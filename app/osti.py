"""OSTI Award DOI Service + ORCID public API for institution enrichment.

Chain: search OSTI by investigator name → extract ORCID ID → query ORCID
public API for current employment → return {institution, country, state}.

No authentication required for either API.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import requests

log = logging.getLogger(__name__)

_OSTI_URL  = "https://www.osti.gov/award-doi-service/api/v1/search"
_ORCID_URL = "https://pub.orcid.org/v3.0"
_TIMEOUT   = 10


# ---------------------------------------------------------------------------
# OSTI search
# ---------------------------------------------------------------------------

def search(
    *,
    investigator: Optional[str] = None,
    award_doi:    Optional[str] = None,
    q:            str           = "*",
    rows:         int           = 20,
) -> list[dict]:
    """Search OSTI Award DOI Service. Returns list of award docs."""
    params: dict = {"rows": rows}
    if investigator:
        params["investigator"] = investigator
    elif award_doi:
        params["award_doi"] = award_doi
    else:
        params["q"] = q
    try:
        r = requests.get(_OSTI_URL, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()["response"]["docs"]
    except Exception as exc:
        log.debug("OSTI search failed (%s): %s", params, exc)
        return []


# ---------------------------------------------------------------------------
# ORCID public API
# ---------------------------------------------------------------------------

def _format_orcid(raw: str) -> str:
    """Convert 16-digit raw ORCID to hyphenated form (0000-0002-0682-9595)."""
    clean = re.sub(r"[^0-9Xx]", "", raw).upper()
    if len(clean) == 16:
        return f"{clean[0:4]}-{clean[4:8]}-{clean[8:12]}-{clean[12:16]}"
    return raw


def _orcid_employment(orcid_id: str) -> dict:
    """Return {institution, country, state} from the person's current ORCID employment."""
    orcid = _format_orcid(orcid_id)
    try:
        r = requests.get(
            f"{_ORCID_URL}/{orcid}/employments",
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
    except Exception as exc:
        log.debug("ORCID lookup failed for %s: %s", orcid, exc)
        return {}

    summaries = []
    for group in data.get("affiliation-group", []):
        for s in group.get("summaries", []):
            es  = s.get("employment-summary", {})
            org = es.get("organization", {})
            if not org.get("name"):
                continue
            addr = org.get("address") or {}
            summaries.append({
                "institution": org["name"],
                "country":     addr.get("country", ""),
                "state":       addr.get("region", ""),
                "end_date":    es.get("end-date"),
            })

    if not summaries:
        return {}

    # Prefer current employment (end_date is None), otherwise take first listed
    current = [s for s in summaries if s["end_date"] is None]
    best = current[0] if current else summaries[0]
    return {
        "institution": best["institution"],
        "country":     best["country"],
        "state":       best["state"],
    }


# ---------------------------------------------------------------------------
# Combined enrichment
# ---------------------------------------------------------------------------

def enrich_person(first_name: str, last_name: str) -> dict:
    """Search OSTI for a person; follow ORCID to get their institution.

    Returns dict with keys: orcid_id, institution, country, state.
    All values may be empty strings if not found.
    """
    result: dict = {"orcid_id": "", "institution": "", "country": "", "state": ""}
    fname_l, lname_l = first_name.lower(), last_name.lower()

    docs = search(investigator=f"{first_name} {last_name}")
    for doc in docs:
        for person in (doc.get("persons") or {}).get("docs", []):
            if (person.get("first_name", "").lower() == fname_l and
                    person.get("last_name", "").lower() == lname_l and
                    person.get("orcid_id")):
                orcid_raw = person["orcid_id"]
                result["orcid_id"] = _format_orcid(orcid_raw)
                inst = _orcid_employment(orcid_raw)
                result.update(inst)
                log.info(
                    "OSTI/ORCID enriched %s %s → %s (ORCID %s)",
                    first_name, last_name,
                    result.get("institution", "—"), result["orcid_id"],
                )
                return result

    return result
