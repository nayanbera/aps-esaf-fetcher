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

CREATE INDEX IF NOT EXISTS idx_esafs_year     ON esafs(year);
CREATE INDEX IF NOT EXISTS idx_esafs_beamline ON esafs(beamline);
CREATE INDEX IF NOT EXISTS idx_esafs_status   ON esafs(status);
CREATE INDEX IF NOT EXISTS idx_esaf_users_badge ON esaf_users(badge);
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
            ]:
                try:
                    conn.execute(f"ALTER TABLE esafs ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass
            for col, defn in [
                ("country", "TEXT DEFAULT ''"),
                ("state",   "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass

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
                "(title LIKE ? OR pi_name LIKE ? OR description LIKE ? OR esaf_id LIKE ?)"
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

    def update_esaf_fields(self, esaf_id: str, notes: str, custom_fields: dict) -> bool:
        with self._db() as conn:
            cur = conn.execute(
                """UPDATE esafs SET notes=?, custom_fields=?, updated_at=datetime('now')
                   WHERE esaf_id=?""",
                (notes, json.dumps(custom_fields), esaf_id),
            )
        return cur.rowcount > 0

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
                    """INSERT OR REPLACE INTO users
                       (badge, first_name, last_name, institution, country, state, email, raw_json)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (u["badge"], u["first_name"], u["last_name"],
                     u["institution"], u.get("country", ""), u.get("state", ""),
                     u["email"], json.dumps(u["raw_json"])),
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

    def get_stats(self) -> dict:
        with self._db() as conn:
            def scalar(sql, params=()):
                return conn.execute(sql, params).fetchone()[0]

            total_esafs  = scalar("SELECT COUNT(*) FROM esafs")
            total_users  = scalar("SELECT COUNT(*) FROM esaf_users")
            unique_users = scalar("SELECT COUNT(DISTINCT badge) FROM esaf_users")

            by_year = [
                dict(r) for r in conn.execute(
                    "SELECT year, COUNT(*) AS count FROM esafs GROUP BY year ORDER BY year DESC"
                ).fetchall()
            ]
            by_beamline = [
                dict(r) for r in conn.execute(
                    "SELECT beamline, COUNT(*) AS count FROM esafs GROUP BY beamline ORDER BY count DESC"
                ).fetchall()
            ]
            by_status = [
                dict(r) for r in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM esafs GROUP BY status ORDER BY count DESC"
                ).fetchall()
            ]
            by_institution = [
                dict(r) for r in conn.execute(
                    """SELECT u.institution, COUNT(DISTINCT u.badge) AS unique_users,
                              COUNT(eu.esaf_id) AS esaf_slots
                       FROM users u JOIN esaf_users eu ON u.badge = eu.badge
                       WHERE u.institution IS NOT NULL AND u.institution != ''
                       GROUP BY u.institution ORDER BY unique_users DESC LIMIT 30"""
                ).fetchall()
            ]
            by_funding = [
                dict(r) for r in conn.execute(
                    "SELECT source, COUNT(*) AS count FROM funding_sources GROUP BY source ORDER BY count DESC"
                ).fetchall()
            ]
            top_users = [
                dict(r) for r in conn.execute(
                    """SELECT u.first_name || ' ' || u.last_name AS name,
                              u.institution, COUNT(eu.esaf_id) AS experiments
                       FROM users u JOIN esaf_users eu ON u.badge = eu.badge
                       GROUP BY u.badge ORDER BY experiments DESC LIMIT 20"""
                ).fetchall()
            ]

        return {
            "total_esafs": total_esafs,
            "total_users": total_users,
            "unique_users": unique_users,
            "by_year": by_year,
            "by_beamline": by_beamline,
            "by_status": by_status,
            "by_institution": by_institution,
            "by_funding": by_funding,
            "top_users": top_users,
        }

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
