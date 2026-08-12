"""ESAF sync — fetches from APS DM API and upserts into local SQLite."""

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from . import config, db, osti
from .institution import lookup_by_email

# Per-sync ORCID cache: badge → enrich result. Avoids re-querying the same
# person when they appear in multiple ESAFs within one sync run.
_osti_cache: dict[str, dict] = {}

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
        # Try subscript access first (works for dict AND dict-like DM API objects)
        try:
            v = obj[k]
            if v is not None:
                return v
        except (KeyError, TypeError):
            pass
        # Fall back to attribute access
        try:
            v = getattr(obj, k, None)
            if v is not None:
                return v
        except Exception:
            pass
    return default


def _extract_esaf(raw: Any) -> dict:
    """Normalise one raw ESAF record from the DM API."""
    raw_dict = dict(raw) if not isinstance(raw, dict) else raw

    # User list — API fields confirmed: badge, badgeNumber, firstName, lastName,
    # email, piFlag ('Yes'/'No'). No institution field in this API.
    raw_users = _get(raw, "experimentUsers", "users", default=[])
    users = []
    pi_badge = pi_name = ""

    for u in raw_users:
        badge      = str(_get(u, "badge", "badgeNumber", default=""))
        first_name = str(_get(u, "firstName", default=""))
        last_name  = str(_get(u, "lastName",  default=""))
        email      = str(_get(u, "email", default=""))
        pi_flag    = str(_get(u, "piFlag", "isPi", default="No")).strip().lower()
        is_pi      = pi_flag in ("yes", "y", "true", "1")
        role       = "pi" if is_pi else "user"

        affil = lookup_by_email(email)
        orcid_id = ""
        # Fall back to OSTI → ORCID when email-based lookup has no institution
        if not affil["institution"] and first_name and last_name:
            cached = _osti_cache.get(badge)
            if cached is None:
                cached = osti.enrich_person(first_name, last_name)
                _osti_cache[badge] = cached
            if cached.get("institution"):
                affil = {k: cached.get(k, "") for k in ("institution", "country", "state")}
            orcid_id = cached.get("orcid_id", "")
        users.append({
            "badge": badge, "first_name": first_name, "last_name": last_name,
            "institution": affil["institution"], "country": affil["country"],
            "state": affil["state"], "email": email, "role": role,
            "orcid_id": orcid_id,
            "raw_json": dict(u) if not isinstance(u, dict) else u,
        })
        if is_pi and not pi_badge:
            pi_badge       = badge
            pi_name        = f"{first_name} {last_name}".strip()
            pi_institution = affil["institution"]

    if not pi_badge:
        pi_institution = ""

    # Funding sources — not present in listStationEsafs; kept for future use
    funding_sources = []

    # Beamline — API returns beamlineStation ('15-ID-CD') and beamline (['15-ID-C,D'])
    # Use beamlineStation as the canonical value; fall back to first item in beamline list
    beamline = str(_get(raw, "beamlineStation", default=""))
    if not beamline:
        bl_list = _get(raw, "beamline", default=[])
        if isinstance(bl_list, list) and bl_list:
            beamline = str(bl_list[0])
        else:
            beamline = str(bl_list)

    esaf_id     = str(_get(raw, "esafId", "id", "esaf_id", default=""))
    title       = str(_get(raw, "esafTitle", "title", default=""))
    description = str(_get(raw, "description", default=""))
    sector      = str(_get(raw, "sector", default=""))
    status      = str(_get(raw, "esafStatus", "status", default=""))
    start       = str(_get(raw, "experimentStartDate", "startDate", default=""))
    end         = str(_get(raw, "experimentEndDate",   "endDate",   default=""))
    doi         = str(_get(raw, "doi", default=""))

    # Year: parse from experimentStartDate, else current year
    if start:
        try:
            year = int(start[:4])
        except (ValueError, IndexError):
            year = datetime.now().year
    else:
        year = datetime.now().year

    return {
        "esaf_id": esaf_id, "title": title, "description": description,
        "sector": sector, "beamline": beamline, "year": year,
        "status": status, "start_date": start, "end_date": end, "doi": doi,
        "pi_badge": pi_badge, "pi_name": pi_name, "pi_institution": pi_institution,
        "users": users, "funding_sources": funding_sources, "raw_json": raw_dict,
    }


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def run_sync(
    beamline_names: list[str] | None = None,
    years: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Fetch ESAFs from DM API and upsert into local DB. Returns summary dict.

    When dry_run=True, fetches from API and computes what would change but
    does not write to the database. Returns the same dict plus 'preview' list.
    """
    global _osti_cache
    _osti_cache = {}

    from .institution import load_overrides as _load_overrides
    from . import db as _db
    _load_overrides(_db.list_domain_overrides())

    bl  = beamline_names or config.BEAMLINE_NAMES
    yrs = years or config.SYNC_YEARS
    now = datetime.now(timezone.utc).isoformat()

    added = updated = 0
    error_msg = None
    preview: list[dict] = []

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
                log.info("%sSyncing beamline=%s year=%s", "[DRY RUN] " if dry_run else "", beamline, year)
                try:
                    records = api.listStationEsafs(
                        config.STATION_ID,
                        beamlineName=beamline,
                        year=str(year),
                    )
                except Exception as exc:
                    log.warning("API error beamline=%s year=%s: %s", beamline, year, exc)
                    continue

                records = list(records)
                log.info("API returned %d records for beamline=%s year=%s", len(records), beamline, year)
                for raw in records:
                    try:
                        data = _extract_esaf(raw)
                        if dry_run:
                            existing = db.get_esaf(data["esaf_id"])
                            action = "add" if existing is None else "update"
                            if action == "add":
                                added += 1
                            else:
                                updated += 1
                            preview.append({
                                "esaf_id": data["esaf_id"],
                                "title": data["title"],
                                "beamline": data["beamline"],
                                "year": data["year"],
                                "status": data["status"],
                                "action": action,
                            })
                        else:
                            action = db.upsert_esaf(data, now)
                            if action == "added":
                                added += 1
                            else:
                                updated += 1
                    except Exception as exc:
                        log.warning("Failed to process ESAF %s: %s", raw, exc)

    except ImportError:
        error_msg = "dm library not installed — install from APS DM package source"
        log.error(error_msg)
    except Exception as exc:
        error_msg = str(exc)
        log.error("Sync failed: %s", exc)

    if not dry_run:
        db.log_sync(
            beamlines="|".join(bl),
            years=",".join(str(y) for y in yrs),
            added=added,
            updated=updated,
            error=error_msg,
        )
    return {"added": added, "updated": updated, "error": error_msg, "preview": preview, "dry_run": dry_run}


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
