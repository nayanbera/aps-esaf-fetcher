"""SQLite backend — all logic from the original db.py wrapped in a class."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..repository import ESAFRepository


_SCHEMA = """
CREATE TABLE IF NOT EXISTS esafs (
    esaf_id       TEXT PRIMARY KEY,
    title         TEXT,
    description   TEXT DEFAULT '',
    sector        TEXT DEFAULT '',
    beamline      TEXT,
    year          INTEGER,
    status        TEXT,
    start_date    TEXT,
    end_date      TEXT,
    doi           TEXT DEFAULT '',
    pi_badge      TEXT,
    pi_name       TEXT,
    pi_institution TEXT DEFAULT '',
    pi_group      TEXT DEFAULT '',
    gup_id        TEXT DEFAULT '',
    pdf_path      TEXT DEFAULT '',
    raw_json      TEXT,
    notes         TEXT DEFAULT '',
    custom_fields TEXT DEFAULT '{}',
    last_synced   TEXT,
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    badge         TEXT PRIMARY KEY,
    first_name    TEXT,
    last_name     TEXT,
    institution   TEXT,
    country       TEXT DEFAULT '',
    state         TEXT DEFAULT '',
    email         TEXT,
    orcid_id      TEXT DEFAULT '',
    raw_json      TEXT
);

CREATE TABLE IF NOT EXISTS esaf_users (
    esaf_id  TEXT NOT NULL REFERENCES esafs(esaf_id) ON DELETE CASCADE,
    badge    TEXT NOT NULL,
    role     TEXT DEFAULT 'user',
    PRIMARY KEY (esaf_id, badge)
);

CREATE TABLE IF NOT EXISTS funding_sources (
    esaf_id TEXT NOT NULL REFERENCES esafs(esaf_id) ON DELETE CASCADE,
    source  TEXT NOT NULL,
    PRIMARY KEY (esaf_id, source)
);

CREATE TABLE IF NOT EXISTS custom_field_definitions (
    name        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    field_type  TEXT NOT NULL DEFAULT 'text',
    options     TEXT DEFAULT '[]',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at       TEXT DEFAULT (datetime('now')),
    beamlines       TEXT,
    years           TEXT,
    records_added   INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS pi_groups (
    name        TEXT PRIMARY KEY,
    pi_name     TEXT NOT NULL DEFAULT '',
    pi_email    TEXT NOT NULL DEFAULT '',
    institution TEXT NOT NULL DEFAULT '',
    country     TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT '',
    orcid_id    TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS domain_overrides (
    domain      TEXT PRIMARY KEY,
    institution TEXT NOT NULL DEFAULT '',
    country     TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gups (
    gup_id           TEXT PRIMARY KEY,
    title            TEXT DEFAULT '',
    pi_name          TEXT DEFAULT '',
    pi_institution   TEXT DEFAULT '',
    run_cycle        TEXT DEFAULT '',
    proposal_call    TEXT DEFAULT '',
    proposal_type    TEXT DEFAULT '',
    primary_area     TEXT DEFAULT '',
    additional_areas TEXT DEFAULT '',
    review_panel     TEXT DEFAULT '',
    co_pi            TEXT DEFAULT '',
    co_proposers     TEXT DEFAULT '',
    keywords         TEXT DEFAULT '',
    abstract         TEXT DEFAULT '',
    beamlines        TEXT DEFAULT '',
    status           TEXT DEFAULT '',
    submitted_at     TEXT DEFAULT '',
    notes            TEXT DEFAULT '',
    pdf_path         TEXT DEFAULT '',
    raw_fields       TEXT DEFAULT '{}',
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS gup_funding_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    gup_id       TEXT NOT NULL REFERENCES gups(gup_id) ON DELETE CASCADE,
    agency       TEXT DEFAULT '',
    details      TEXT DEFAULT '',
    grant_number TEXT DEFAULT '',
    percentage   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS institution_ror (
    name         TEXT PRIMARY KEY,
    ror_id       TEXT DEFAULT '',
    ror_name     TEXT DEFAULT '',
    org_types    TEXT DEFAULT '[]',
    manual_types TEXT DEFAULT '[]',
    country      TEXT DEFAULT '',
    website      TEXT DEFAULT '',
    score        REAL DEFAULT 0.0,
    status       TEXT DEFAULT 'pending',
    looked_up_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS beamline_scientists (
    badge       TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    institution TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_esafs_year       ON esafs(year);
CREATE INDEX IF NOT EXISTS idx_esafs_beamline   ON esafs(beamline);
CREATE INDEX IF NOT EXISTS idx_esafs_status     ON esafs(status);
CREATE INDEX IF NOT EXISTS idx_esaf_users_badge ON esaf_users(badge);
CREATE INDEX IF NOT EXISTS idx_gups_run_cycle   ON gups(run_cycle);
CREATE INDEX IF NOT EXISTS idx_gup_fs_gup_id    ON gup_funding_sources(gup_id);
CREATE INDEX IF NOT EXISTS idx_ror_status        ON institution_ror(status);
"""


class SQLiteESAFRepository(ESAFRepository):

    def __init__(self, db_path: str):
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _db(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for field in ("raw_json", "custom_fields", "options"):
            if field in d and d[field]:
                try:
                    d[field] = json.loads(d[field])
                except (ValueError, TypeError):
                    pass
        return d

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        with self._db() as conn:
            conn.executescript(_SCHEMA)
            for col, defn in [
                ("description",    "TEXT DEFAULT ''"),
                ("sector",         "TEXT DEFAULT ''"),
                ("doi",            "TEXT DEFAULT ''"),
                ("pi_institution", "TEXT DEFAULT ''"),
                ("pi_group",       "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE esafs ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
            for col, defn in [
                ("country",  "TEXT DEFAULT ''"),
                ("state",    "TEXT DEFAULT ''"),
                ("orcid_id", "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
            # Ensure pi_groups table exists with full schema on existing DBs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pi_groups (
                    name        TEXT PRIMARY KEY,
                    pi_name     TEXT NOT NULL DEFAULT '',
                    pi_email    TEXT NOT NULL DEFAULT '',
                    institution TEXT NOT NULL DEFAULT '',
                    country     TEXT NOT NULL DEFAULT '',
                    state       TEXT NOT NULL DEFAULT '',
                    orcid_id    TEXT NOT NULL DEFAULT '',
                    created_at  TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
            for col, defn in [
                ("pi_name",     "TEXT NOT NULL DEFAULT ''"),
                ("pi_email",    "TEXT NOT NULL DEFAULT ''"),
                ("institution", "TEXT NOT NULL DEFAULT ''"),
                ("country",     "TEXT NOT NULL DEFAULT ''"),
                ("state",       "TEXT NOT NULL DEFAULT ''"),
                ("orcid_id",    "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE pi_groups ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
            # technique column (user-assigned classification)
            for tbl in ("esafs", "gups", "pi_groups"):
                try:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN technique TEXT DEFAULT ''")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
            # GUP-related migrations for esafs table
            for col, defn in [
                ("gup_id",   "TEXT DEFAULT ''"),
                ("pdf_path", "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE esafs ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
            # Index on gup_id — must come after the column exists
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_esafs_gup_id ON esafs(gup_id)"
                )
                conn.commit()
            except sqlite3.OperationalError:
                pass
            # New parsed GUP fields (migration-safe)
            for col, defn in [
                ("proposal_call",  "TEXT DEFAULT ''"),
                ("review_panel",   "TEXT DEFAULT ''"),
                ("co_pi",          "TEXT DEFAULT ''"),
                ("co_proposers",   "TEXT DEFAULT ''"),
                ("additional_areas", "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE gups ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
            # GUP tables (already in _SCHEMA but ensure on old DBs)
            # institution_ror table (migration-safe)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS institution_ror (
                    name         TEXT PRIMARY KEY,
                    ror_id       TEXT DEFAULT '',
                    ror_name     TEXT DEFAULT '',
                    org_types    TEXT DEFAULT '[]',
                    manual_types TEXT DEFAULT '[]',
                    country      TEXT DEFAULT '',
                    website      TEXT DEFAULT '',
                    score        REAL DEFAULT 0.0,
                    status       TEXT DEFAULT 'pending',
                    looked_up_at TEXT DEFAULT ''
                )
            """)
            try:
                conn.execute(
                    "ALTER TABLE institution_ror ADD COLUMN manual_types TEXT DEFAULT '[]'"
                )
                conn.commit()
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ror_status ON institution_ror(status)"
                )
            except sqlite3.OperationalError:
                pass
            conn.commit()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS beamline_scientists (
                    badge       TEXT PRIMARY KEY,
                    name        TEXT NOT NULL DEFAULT '',
                    institution TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.commit()

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS gups (
                    gup_id         TEXT PRIMARY KEY,
                    title          TEXT DEFAULT '',
                    pi_name        TEXT DEFAULT '',
                    pi_institution TEXT DEFAULT '',
                    run_cycle      TEXT DEFAULT '',
                    proposal_type  TEXT DEFAULT '',
                    primary_area   TEXT DEFAULT '',
                    keywords       TEXT DEFAULT '',
                    abstract       TEXT DEFAULT '',
                    beamlines      TEXT DEFAULT '',
                    status         TEXT DEFAULT '',
                    submitted_at   TEXT DEFAULT '',
                    notes          TEXT DEFAULT '',
                    pdf_path       TEXT DEFAULT '',
                    raw_fields     TEXT DEFAULT '{}',
                    created_at     TEXT DEFAULT (datetime('now')),
                    updated_at     TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS gup_funding_sources (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    gup_id       TEXT NOT NULL REFERENCES gups(gup_id) ON DELETE CASCADE,
                    agency       TEXT DEFAULT '',
                    details      TEXT DEFAULT '',
                    grant_number TEXT DEFAULT '',
                    percentage   INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_esafs_gup_id   ON esafs(gup_id);
                CREATE INDEX IF NOT EXISTS idx_gups_run_cycle ON gups(run_cycle);
                CREATE INDEX IF NOT EXISTS idx_gup_fs_gup_id ON gup_funding_sources(gup_id);
            """)

    # ------------------------------------------------------------------
    # ESAFs
    # ------------------------------------------------------------------

    def list_esafs(
        self,
        year: Optional[int] = None,
        beamline: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        clauses, params = [], []
        if year:
            clauses.append("year = ?"); params.append(year)
        if beamline:
            clauses.append("beamline LIKE ?"); params.append(f"%{beamline}%")
        if status:
            clauses.append("status = ?"); params.append(status)
        if search:
            clauses.append(
                "(e.title LIKE ? OR e.pi_name LIKE ? OR e.description LIKE ? OR e.esaf_id LIKE ?)"
            )
            params.extend([f"%{search}%"] * 4)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT e.*, COUNT(eu.badge) AS user_count
            FROM esafs e
            LEFT JOIN esaf_users eu ON e.esaf_id = eu.esaf_id
            {where}
            GROUP BY e.esaf_id
            ORDER BY e.year DESC, e.esaf_id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_esaf(self, esaf_id: str) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM esafs WHERE esaf_id = ?", (esaf_id,)
            ).fetchone()
            if row is None:
                return None
            esaf = self._row_to_dict(row)
            esaf["users"] = [
                self._row_to_dict(r)
                for r in conn.execute(
                    """SELECT u.*, eu.role
                       FROM users u JOIN esaf_users eu ON u.badge = eu.badge
                       WHERE eu.esaf_id = ?
                       ORDER BY eu.role, u.last_name""",
                    (esaf_id,),
                ).fetchall()
            ]
            esaf["funding_sources"] = [
                r["source"]
                for r in conn.execute(
                    "SELECT source FROM funding_sources WHERE esaf_id = ? ORDER BY source",
                    (esaf_id,),
                ).fetchall()
            ]
        return esaf

    def count_esafs(
        self,
        year: Optional[int] = None,
        beamline: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        clauses, params = [], []
        if year:
            clauses.append("year = ?"); params.append(year)
        if beamline:
            clauses.append("beamline LIKE ?"); params.append(f"%{beamline}%")
        if status:
            clauses.append("status = ?"); params.append(status)
        if search:
            clauses.append(
                "(title LIKE ? OR pi_name LIKE ? OR description LIKE ? OR esaf_id LIKE ?)"
            )
            params.extend([f"%{search}%"] * 4)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM esafs {where}", params).fetchone()[0]

    def get_filter_options(self) -> dict:
        with self._db() as conn:
            years = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT year FROM esafs ORDER BY year DESC"
                ).fetchall()
            ]
            beamlines = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT beamline FROM esafs WHERE beamline != '' ORDER BY beamline"
                ).fetchall()
            ]
            statuses = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT status FROM esafs WHERE status != '' ORDER BY status"
                ).fetchall()
            ]
        return {"years": years, "beamlines": beamlines, "statuses": statuses}

    def update_esaf_fields(
        self, esaf_id: str, notes: str, custom_fields: dict, pi_group: str = ""
    ) -> bool:
        with self._db() as conn:
            cur = conn.execute(
                """UPDATE esafs SET notes=?, custom_fields=?, pi_group=?,
                   updated_at=datetime('now') WHERE esaf_id=?""",
                (notes, json.dumps(custom_fields), pi_group, esaf_id),
            )
            if pi_group.strip():
                conn.execute(
                    "INSERT OR IGNORE INTO pi_groups (name) VALUES (?)",
                    (pi_group.strip(),),
                )
        return cur.rowcount > 0

    def list_pi_groups(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM pi_groups ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_pi_group(
        self, name: str, pi_name: str = "", pi_email: str = "",
        institution: str = "", country: str = "", state: str = "", orcid_id: str = ""
    ) -> None:
        with self._db() as conn:
            conn.execute(
                """INSERT INTO pi_groups (name, pi_name, pi_email, institution,
                       country, state, orcid_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       pi_name=excluded.pi_name, pi_email=excluded.pi_email,
                       institution=excluded.institution, country=excluded.country,
                       state=excluded.state, orcid_id=excluded.orcid_id""",
                (name, pi_name, pi_email, institution, country, state, orcid_id),
            )

    def delete_pi_group(self, name: str) -> bool:
        with self._db() as conn:
            cur = conn.execute("DELETE FROM pi_groups WHERE name = ?", (name,))
            return cur.rowcount > 0

    def propagate_pi_group_by_pi_name(
        self, group_name: str, pi_name: str, institution: str = ""
    ) -> int:
        import re as _re
        if not pi_name.strip():
            return 0
        # Require ALL name tokens (≥2 chars) to appear in pi_name
        tokens = [t for t in _re.split(r"[\s,\.]+", pi_name.strip()) if len(t) >= 2]
        if not tokens:
            return 0
        clauses = ["(pi_group = '' OR pi_group IS NULL)"]
        params: list = []
        for token in tokens:
            clauses.append("pi_name LIKE ? COLLATE NOCASE")
            params.append(f"%{token}%")
        # Institution: match on first significant word (≥4 chars)
        if institution.strip():
            inst_words = [w for w in institution.strip().split() if len(w) >= 4]
            if inst_words:
                clauses.append("pi_institution LIKE ? COLLATE NOCASE")
                params.append(f"%{inst_words[0]}%")
        where = " AND ".join(clauses)
        with self._db() as conn:
            cur = conn.execute(
                f"UPDATE esafs SET pi_group=?, updated_at=datetime('now') WHERE {where}",
                [group_name] + params,
            )
        return cur.rowcount

    def clear_pi_group_assignments(self, group_name: str) -> int:
        with self._db() as conn:
            cur = conn.execute(
                "UPDATE esafs SET pi_group='', updated_at=datetime('now') WHERE pi_group=?",
                (group_name,),
            )
        return cur.rowcount

    def list_users_for_lookup(self, q: str = "") -> list[dict]:
        fields = ("badge", "first_name", "last_name", "institution",
                  "country", "state", "email", "orcid_id")
        with self._db() as conn:
            if q:
                pat = f"%{q}%"
                rows = conn.execute(
                    """SELECT * FROM users
                       WHERE (first_name || ' ' || last_name) LIKE ?
                          OR last_name LIKE ? OR email LIKE ?
                       ORDER BY last_name, first_name LIMIT 50""",
                    (pat, pat, pat),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM users ORDER BY last_name, first_name LIMIT 500",
                ).fetchall()
            return [{f: dict(r).get(f, "") for f in fields} for r in rows]

    def upsert_esaf(self, data: dict, now: str) -> str:
        with self._db() as conn:
            existing = conn.execute(
                "SELECT esaf_id, notes, custom_fields FROM esafs WHERE esaf_id=?",
                (data["esaf_id"],),
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE esafs SET title=?, description=?, sector=?, beamline=?,
                       year=?, status=?, start_date=?, end_date=?, doi=?,
                       pi_badge=?, pi_name=?, pi_institution=?, raw_json=?, last_synced=?,
                       updated_at=datetime('now')
                       WHERE esaf_id=?""",
                    (
                        data["title"], data["description"], data["sector"],
                        data["beamline"], data["year"], data["status"],
                        data["start_date"], data["end_date"], data.get("doi", ""),
                        data["pi_badge"], data["pi_name"], data.get("pi_institution", ""),
                        json.dumps(data["raw_json"]), now, data["esaf_id"],
                    ),
                )
                action = "updated"
            else:
                conn.execute(
                    """INSERT INTO esafs
                       (esaf_id, title, description, sector, beamline, year, status,
                        start_date, end_date, doi, pi_badge, pi_name, pi_institution,
                        raw_json, last_synced)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        data["esaf_id"], data["title"], data["description"], data["sector"],
                        data["beamline"], data["year"], data["status"],
                        data["start_date"], data["end_date"], data.get("doi", ""),
                        data["pi_badge"], data["pi_name"], data.get("pi_institution", ""),
                        json.dumps(data["raw_json"]), now,
                    ),
                )
                action = "added"

            conn.execute("DELETE FROM esaf_users WHERE esaf_id=?", (data["esaf_id"],))
            conn.execute("DELETE FROM funding_sources WHERE esaf_id=?", (data["esaf_id"],))

            for u in data.get("users", []):
                conn.execute(
                    """INSERT INTO users
                       (badge, first_name, last_name, institution, country,
                        state, email, orcid_id, raw_json)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(badge) DO UPDATE SET
                           first_name  = excluded.first_name,
                           last_name   = excluded.last_name,
                           institution = CASE WHEN excluded.institution != ''
                                              THEN excluded.institution
                                              ELSE institution END,
                           country     = CASE WHEN excluded.country != ''
                                              THEN excluded.country ELSE country END,
                           state       = CASE WHEN excluded.state != ''
                                              THEN excluded.state ELSE state END,
                           email       = excluded.email,
                           orcid_id    = CASE WHEN excluded.orcid_id != ''
                                              THEN excluded.orcid_id ELSE orcid_id END,
                           raw_json    = excluded.raw_json""",
                    (u["badge"], u["first_name"], u["last_name"],
                     u["institution"], u.get("country", ""), u.get("state", ""),
                     u["email"], u.get("orcid_id", ""), json.dumps(u["raw_json"])),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO esaf_users (esaf_id, badge, role) VALUES (?,?,?)",
                    (data["esaf_id"], u["badge"], u["role"]),
                )

            for src in data.get("funding_sources", []):
                conn.execute(
                    "INSERT OR IGNORE INTO funding_sources (esaf_id, source) VALUES (?,?)",
                    (data["esaf_id"], src),
                )

        return action

    # ------------------------------------------------------------------
    # Sync log
    # ------------------------------------------------------------------

    def log_sync(
        self,
        beamlines: str,
        years: str,
        added: int,
        updated: int,
        error: Optional[str] = None,
    ) -> None:
        with self._db() as conn:
            conn.execute(
                """INSERT INTO sync_log (beamlines, years, records_added, records_updated, error)
                   VALUES (?,?,?,?,?)""",
                (beamlines, years, added, updated, error),
            )

    def get_last_sync(self) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(
        self,
        year_from: Optional[int] = None,
        year_to:   Optional[int] = None,
        technique: Optional[str] = None,
        exclude_scientists: bool = False,
    ) -> dict:
        # Build shared WHERE clause fragments
        direct_clause = ""   # for direct esafs table (no alias)
        direct_params: list = []
        join_clause   = ""   # for queries with JOIN esafs e
        join_params: list   = []

        if year_from is not None:
            direct_clause += " AND year >= ?";   direct_params.append(year_from)
            join_clause   += " AND e.year >= ?";  join_params.append(year_from)
        if year_to is not None:
            direct_clause += " AND year <= ?";   direct_params.append(year_to)
            join_clause   += " AND e.year <= ?";  join_params.append(year_to)
        if technique:
            direct_clause += " AND technique = ?";   direct_params.append(technique)
            join_clause   += " AND e.technique = ?"; join_params.append(technique)

        sci_eu = (
            " AND eu.badge NOT IN (SELECT badge FROM beamline_scientists)"
            if exclude_scientists else ""
        )
        sci_u = (
            " AND u.badge NOT IN (SELECT badge FROM beamline_scientists)"
            if exclude_scientists else ""
        )

        with self._db() as conn:
            def scalar(sql, params=()):
                return conn.execute(sql, params).fetchone()[0]

            total_esafs = scalar(
                f"SELECT COUNT(*) FROM esafs WHERE status = 'Approved'{direct_clause}",
                direct_params,
            )
            total_all_esafs = scalar(
                f"SELECT COUNT(*) FROM esafs WHERE 1=1{direct_clause}",
                direct_params,
            )
            participation_slots = scalar(
                f"""SELECT COUNT(*) FROM esaf_users eu
                    JOIN esafs e ON eu.esaf_id = e.esaf_id
                    WHERE e.status = 'Approved'{join_clause}{sci_eu}""",
                join_params,
            )
            unique_users = scalar(
                f"""SELECT COUNT(DISTINCT eu.badge) FROM esaf_users eu
                    JOIN esafs e ON eu.esaf_id = e.esaf_id
                    WHERE e.status = 'Approved'{join_clause}{sci_eu}""",
                join_params,
            )

            by_year = [
                dict(r) for r in conn.execute(
                    f"""SELECT year, COUNT(*) AS count FROM esafs
                        WHERE status = 'Approved'{direct_clause}
                        GROUP BY year ORDER BY year DESC""",
                    direct_params,
                ).fetchall()
            ]
            by_beamline = [
                dict(r) for r in conn.execute(
                    f"""SELECT beamline, COUNT(*) AS count FROM esafs
                        WHERE status = 'Approved'{direct_clause}
                        GROUP BY beamline ORDER BY count DESC""",
                    direct_params,
                ).fetchall()
            ]
            # Status breakdown uses same filters but shows all statuses
            by_status = [
                dict(r) for r in conn.execute(
                    f"""SELECT status, COUNT(*) AS count FROM esafs
                        WHERE 1=1{direct_clause}
                        GROUP BY status ORDER BY count DESC""",
                    direct_params,
                ).fetchall()
            ]
            by_institution = [
                dict(r) for r in conn.execute(
                    f"""SELECT u.institution,
                               COUNT(DISTINCT u.badge) AS unique_users,
                               COUNT(eu.esaf_id)       AS esaf_slots
                        FROM users u
                        JOIN esaf_users eu ON u.badge    = eu.badge
                        JOIN esafs e       ON eu.esaf_id = e.esaf_id
                        WHERE u.institution IS NOT NULL AND u.institution != ''
                          AND e.status = 'Approved'{join_clause}{sci_u}
                        GROUP BY u.institution
                        ORDER BY unique_users DESC LIMIT 30""",
                    join_params,
                ).fetchall()
            ]
            by_funding = [
                dict(r) for r in conn.execute(
                    f"""SELECT fs.source, COUNT(*) AS count
                        FROM funding_sources fs
                        JOIN esafs e ON fs.esaf_id = e.esaf_id
                        WHERE e.status = 'Approved'{join_clause}
                        GROUP BY fs.source ORDER BY count DESC""",
                    join_params,
                ).fetchall()
            ]
            top_users = [
                dict(r) for r in conn.execute(
                    f"""SELECT u.first_name || ' ' || u.last_name AS name,
                               u.institution, COUNT(eu.esaf_id) AS experiments
                        FROM users u
                        JOIN esaf_users eu ON u.badge    = eu.badge
                        JOIN esafs e       ON eu.esaf_id = e.esaf_id
                        WHERE e.status = 'Approved'{join_clause}{sci_u}
                        GROUP BY u.badge ORDER BY experiments DESC LIMIT 20""",
                    join_params,
                ).fetchall()
            ]
            all_years = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT year FROM esafs WHERE year IS NOT NULL ORDER BY year"
                ).fetchall()
            ]
            all_techniques = [
                r[0] for r in conn.execute(
                    """SELECT DISTINCT technique FROM esafs
                       WHERE technique != '' AND technique IS NOT NULL ORDER BY technique"""
                ).fetchall()
            ]

        return {
            "total_esafs":         total_esafs,
            "total_all_esafs":     total_all_esafs,
            "participation_slots": participation_slots,
            "unique_users":        unique_users,
            "by_year":             by_year,
            "by_beamline":         by_beamline,
            "by_status":           by_status,
            "by_institution":      by_institution,
            "by_funding":          by_funding,
            "top_users":           top_users,
            "all_years":           all_years,
            "all_techniques":      all_techniques,
            "year_from":           year_from,
            "year_to":             year_to,
            "technique":           technique,
            "exclude_scientists":  exclude_scientists,
        }

    # ------------------------------------------------------------------
    # Unique users list
    # ------------------------------------------------------------------

    def list_unique_users(
        self,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        technique: Optional[str] = None,
        exclude_scientists: bool = False,
    ) -> list[dict]:
        clauses = ["e.status = 'Approved'"]
        params: list = []
        if year_from is not None:
            clauses.append("e.year >= ?"); params.append(year_from)
        if year_to is not None:
            clauses.append("e.year <= ?"); params.append(year_to)
        if technique:
            clauses.append("e.technique = ?"); params.append(technique)
        if exclude_scientists:
            clauses.append("u.badge NOT IN (SELECT badge FROM beamline_scientists)")
        where = " AND ".join(clauses)
        sql = f"""
            SELECT u.badge,
                   u.first_name || ' ' || u.last_name AS name,
                   u.institution, u.country, u.state, u.email,
                   GROUP_CONCAT(DISTINCT e.technique) AS techniques,
                   COUNT(DISTINCT e.esaf_id) AS esaf_count,
                   MIN(e.start_date) AS first_experiment,
                   MAX(e.end_date)   AS last_experiment
            FROM users u
            JOIN esaf_users eu ON u.badge    = eu.badge
            JOIN esafs e       ON eu.esaf_id = e.esaf_id
            WHERE {where}
            GROUP BY u.badge
            ORDER BY name
        """
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            raw = d.get("techniques") or ""
            d["techniques"] = sorted({t for t in raw.split(",") if t})
            result.append(d)
        return result

    def get_user_detail(self, badge: str) -> Optional[dict]:
        with self._db() as conn:
            user_row = conn.execute(
                "SELECT * FROM users WHERE badge = ?", (badge,)
            ).fetchone()
            if user_row is None:
                return None
            d = self._row_to_dict(user_row)
            esaf_rows = conn.execute(
                """SELECT e.esaf_id, e.title, e.year, e.start_date, e.end_date,
                          e.beamline, e.status, e.technique, e.pi_name, eu.role
                   FROM esafs e
                   JOIN esaf_users eu ON eu.esaf_id = e.esaf_id
                   WHERE eu.badge = ?
                   ORDER BY e.start_date DESC""",
                (badge,),
            ).fetchall()
            d["esafs"] = [dict(r) for r in esaf_rows]
            is_scientist = conn.execute(
                "SELECT 1 FROM beamline_scientists WHERE badge = ?", (badge,)
            ).fetchone()
            d["is_beamline_scientist"] = is_scientist is not None
        return d

    # ------------------------------------------------------------------
    # Beamline scientists
    # ------------------------------------------------------------------

    def list_beamline_scientists(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT badge, name, institution FROM beamline_scientists ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def add_beamline_scientist(self, badge: str) -> bool:
        with self._db() as conn:
            user = conn.execute(
                "SELECT badge, first_name || ' ' || last_name AS name, institution "
                "FROM users WHERE badge = ?",
                (badge,),
            ).fetchone()
            if user is None:
                return False
            conn.execute(
                """INSERT INTO beamline_scientists (badge, name, institution)
                   VALUES (?,?,?)
                   ON CONFLICT(badge) DO NOTHING""",
                (user["badge"], user["name"], user["institution"] or ""),
            )
        return True

    def remove_beamline_scientist(self, badge: str) -> bool:
        with self._db() as conn:
            cur = conn.execute(
                "DELETE FROM beamline_scientists WHERE badge = ?", (badge,)
            )
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Custom field definitions
    # ------------------------------------------------------------------

    def list_field_definitions(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_field_definitions ORDER BY name"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def upsert_field_definition(
        self, name: str, label: str, field_type: str, options: list[str]
    ) -> None:
        with self._db() as conn:
            conn.execute(
                """INSERT INTO custom_field_definitions (name, label, field_type, options)
                   VALUES (?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET label=excluded.label,
                   field_type=excluded.field_type, options=excluded.options""",
                (name, label, field_type, json.dumps(options)),
            )

    def delete_field_definition(self, name: str) -> bool:
        with self._db() as conn:
            cur = conn.execute(
                "DELETE FROM custom_field_definitions WHERE name=?", (name,)
            )
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Domain affiliation overrides
    # ------------------------------------------------------------------

    def list_domain_overrides(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT domain, institution, country, state, created_at "
                "FROM domain_overrides ORDER BY domain"
            ).fetchall()
        return [dict(r) for r in rows]

    def set_domain_override(
        self, domain: str, institution: str, country: str, state: str
    ) -> None:
        with self._db() as conn:
            conn.execute(
                """INSERT INTO domain_overrides (domain, institution, country, state)
                   VALUES (?,?,?,?)
                   ON CONFLICT(domain) DO UPDATE SET
                       institution=excluded.institution,
                       country=excluded.country,
                       state=excluded.state""",
                (domain, institution, country, state),
            )

    def delete_domain_override(self, domain: str) -> bool:
        with self._db() as conn:
            cur = conn.execute(
                "DELETE FROM domain_overrides WHERE domain=?", (domain,)
            )
        return cur.rowcount > 0

    def apply_domain_override(
        self, domain: str, institution: str, country: str, state: str
    ) -> int:
        with self._db() as conn:
            cur = conn.execute(
                "UPDATE users SET institution=?, country=?, state=? WHERE email LIKE ?",
                (institution, country, state, f"%@{domain}"),
            )
        return cur.rowcount

    # ------------------------------------------------------------------
    # GUPs
    # ------------------------------------------------------------------

    def list_gups(
        self,
        search: Optional[str] = None,
        run_cycle: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        clauses, params = [], []
        if run_cycle:
            clauses.append("g.run_cycle = ?"); params.append(run_cycle)
        if search:
            clauses.append(
                "(g.title LIKE ? OR g.pi_name LIKE ? OR g.gup_id LIKE ?)"
            )
            params.extend([f"%{search}%"] * 3)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT g.*,
                   COUNT(DISTINCT gf.id) AS funding_count,
                   COUNT(DISTINCT e.esaf_id) AS linked_esaf_count
            FROM gups g
            LEFT JOIN gup_funding_sources gf ON g.gup_id = gf.gup_id
            LEFT JOIN esafs e ON e.gup_id = g.gup_id
            {where}
            GROUP BY g.gup_id
            ORDER BY g.run_cycle DESC, g.gup_id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        with self._db() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = self._row_to_dict(r)
            d["funding_sources"] = self._load_gup_funding(d["gup_id"])
            result.append(d)
        return result

    def get_gup(self, gup_id: str) -> Optional[dict]:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM gups WHERE gup_id = ?", (gup_id,)).fetchone()
            if row is None:
                return None
            d = self._row_to_dict(row)
            d["linked_esaf_count"] = conn.execute(
                "SELECT COUNT(*) FROM esafs WHERE gup_id = ?", (gup_id,)
            ).fetchone()[0]
        d["funding_sources"] = self._load_gup_funding(gup_id)
        return d

    def _load_gup_funding(self, gup_id: str) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT agency, details, grant_number, percentage "
                "FROM gup_funding_sources WHERE gup_id = ? ORDER BY id",
                (gup_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_gups(
        self,
        search: Optional[str] = None,
        run_cycle: Optional[str] = None,
    ) -> int:
        clauses, params = [], []
        if run_cycle:
            clauses.append("run_cycle = ?"); params.append(run_cycle)
        if search:
            clauses.append("(title LIKE ? OR pi_name LIKE ? OR gup_id LIKE ?)")
            params.extend([f"%{search}%"] * 3)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM gups {where}", params).fetchone()[0]

    def upsert_gup(self, data: dict, now: str) -> str:
        gup_id = data["gup_id"]
        with self._db() as conn:
            existing = conn.execute(
                "SELECT gup_id FROM gups WHERE gup_id = ?", (gup_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE gups SET title=?, pi_name=?, pi_institution=?, run_cycle=?,
                       proposal_call=?, proposal_type=?, primary_area=?, additional_areas=?,
                       review_panel=?, co_pi=?, co_proposers=?,
                       keywords=?, abstract=?, beamlines=?,
                       status=?, submitted_at=?, pdf_path=?, raw_fields=?,
                       updated_at=datetime('now') WHERE gup_id=?""",
                    (
                        data.get("title", ""), data.get("pi_name", ""),
                        data.get("pi_institution", ""), data.get("run_cycle", ""),
                        data.get("proposal_call", ""), data.get("proposal_type", ""),
                        data.get("primary_area", ""), data.get("additional_areas", ""),
                        data.get("review_panel", ""), data.get("co_pi", ""),
                        data.get("co_proposers", ""),
                        data.get("keywords", ""), data.get("abstract", ""),
                        data.get("beamlines", ""), data.get("status", ""),
                        data.get("submitted_at", ""), data.get("pdf_path", ""),
                        json.dumps(data.get("raw_fields", {})), gup_id,
                    ),
                )
                action = "updated"
            else:
                conn.execute(
                    """INSERT INTO gups
                       (gup_id, title, pi_name, pi_institution, run_cycle,
                        proposal_call, proposal_type, primary_area, additional_areas,
                        review_panel, co_pi, co_proposers,
                        keywords, abstract, beamlines, status, submitted_at,
                        pdf_path, raw_fields)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        gup_id, data.get("title", ""), data.get("pi_name", ""),
                        data.get("pi_institution", ""), data.get("run_cycle", ""),
                        data.get("proposal_call", ""), data.get("proposal_type", ""),
                        data.get("primary_area", ""), data.get("additional_areas", ""),
                        data.get("review_panel", ""), data.get("co_pi", ""),
                        data.get("co_proposers", ""),
                        data.get("keywords", ""), data.get("abstract", ""),
                        data.get("beamlines", ""), data.get("status", ""),
                        data.get("submitted_at", ""), data.get("pdf_path", ""),
                        json.dumps(data.get("raw_fields", {})),
                    ),
                )
                action = "added"

            # Replace funding sources
            conn.execute("DELETE FROM gup_funding_sources WHERE gup_id = ?", (gup_id,))
            for fs in data.get("funding_sources", []):
                conn.execute(
                    "INSERT INTO gup_funding_sources (gup_id, agency, details, grant_number, percentage) "
                    "VALUES (?,?,?,?,?)",
                    (gup_id, fs.get("agency", ""), fs.get("details", ""),
                     fs.get("grant_number", ""), fs.get("percentage", 0)),
                )
        return action

    def delete_gup(self, gup_id: str) -> bool:
        with self._db() as conn:
            cur = conn.execute("DELETE FROM gups WHERE gup_id = ?", (gup_id,))
        return cur.rowcount > 0

    def get_esafs_for_gup(self, gup_id: str) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                """SELECT esaf_id, title, beamline, year, status, start_date, end_date, pi_name
                   FROM esafs WHERE gup_id = ? ORDER BY start_date""",
                (gup_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_esaf_pdf(self, esaf_id: str, gup_id: str, pdf_path: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE esafs SET gup_id=?, pdf_path=?, updated_at=datetime('now') WHERE esaf_id=?",
                (gup_id, pdf_path, esaf_id),
            )

    def propagate_gup_funding(self, gup_id: str, funding_strings: list[str]) -> int:
        with self._db() as conn:
            esaf_ids = [
                r[0] for r in conn.execute(
                    "SELECT esaf_id FROM esafs WHERE gup_id = ?", (gup_id,)
                ).fetchall()
            ]
            count = 0
            for esaf_id in esaf_ids:
                conn.execute(
                    "DELETE FROM funding_sources WHERE esaf_id = ?", (esaf_id,)
                )
                for src in funding_strings:
                    conn.execute(
                        "INSERT OR IGNORE INTO funding_sources (esaf_id, source) VALUES (?,?)",
                        (esaf_id, src),
                    )
                count += 1
        return count

    def get_gup_run_cycles(self) -> list[str]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_cycle FROM gups WHERE run_cycle != '' ORDER BY run_cycle DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def set_gup_technique(self, gup_id: str, technique: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE gups SET technique=?, updated_at=datetime('now') WHERE gup_id=?",
                (technique, gup_id),
            )

    def set_pi_group_technique(self, name: str, technique: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE pi_groups SET technique=? WHERE name=?",
                (technique, name),
            )

    def add_pi_group_technique(self, name: str, technique: str) -> None:
        _ORDER = ["Surf", "Xtal", "ASWAXS", "Beamline"]
        with self._db() as conn:
            row = conn.execute(
                "SELECT technique FROM pi_groups WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                return
            current = {t for t in (row[0] or "").split(",") if t}
            current.add(technique)
            new_csv = ",".join(t for t in _ORDER if t in current)
            conn.execute("UPDATE pi_groups SET technique=? WHERE name=?", (new_csv, name))

    def set_esaf_technique(self, esaf_id: str, technique: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE esafs SET technique=?, updated_at=datetime('now') WHERE esaf_id=?",
                (technique, esaf_id),
            )

    def rename_pi_group(self, old_name: str, new_name: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE pi_groups SET name = ? WHERE name = ?", (new_name, old_name)
            )
            conn.execute(
                "UPDATE esafs SET pi_group = ? WHERE pi_group = ?", (new_name, old_name)
            )

    def list_distinct_institutions(self) -> list[str]:
        with self._db() as conn:
            rows = conn.execute("""
                SELECT institution FROM users WHERE institution != ''
                UNION
                SELECT pi_institution FROM esafs WHERE pi_institution != ''
                UNION
                SELECT institution FROM pi_groups WHERE institution != ''
                UNION
                SELECT pi_institution FROM gups WHERE pi_institution != ''
                ORDER BY institution
            """).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Institution ROR classification
    # ------------------------------------------------------------------

    def list_institution_ror(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM institution_ror ORDER BY name"
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for field in ("org_types", "manual_types"):
                try:
                    d[field] = json.loads(d.get(field) or "[]")
                except (ValueError, TypeError):
                    d[field] = []
            result.append(d)
        return result

    def upsert_institution_ror(self, name: str, data: dict) -> None:
        with self._db() as conn:
            conn.execute(
                """INSERT INTO institution_ror
                   (name, ror_id, ror_name, org_types, manual_types,
                    country, website, score, status, looked_up_at)
                   VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(name) DO UPDATE SET
                       ror_id=excluded.ror_id, ror_name=excluded.ror_name,
                       org_types=excluded.org_types, manual_types=excluded.manual_types,
                       country=excluded.country, website=excluded.website,
                       score=excluded.score, status=excluded.status,
                       looked_up_at=excluded.looked_up_at""",
                (
                    name, data.get("ror_id", ""), data.get("ror_name", ""),
                    json.dumps(data.get("org_types", [])),
                    json.dumps(data.get("manual_types", [])),
                    data.get("country", ""), data.get("website", ""),
                    data.get("score", 0.0), data.get("status", "pending"),
                ),
            )

    def rename_institution(self, old_name: str, new_name: str) -> dict:
        """Rename an institution across all tables. Returns per-table update counts."""
        with self._db() as conn:
            r_users = conn.execute(
                "UPDATE users SET institution=? WHERE institution=?", (new_name, old_name)
            ).rowcount
            r_esafs = conn.execute(
                "UPDATE esafs SET pi_institution=? WHERE pi_institution=?", (new_name, old_name)
            ).rowcount
            r_groups = conn.execute(
                "UPDATE pi_groups SET institution=? WHERE institution=?", (new_name, old_name)
            ).rowcount
            r_gups = conn.execute(
                "UPDATE gups SET pi_institution=? WHERE pi_institution=?", (new_name, old_name)
            ).rowcount
            conn.execute(
                "UPDATE institution_ror SET name=? WHERE name=?", (new_name, old_name)
            )
        return {"users": r_users, "esafs": r_esafs, "pi_groups": r_groups, "gups": r_gups}

    def set_institution_manual_types(self, name: str, types: list[str]) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE institution_ror SET manual_types=? WHERE name=?",
                (json.dumps(types), name),
            )

    def sync_institution_names(self) -> int:
        """Insert pending rows for any institution not yet in institution_ror."""
        names = self.list_distinct_institutions()
        count = 0
        with self._db() as conn:
            for name in names:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO institution_ror (name, status) VALUES (?, 'pending')",
                    (name,),
                )
                count += cur.rowcount
        return count
