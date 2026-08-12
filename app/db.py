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


def propagate_pi_group_by_pi_name(
    group_name: str, pi_name: str, institution: str = ""
) -> int:
    return _r().propagate_pi_group_by_pi_name(group_name, pi_name, institution)


def clear_pi_group_assignments(group_name: str) -> int:
    return _r().clear_pi_group_assignments(group_name)


def set_gup_technique(gup_id: str, technique: str) -> None:
    _r().set_gup_technique(gup_id, technique)


def set_pi_group_technique(name: str, technique: str) -> None:
    _r().set_pi_group_technique(name, technique)


def add_pi_group_technique(name: str, technique: str) -> None:
    _r().add_pi_group_technique(name, technique)


def set_esaf_technique(esaf_id: str, technique: str) -> None:
    _r().set_esaf_technique(esaf_id, technique)


def rename_pi_group(old_name: str, new_name: str) -> None:
    _r().rename_pi_group(old_name, new_name)


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

def get_stats(
    year_from: Optional[int] = None,
    year_to:   Optional[int] = None,
    technique: Optional[str] = None,
    exclude_scientists: bool = False,
) -> dict:
    return _r().get_stats(
        year_from=year_from, year_to=year_to,
        technique=technique, exclude_scientists=exclude_scientists,
    )


def list_unique_users(
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    technique: Optional[str] = None,
    exclude_scientists: bool = False,
) -> list[dict]:
    return _r().list_unique_users(
        year_from=year_from, year_to=year_to,
        technique=technique, exclude_scientists=exclude_scientists,
    )


def list_beamline_scientists() -> list[dict]:
    return _r().list_beamline_scientists()


def add_beamline_scientist(badge: str) -> bool:
    return _r().add_beamline_scientist(badge)


def remove_beamline_scientist(badge: str) -> bool:
    return _r().remove_beamline_scientist(badge)


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


# ------------------------------------------------------------------
# GUPs (General User Proposals)
# ------------------------------------------------------------------

def list_gups(
    search: Optional[str] = None,
    run_cycle: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    return _r().list_gups(search=search, run_cycle=run_cycle, limit=limit, offset=offset)


def get_gup(gup_id: str) -> Optional[dict]:
    return _r().get_gup(gup_id)


def count_gups(
    search: Optional[str] = None,
    run_cycle: Optional[str] = None,
) -> int:
    return _r().count_gups(search=search, run_cycle=run_cycle)


def upsert_gup(data: dict, now: str) -> str:
    return _r().upsert_gup(data, now)


def delete_gup(gup_id: str) -> bool:
    return _r().delete_gup(gup_id)


def get_esafs_for_gup(gup_id: str) -> list[dict]:
    return _r().get_esafs_for_gup(gup_id)


def update_esaf_pdf(esaf_id: str, gup_id: str, pdf_path: str) -> None:
    _r().update_esaf_pdf(esaf_id, gup_id, pdf_path)


def propagate_gup_funding(gup_id: str, funding_strings: list[str]) -> int:
    return _r().propagate_gup_funding(gup_id, funding_strings)


def get_gup_run_cycles() -> list[str]:
    return _r().get_gup_run_cycles()


def list_distinct_institutions() -> list[str]:
    return _r().list_distinct_institutions()


# ------------------------------------------------------------------
# Institution ROR classification
# ------------------------------------------------------------------

def list_institution_ror() -> list[dict]:
    return _r().list_institution_ror()


def upsert_institution_ror(name: str, data: dict) -> None:
    _r().upsert_institution_ror(name, data)


def sync_institution_names() -> int:
    return _r().sync_institution_names()


def rename_institution(old_name: str, new_name: str) -> dict:
    return _r().rename_institution(old_name, new_name)


def set_institution_manual_types(name: str, types: list[str]) -> None:
    _r().set_institution_manual_types(name, types)
