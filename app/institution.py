"""Institution, country, and state lookup from email domain.

Three-layer lookup:
  1. _override_map — user-defined domain overrides stored in the DB (highest priority).
  2. _DOMAIN_MAP   — curated entries for national labs, DOE facilities, and
                     industry where the Hipo university DB has no entry.
  3. University DB — Hipo/university-domains-list (~10 k universities worldwide),
                     fetched once and cached at ~/.aps-esaf-fetcher/university_domains.json.

lookup_by_email() checks the override map first, then the manual map, then
the university DB.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_EMPTY: dict = {"institution": "", "country": "", "state": ""}

# ---------- User-defined domain overrides (loaded from DB at startup) ----------
_override_map: dict[str, dict] = {}


def load_overrides(overrides: list[dict]) -> None:
    """Rebuild _override_map from a list of dicts with keys domain/institution/country/state."""
    global _override_map
    _override_map = {
        row["domain"]: {
            "institution": row.get("institution", ""),
            "country":     row.get("country", ""),
            "state":       row.get("state", ""),
        }
        for row in overrides
        if row.get("domain")
    }


def set_override(domain: str, inst: str, country: str, state: str) -> None:
    """Update a single entry in the in-memory override map."""
    _override_map[domain.lower().strip()] = {
        "institution": inst,
        "country":     country,
        "state":       state,
    }

_HIPO_URL = (
    "https://raw.githubusercontent.com/Hipo/university-domains-list"
    "/master/world_universities_and_domains.json"
)
_CACHE_PATH = Path.home() / ".aps-esaf-fetcher" / "university_domains.json"

# US state full-name → abbreviation
_US_STATE_ABBR: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}

# ---------- Manual map — national labs, DOE facilities, synchrotrons, industry ----------
# These take precedence over the university DB.
_DOMAIN_MAP: dict[str, dict] = {
    "anl.gov":           {"institution": "Argonne National Laboratory",              "country": "US", "state": "IL"},
    "ameslab.gov":       {"institution": "Ames National Laboratory",                 "country": "US", "state": "IA"},
    "bnl.gov":           {"institution": "Brookhaven National Laboratory",           "country": "US", "state": "NY"},
    "fnal.gov":          {"institution": "Fermi National Accelerator Laboratory",    "country": "US", "state": "IL"},
    "inl.gov":           {"institution": "Idaho National Laboratory",               "country": "US", "state": "ID"},
    "jlab.org":          {"institution": "Jefferson Lab",                            "country": "US", "state": "VA"},
    "lanl.gov":          {"institution": "Los Alamos National Laboratory",           "country": "US", "state": "NM"},
    "lbl.gov":           {"institution": "Lawrence Berkeley National Laboratory",    "country": "US", "state": "CA"},
    "llnl.gov":          {"institution": "Lawrence Livermore National Laboratory",   "country": "US", "state": "CA"},
    "nist.gov":          {"institution": "National Institute of Standards and Technology", "country": "US", "state": "MD"},
    "nih.gov":           {"institution": "National Institutes of Health",            "country": "US", "state": "MD"},
    "nrel.gov":          {"institution": "National Renewable Energy Laboratory",     "country": "US", "state": "CO"},
    "ornl.gov":          {"institution": "Oak Ridge National Laboratory",            "country": "US", "state": "TN"},
    "pnnl.gov":          {"institution": "Pacific Northwest National Laboratory",    "country": "US", "state": "WA"},
    "pppl.gov":          {"institution": "Princeton Plasma Physics Laboratory",      "country": "US", "state": "NJ"},
    "sandia.gov":        {"institution": "Sandia National Laboratories",             "country": "US", "state": "NM"},
    "slac.stanford.edu": {"institution": "SLAC National Accelerator Laboratory",     "country": "US", "state": "CA"},
    "sns.gov":           {"institution": "Spallation Neutron Source / ORNL",         "country": "US", "state": "TN"},
    "cnl.ca":            {"institution": "Canadian Nuclear Laboratories",            "country": "CA", "state": ""},
    "esrf.eu":           {"institution": "European Synchrotron Radiation Facility",  "country": "FR", "state": ""},
    "diamond.ac.uk":     {"institution": "Diamond Light Source",                     "country": "GB", "state": ""},
    "desy.de":           {"institution": "DESY",                                     "country": "DE", "state": ""},
    "psi.ch":            {"institution": "Paul Scherrer Institut",                   "country": "CH", "state": ""},
    "maxiv.lu.se":       {"institution": "MAX IV Laboratory",                        "country": "SE", "state": ""},
    "helmholtz-berlin.de": {"institution": "Helmholtz-Zentrum Berlin",               "country": "DE", "state": ""},
    "dow.com":           {"institution": "Dow Chemical",                             "country": "US", "state": "MI"},
    "dupont.com":        {"institution": "DuPont",                                   "country": "US", "state": "DE"},
    "3m.com":            {"institution": "3M",                                       "country": "US", "state": "MN"},
    "abbott.com":        {"institution": "Abbott Laboratories",                      "country": "US", "state": "IL"},
    "pfizer.com":        {"institution": "Pfizer",                                   "country": "US", "state": "NY"},
    "merck.com":         {"institution": "Merck",                                    "country": "US", "state": "NJ"},
    "novartis.com":      {"institution": "Novartis",                                 "country": "CH", "state": ""},
    "bp.com":            {"institution": "BP",                                       "country": "GB", "state": ""},
    "exxonmobil.com":    {"institution": "ExxonMobil",                              "country": "US", "state": "TX"},
}

# ---------- University DB (Hipo) — loaded lazily, thread-safe ----------

_uni_db: dict | None = None
_uni_db_lock = threading.Lock()


def _build_uni_db(raw: list) -> dict:
    db: dict = {}
    for entry in raw:
        name    = entry.get("name", "")
        country = entry.get("alpha_two_code", "")
        sp      = entry.get("state-province") or ""
        if country == "US":
            state = _US_STATE_ABBR.get(sp, sp)
        else:
            state = sp
        for domain in entry.get("domains", []):
            db[domain.lower()] = {"institution": name, "country": country, "state": state}
    return db


def _load_uni_db() -> dict:
    global _uni_db
    if _uni_db is not None:
        return _uni_db
    with _uni_db_lock:
        if _uni_db is not None:
            return _uni_db

        # Try local cache first
        if _CACHE_PATH.exists():
            try:
                raw = json.loads(_CACHE_PATH.read_text())
                _uni_db = _build_uni_db(raw)
                log.info("Loaded university DB from cache (%d domains)", len(_uni_db))
                return _uni_db
            except Exception as exc:
                log.warning("Could not read university DB cache: %s", exc)

        # Fetch from GitHub
        try:
            import httpx
            log.info("Fetching university domain list from GitHub…")
            resp = httpx.get(_HIPO_URL, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            raw = resp.json()
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_PATH.write_text(resp.text)
            _uni_db = _build_uni_db(raw)
            log.info("University DB ready (%d domains)", len(_uni_db))
        except Exception as exc:
            log.warning("Could not fetch university DB: %s — falling back to manual map", exc)
            _uni_db = {}

    return _uni_db


def _domain_lookup(db: dict, domain: str) -> dict | None:
    """Strip leading subdomains until a match is found."""
    d = domain
    while d:
        entry = db.get(d)
        if entry:
            return entry
        parts = d.split(".", 1)
        if len(parts) < 2:
            break
        d = parts[1]
    return None


def lookup_by_email(email: str) -> dict:
    """Return {institution, country, state} for an email address.

    Check order: user-defined override map → manual map (national labs,
    companies) → Hipo university database. Returns empty strings for
    unknown domains.
    """
    if not email or "@" not in email:
        return _EMPTY.copy()
    domain = email.split("@", 1)[1].lower().strip()

    entry = _domain_lookup(_override_map, domain)
    if entry:
        return entry.copy()

    entry = _domain_lookup(_DOMAIN_MAP, domain)
    if entry:
        return entry.copy()

    entry = _domain_lookup(_load_uni_db(), domain)
    if entry:
        return entry.copy()

    return _EMPTY.copy()


def refresh_uni_db() -> int:
    """Force re-download of the university DB. Returns domain count."""
    global _uni_db
    try:
        import httpx
        resp = httpx.get(_HIPO_URL, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        raw = resp.json()
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(resp.text)
        with _uni_db_lock:
            _uni_db = _build_uni_db(raw)
        log.info("University DB refreshed (%d domains)", len(_uni_db))
        return len(_uni_db)
    except Exception as exc:
        log.error("University DB refresh failed: %s", exc)
        return 0
