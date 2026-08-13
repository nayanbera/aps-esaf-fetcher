"""ROR (Research Organization Registry) API client."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_ROR_API = "https://api.ror.org/v2/organizations"

_TYPE_COLORS = {
    # ROR types
    "education":    "primary",
    "government":   "success",
    "facility":     "warning text-dark",
    "funder":       "dark",
    "company":      "secondary",
    "nonprofit":    "info text-dark",
    "healthcare":   "danger",
    "archive":      "light text-dark border",
    "other":        "secondary",
    # CSV-imported institution types
    "academic":     "primary",
    "industry":     "secondary",
    "national lab":        "warning text-dark",
    "national laboratory": "warning text-dark",
    "federal":      "success",
    "non-profit":   "info text-dark",
    "hospital":     "danger",
    "medical":      "danger",
    "international":"info text-dark",
    "foreign":      "info text-dark",
}


def type_badge_class(org_type: str) -> str:
    return _TYPE_COLORS.get(org_type.lower(), "secondary")


def lookup_institution(name: str) -> dict:
    """Look up an institution via the ROR affiliation endpoint.

    Returns a dict with keys: ror_id, ror_name, org_types (list[str]),
    country, website, score (float), status ("found"/"not_found"/"error").
    """
    try:
        resp = httpx.get(
            _ROR_API,
            params={"affiliation": name},
            timeout=10.0,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("ROR lookup failed for %r: %s", name, exc)
        return _empty("error")

    items = data.get("items", [])
    chosen = next((i for i in items if i.get("chosen")), None)
    if chosen is None:
        return _empty("not_found")

    org = chosen.get("organization", {})
    ror_id = org.get("id", "")
    names = org.get("names", [])
    ror_name = next(
        (n["value"] for n in names if "ror_display" in n.get("types", [])),
        names[0]["value"] if names else "",
    )
    org_types = [t.lower() for t in org.get("types", [])]
    locations = org.get("locations", [])
    country = (
        locations[0].get("geonames_details", {}).get("country_name", "")
        if locations else ""
    )
    website = next(
        (lnk["value"] for lnk in org.get("links", []) if lnk.get("type") == "website"),
        "",
    )

    return {
        "status":    "found",
        "ror_id":    ror_id,
        "ror_name":  ror_name,
        "org_types": org_types,
        "country":   country,
        "website":   website,
        "score":     float(chosen.get("score", 0.0)),
    }


def _empty(status: str) -> dict:
    return {
        "status": status, "ror_id": "", "ror_name": "",
        "org_types": [], "country": "", "website": "", "score": 0.0,
    }
