"""ESAF sync — fetches from APS DM API and upserts into local SQLite."""

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db

log = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------
# The DM API returns dict-like objects. Field names follow APS naming
# conventions; we try the known variants and fall back gracefully.

def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Try multiple attribute/key names on a dict-like object."""
    for k in keys:
        try:
            v = obj[k] if isinstance(obj, dict) else getattr(obj, k, None)
            if v is not None:
                return v
        except (KeyError, TypeError):
            continue
    return default


def _extract_esaf(raw: Any) -> dict:
    """Normalise one raw ESAF record from the DM API."""
    raw_dict = dict(raw) if not isinstance(raw, dict) else raw

    # User list
    raw_users = _get(raw, "experimentUsers", "users", default=[])
    users = []
    pi_badge = pi_name = institution = ""

    for u in raw_users:
        badge      = str(_get(u, "badge", "badgeNumber", default=""))
        first_name = str(_get(u, "firstName", "first_name", default=""))
        last_name  = str(_get(u, "lastName",  "last_name",  default=""))
        inst       = str(_get(u, "instName",  "institution", "affiliation", default=""))
        email      = str(_get(u, "email", default=""))
        is_pi      = str(_get(u, "piFlag", "isPi", default="N")).upper() in ("Y", "YES", "TRUE", "1")
        role       = "pi" if is_pi else str(_get(u, "role", default="user")).lower()

        users.append({
            "badge": badge, "first_name": first_name, "last_name": last_name,
            "institution": inst, "email": email, "role": role,
            "raw_json": dict(u) if not isinstance(u, dict) else u,
        })
        if is_pi and not pi_badge:
            pi_badge = badge
            pi_name  = f"{first_name} {last_name}".strip()
            institution = inst

    # Funding sources — stored as a flat list of strings
    raw_funding = _get(raw, "fundingSupport", "fundingSupportList",
                       "fundingSourceList", default="")
    if isinstance(raw_funding, str):
        funding_sources = [s.strip() for s in raw_funding.split(",") if s.strip()]
    elif isinstance(raw_funding, list):
        funding_sources = [
            str(_get(f, "fundingSupport", "source", default=f)) for f in raw_funding
        ]
    else:
        funding_sources = []

    # Beamline — the API can return a list of beamlineReqs objects
    beamline_raw = _get(raw, "beamlineReqs", "beamlineName", "beamline", default=[])
    if isinstance(beamline_raw, list) and beamline_raw:
        first = beamline_raw[0]
        beamline = str(_get(first, "beamlineName", "name", default=first))
    else:
        beamline = str(beamline_raw)

    esaf_id  = str(_get(raw, "esafId", "id", "esaf_id", default=""))
    title    = str(_get(raw, "title", "esafTitle", default=""))
    status   = str(_get(raw, "esafStatus", "status", default=""))
    start    = str(_get(raw, "experimentStartDate", "startDate", "start_date", default=""))
    end      = str(_get(raw, "experimentEndDate",   "endDate",   "end_date",   default=""))

    # Year: prefer explicit field, else parse from start_date, else current year
    year_raw = _get(raw, "year")
    if year_raw:
        year = int(year_raw)
    elif start:
        try:
            year = int(start[:4])
        except (ValueError, IndexError):
            year = datetime.now().year
    else:
        year = datetime.now().year

    return {
        "esaf_id": esaf_id, "title": title, "beamline": beamline,
        "year": year, "status": status, "start_date": start, "end_date": end,
        "pi_badge": pi_badge, "pi_name": pi_name, "institution": institution,
        "users": users, "funding_sources": funding_sources, "raw_json": raw_dict,
    }


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def run_sync(beamline_names: list[str] | None = None, years: list[str] | None = None) -> dict:
    """Fetch ESAFs from DM API and upsert into local DB. Returns summary dict."""
    bl  = beamline_names or config.BEAMLINE_NAMES
    yrs = years or config.SYNC_YEARS
    now = datetime.now(timezone.utc).isoformat()

    added = updated = 0
    error_msg = None

    try:
        from dm.aps_db_web_service.api.esafApsDbApi import EsafApsDbApi

        if not config.DM_USERNAME or not config.DM_PASSWORD:
            raise RuntimeError("DM_USERNAME and DM_PASSWORD must be set in .env")

        api = EsafApsDbApi(
            username=config.DM_USERNAME,
            password=config.DM_PASSWORD,
            url=config.DM_URL,
        )

        for beamline in bl:
            for year in yrs:
                log.info("Syncing beamline=%s year=%s", beamline, year)
                try:
                    records = api.listStationEsafs(
                        config.STATION_ID,
                        beamlineName=beamline,
                        year=str(year),
                    )
                except Exception as exc:
                    log.warning("API error beamline=%s year=%s: %s", beamline, year, exc)
                    continue

                for raw in records:
                    try:
                        data   = _extract_esaf(raw)
                        action = db.upsert_esaf(data, now)
                        if action == "added":
                            added += 1
                        else:
                            updated += 1
                    except Exception as exc:
                        log.warning("Failed to upsert ESAF %s: %s", raw, exc)

    except ImportError:
        error_msg = "dm library not installed — install from APS DM package source"
        log.error(error_msg)
    except Exception as exc:
        error_msg = str(exc)
        log.error("Sync failed: %s", exc)

    db.log_sync(
        beamlines="|".join(bl),
        years=",".join(str(y) for y in yrs),
        added=added,
        updated=updated,
        error=error_msg,
    )
    return {"added": added, "updated": updated, "error": error_msg}


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def start_scheduler():
    global _scheduler
    if config.SYNC_INTERVAL_HOURS <= 0:
        log.info("Auto-sync disabled (SYNC_INTERVAL_HOURS=0)")
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        run_sync,
        trigger="interval",
        hours=config.SYNC_INTERVAL_HOURS,
        id="esaf_sync",
        replace_existing=True,
    )
    _scheduler.start()
    log.info("Sync scheduler started — interval %d h", config.SYNC_INTERVAL_HOURS)


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
