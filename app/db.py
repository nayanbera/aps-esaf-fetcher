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


def update_esaf_fields(esaf_id: str, notes: str, custom_fields: dict) -> bool:
    return _r().update_esaf_fields(esaf_id, notes, custom_fields)


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
