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
    def update_esaf_fields(
        self, esaf_id: str, notes: str, custom_fields: dict, pi_group: str = ""
    ) -> bool: ...

    # ------------------------------------------------------------------
    # PI Groups
    # ------------------------------------------------------------------

    @abstractmethod
    def list_pi_groups(self) -> list[dict]: ...

    @abstractmethod
    def upsert_pi_group(
        self, name: str, pi_name: str = "", pi_email: str = "",
        institution: str = "", country: str = "", state: str = "", orcid_id: str = ""
    ) -> None: ...

    @abstractmethod
    def delete_pi_group(self, name: str) -> bool: ...

    @abstractmethod
    def list_users_for_lookup(self, q: str = "") -> list[dict]: ...

    @abstractmethod
    def propagate_pi_group_by_pi_name(
        self, group_name: str, pi_name: str, institution: str = ""
    ) -> int:
        """Set pi_group on ESAFs whose pi_name contains ALL tokens of pi_name
        (case-insensitive) and whose pi_institution matches (if provided).
        Only updates ESAFs where pi_group is not yet set.
        Returns the number of ESAFs updated."""
        ...

    @abstractmethod
    def clear_pi_group_assignments(self, group_name: str) -> int:
        """Clear pi_group on all ESAFs assigned to group_name.
        Returns the number of ESAFs cleared."""
        ...

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
    def get_stats(
        self,
        year_from: Optional[int] = None,
        year_to:   Optional[int] = None,
        technique: Optional[str] = None,
        exclude_scientists: bool = False,
    ) -> dict: ...

    @abstractmethod
    def get_user_detail(self, badge: str) -> Optional[dict]:
        """Return full user record plus all ESAFs they appear on."""
        ...

    @abstractmethod
    def list_unique_users(
        self,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        technique: Optional[str] = None,
        exclude_scientists: bool = False,
    ) -> list[dict]:
        """Return one row per unique user across Approved ESAFs, with aggregated technique list."""
        ...

    @abstractmethod
    def list_beamline_scientists(self) -> list[dict]:
        """Return all rows from beamline_scientists, sorted by name."""
        ...

    @abstractmethod
    def add_beamline_scientist(self, badge: str, start_date: str = "") -> bool:
        """Add a user to the beamline scientists list. Returns False if badge not found."""
        ...

    @abstractmethod
    def update_beamline_scientist(self, badge: str, start_date: str) -> bool:
        """Update the start_date for a beamline scientist. Returns False if not found."""
        ...

    @abstractmethod
    def remove_beamline_scientist(self, badge: str) -> bool:
        """Remove a user from the beamline scientists list. Returns False if not found."""
        ...

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

    # ------------------------------------------------------------------
    # Domain affiliation overrides
    # ------------------------------------------------------------------

    @abstractmethod
    def list_domain_overrides(self) -> list[dict]: ...

    @abstractmethod
    def set_domain_override(
        self, domain: str, institution: str, country: str, state: str
    ) -> None: ...

    @abstractmethod
    def delete_domain_override(self, domain: str) -> bool: ...

    @abstractmethod
    def apply_domain_override(
        self, domain: str, institution: str, country: str, state: str
    ) -> int:
        """Update all users whose email matches @domain. Returns row count."""
        ...

    # ------------------------------------------------------------------
    # GUPs (General User Proposals)
    # ------------------------------------------------------------------

    @abstractmethod
    def list_gups(
        self,
        search: Optional[str] = None,
        run_cycle: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]: ...

    @abstractmethod
    def get_gup(self, gup_id: str) -> Optional[dict]: ...

    @abstractmethod
    def count_gups(
        self,
        search: Optional[str] = None,
        run_cycle: Optional[str] = None,
    ) -> int: ...

    @abstractmethod
    def upsert_gup(self, data: dict, now: str) -> str:
        """Insert or update one GUP. Returns 'added' or 'updated'."""
        ...

    @abstractmethod
    def delete_gup(self, gup_id: str) -> bool: ...

    @abstractmethod
    def get_esafs_for_gup(self, gup_id: str) -> list[dict]: ...

    @abstractmethod
    def update_esaf_pdf(self, esaf_id: str, gup_id: str, pdf_path: str) -> None:
        """Set gup_id and pdf_path on an ESAF record."""
        ...

    @abstractmethod
    def propagate_gup_funding(self, gup_id: str, funding_strings: list[str]) -> int:
        """Replace funding_sources on all ESAFs linked to gup_id. Returns count updated."""
        ...

    @abstractmethod
    def get_gup_run_cycles(self) -> list[str]:
        """Return distinct run_cycle values from the gups table."""
        ...

    @abstractmethod
    def set_gup_technique(self, gup_id: str, technique: str) -> None:
        """Set the technique classification on a GUP."""
        ...

    @abstractmethod
    def set_pi_group_technique(self, name: str, technique: str) -> None:
        """Set the technique classification on a PI Group (replaces existing value)."""
        ...

    @abstractmethod
    def add_pi_group_technique(self, name: str, technique: str) -> None:
        """Add a technique to a PI Group's multi-select set without removing others."""
        ...

    @abstractmethod
    def set_esaf_technique(self, esaf_id: str, technique: str) -> None:
        """Set the technique classification ('Surf', 'Xtal', 'ASWAXS', or '') on an ESAF."""
        ...

    @abstractmethod
    def rename_pi_group(self, old_name: str, new_name: str) -> None:
        """Rename a PI group and update pi_group references on all linked ESAFs."""
        ...

    @abstractmethod
    def list_distinct_institutions(self) -> list[str]:
        """Return sorted distinct institution names from users, esafs, pi_groups, and gups."""
        ...

    # ------------------------------------------------------------------
    # Institution ROR classification
    # ------------------------------------------------------------------

    @abstractmethod
    def list_institution_ror(self) -> list[dict]:
        """Return all rows from institution_ror, sorted by name."""
        ...

    @abstractmethod
    def upsert_institution_ror(self, name: str, data: dict) -> None:
        """Insert or update a ROR lookup result for a given institution name."""
        ...

    @abstractmethod
    def sync_institution_names(self) -> int:
        """Ensure all distinct institution names have a pending row in institution_ror.
        Returns the number of new rows inserted."""
        ...

    @abstractmethod
    def rename_institution(self, old_name: str, new_name: str) -> dict:
        """Rename an institution across users, esafs, pi_groups, gups, and institution_ror.
        Returns dict of per-table update counts."""
        ...

    @abstractmethod
    def set_institution_manual_types(self, name: str, types: list[str]) -> None:
        """Set the manual org-type override for an institution."""
        ...


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
