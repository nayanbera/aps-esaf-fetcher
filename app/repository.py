"""Abstract repository interface and factory function."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ESAFRepository(ABC):

    @abstractmethod
    def init_db(self) -> None: ...

    # ------------------------------------------------------------------
    # ESAFs
    # ------------------------------------------------------------------

    @abstractmethod
    def list_esafs(
        self,
        year: Optional[int] = None,
        beamline: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]: ...

    @abstractmethod
    def get_esaf(self, esaf_id: str) -> Optional[dict]: ...

    @abstractmethod
    def count_esafs(
        self,
        year: Optional[int] = None,
        beamline: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int: ...

    @abstractmethod
    def get_filter_options(self) -> dict:
        """Return distinct years, beamlines, and statuses for filter dropdowns."""
        ...

    @abstractmethod
    def update_esaf_fields(self, esaf_id: str, notes: str, custom_fields: dict) -> bool: ...

    @abstractmethod
    def upsert_esaf(self, data: dict, now: str) -> str:
        """Insert or update one ESAF. Returns 'added' or 'updated'."""
        ...

    # ------------------------------------------------------------------
    # Sync log
    # ------------------------------------------------------------------

    @abstractmethod
    def log_sync(
        self,
        beamlines: str,
        years: str,
        added: int,
        updated: int,
        error: Optional[str] = None,
    ) -> None: ...

    @abstractmethod
    def get_last_sync(self) -> Optional[dict]: ...

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @abstractmethod
    def get_stats(self) -> dict: ...

    # ------------------------------------------------------------------
    # Custom field definitions
    # ------------------------------------------------------------------

    @abstractmethod
    def list_field_definitions(self) -> list[dict]: ...

    @abstractmethod
    def upsert_field_definition(
        self, name: str, label: str, field_type: str, options: list[str]
    ) -> None: ...

    @abstractmethod
    def delete_field_definition(self, name: str) -> bool: ...


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_repository() -> ESAFRepository:
    """Return the configured backend repository."""
    from . import config

    if config.MONGODB_URI:
        from .backends.mongo_backend import MongoESAFRepository
        return MongoESAFRepository(uri=config.MONGODB_URI, db_name=config.MONGODB_DB)

    from .backends.sqlite_backend import SQLiteESAFRepository
    return SQLiteESAFRepository(db_path=config.DB_PATH)
