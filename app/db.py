"""Database access — thin proxy to the configured backend repository.

Routers import functions from this module unchanged. The backend
(SQLite or MongoDB) is selected by MONGODB_URI in the environment.
"""

from __future__ import annotations

from typing import Optional

from .repository import ESAFRepository

_repo: ESAFRepository | None = None


def _r() -> ESAFRepository:
    if _repo is None:
        raise RuntimeError("db.init_db() has not been called")
    return _repo


def init_db() -> None:
    global _repo
    from .repository import get_repository
    _repo = get_repository()
    _repo.init_db()


# ------------------------------------------------------------------
# ESAFs
# ------------------------------------------------------------------

def list_esafs(
    year: Optional[int] = None,
    beamline: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    return _r().list_esafs(
        year=year, beamline=beamline, status=status,
        search=search, limit=limit, offset=offset,
    )


def get_esaf(esaf_id: str) -> Optional[dict]:
    return _r().get_esaf(esaf_id)


def count_esafs(
    year: Optional[int] = None,
    beamline: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> int:
    return _r().count_esafs(year=year, beamline=beamline, status=status, search=search)


def get_filter_options() -> dict:
    return _r().get_filter_options()


def update_esaf_fields(
    esaf_id: str, notes: str, custom_fields: dict, pi_group: str = ""
) -> bool:
    return _r().update_esaf_fields(esaf_id, notes, custom_fields, pi_group)


def list_pi_groups() -> list[dict]:
    return _r().list_pi_groups()


def upsert_pi_group(
    name: str, pi_name: str = "", pi_email: str = "",
    institution: str = "", country: str = "", state: str = "", orcid_id: str = ""
) -> None:
    _r().upsert_pi_group(name, pi_name, pi_email, institution, country, state, orcid_id)


def delete_pi_group(name: str) -> bool:
    return _r().delete_pi_group(name)


def list_users_for_lookup(q: str = "") -> list[dict]:
    return _r().list_users_for_lookup(q)


def upsert_esaf(data: dict, now: str) -> str:
    return _r().upsert_esaf(data, now)


# ------------------------------------------------------------------
# Sync log
# ------------------------------------------------------------------

def log_sync(
    beamlines: str,
    years: str,
    added: int,
    updated: int,
    error: Optional[str] = None,
) -> None:
    _r().log_sync(beamlines, years, added, updated, error)


def get_last_sync() -> Optional[dict]:
    return _r().get_last_sync()


# ------------------------------------------------------------------
# Statistics
# ------------------------------------------------------------------

def get_stats() -> dict:
    return _r().get_stats()


# ------------------------------------------------------------------
# Custom field definitions
# ------------------------------------------------------------------

def list_field_definitions() -> list[dict]:
    return _r().list_field_definitions()


def upsert_field_definition(
    name: str, label: str, field_type: str, options: list[str]
) -> None:
    _r().upsert_field_definition(name, label, field_type, options)


def delete_field_definition(name: str) -> bool:
    return _r().delete_field_definition(name)


# ------------------------------------------------------------------
# Domain affiliation overrides
# ------------------------------------------------------------------

def list_domain_overrides() -> list[dict]:
    return _r().list_domain_overrides()


def set_domain_override(
    domain: str, institution: str, country: str, state: str
) -> None:
    _r().set_domain_override(domain, institution, country, state)


def delete_domain_override(domain: str) -> bool:
    return _r().delete_domain_override(domain)


def apply_domain_override(
    domain: str, institution: str, country: str, state: str
) -> int:
    return _r().apply_domain_override(domain, institution, country, state)
