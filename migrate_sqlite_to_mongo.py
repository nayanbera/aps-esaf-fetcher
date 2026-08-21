"""Migrate all data from the SQLite database to MongoDB.

Usage:
    python migrate_sqlite_to_mongo.py [--db /path/to/esaf.db] [--dry-run]

Environment variables:
    MONGODB_URI   MongoDB connection URI (required)
    MONGODB_ESAF_DB   Database name (default: aps_esaf)
    DB_PATH       SQLite database path (default: ~/.aps-esaf-fetcher/esaf.db)

The script reads every table from SQLite via SQLiteESAFRepository and writes
to MongoDB via MongoESAFRepository using the same public API methods — so all
field mappings, JSON parsing, and index creation are handled by the backends.

Safe to re-run: MongoDB upserts are idempotent. Audit log entries are appended
(no dedup) so avoid running multiple times unless intentional.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_sqlite_rows(db_path: str, query: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def migrate(sqlite_path: str, mongo_uri: str, mongo_db: str, dry_run: bool = False):
    from app.backends.sqlite_backend import SQLiteESAFRepository
    from app.backends.mongo_backend  import MongoESAFRepository

    sq = SQLiteESAFRepository(db_path=sqlite_path)
    if not dry_run:
        mg = MongoESAFRepository(uri=mongo_uri, db_name=mongo_db)
        mg.init_db()

    now = _now()

    # ── 1. ESAFs (includes embedded users via get_esaf) ─────────────────────
    # list_esafs returns projected rows; we need full records with users.
    # Read raw from SQLite then reconstruct the data dict upsert_esaf expects.
    print("Migrating ESAFs …")
    esaf_rows = _get_sqlite_rows(sqlite_path, "SELECT * FROM esafs")
    user_rows  = _get_sqlite_rows(sqlite_path,
        "SELECT eu.*, u.first_name, u.last_name, u.email, u.institution, "
        "u.country, u.state, u.orcid_id, u.gender, u.employment_level "
        "FROM esaf_users eu LEFT JOIN users u ON u.badge = eu.badge")
    fund_rows  = _get_sqlite_rows(sqlite_path, "SELECT * FROM funding_sources")

    # Group users and funding by esaf_id
    users_by_esaf: dict[str, list] = {}
    for r in user_rows:
        users_by_esaf.setdefault(r["esaf_id"], []).append(r)
    fund_by_esaf: dict[str, list] = {}
    for r in fund_rows:
        fund_by_esaf.setdefault(r["esaf_id"], []).append(r["source"])

    added = updated = 0
    for row in esaf_rows:
        esaf_id = row["esaf_id"]
        raw_json = {}
        try:
            raw_json = json.loads(row.get("raw_json") or "{}")
        except (ValueError, TypeError):
            pass
        custom_fields = {}
        try:
            custom_fields = json.loads(row.get("custom_fields") or "{}")
        except (ValueError, TypeError):
            pass

        users = []
        for u in users_by_esaf.get(esaf_id, []):
            users.append({
                "badge":            u.get("badge", ""),
                "first_name":       u.get("first_name", ""),
                "last_name":        u.get("last_name", ""),
                "email":            u.get("email", ""),
                "institution":      u.get("institution", ""),
                "country":          u.get("country", ""),
                "state":            u.get("state", ""),
                "orcid_id":         u.get("orcid_id", ""),
                "gender":           u.get("gender", ""),
                "employment_level": u.get("employment_level", ""),
                "role":             u.get("role", ""),
                "user_type":        u.get("user_type", ""),
            })

        data = {
            "esaf_id":        esaf_id,
            "title":          row.get("title", ""),
            "description":    row.get("description", ""),
            "sector":         row.get("sector", ""),
            "beamline":       row.get("beamline", ""),
            "year":           row.get("year", 0),
            "status":         row.get("status", ""),
            "start_date":     row.get("start_date", ""),
            "end_date":       row.get("end_date", ""),
            "doi":            row.get("doi", ""),
            "pi_badge":       row.get("pi_badge", ""),
            "pi_name":        row.get("pi_name", ""),
            "pi_institution": row.get("pi_institution", ""),
            "pi_group":       row.get("pi_group", ""),
            "gup_id":         row.get("gup_id", ""),
            "local_id":       row.get("local_id", ""),
            "technique":      row.get("technique", ""),
            "notes":          row.get("notes", ""),
            "pdf_path":       row.get("pdf_path", ""),
            "custom_fields":  custom_fields,
            "users":          users,
            "funding_sources": fund_by_esaf.get(esaf_id, []),
            "raw_json":       raw_json,
        }
        if dry_run:
            added += 1
        else:
            action = mg.upsert_esaf(data, now)
            if action == "added":
                added += 1
            else:
                updated += 1
    print(f"  ESAFs: {added} added, {updated} updated")

    # ── 2. GUPs ──────────────────────────────────────────────────────────────
    print("Migrating GUPs …")
    gup_rows  = _get_sqlite_rows(sqlite_path, "SELECT * FROM gups")
    gfs_rows  = _get_sqlite_rows(sqlite_path, "SELECT * FROM gup_funding_sources")
    gfs_by_gup: dict[str, list] = {}
    for r in gfs_rows:
        gfs_by_gup.setdefault(r["gup_id"], []).append(r["source"])

    added = updated = 0
    for row in gup_rows:
        raw_json = {}
        try:
            raw_json = json.loads(row.get("raw_json") or "{}")
        except (ValueError, TypeError):
            pass
        data = {
            "gup_id":          row["gup_id"],
            "title":           row.get("title", ""),
            "pi_name":         row.get("pi_name", ""),
            "pi_badge":        row.get("pi_badge", ""),
            "pi_institution":  row.get("pi_institution", ""),
            "run_cycle":       row.get("run_cycle", ""),
            "beamlines":       row.get("beamlines", ""),
            "status":          row.get("status", ""),
            "start_date":      row.get("start_date", ""),
            "end_date":        row.get("end_date", ""),
            "technique":       row.get("technique", ""),
            "notes":           row.get("notes", ""),
            "pdf_path":        row.get("pdf_path", ""),
            "funding_sources": gfs_by_gup.get(row["gup_id"], []),
            "raw_json":        raw_json,
        }
        if dry_run:
            added += 1
        else:
            action = mg.upsert_gup(data, now)
            if action == "added":
                added += 1
            else:
                updated += 1
    print(f"  GUPs: {added} added, {updated} updated")

    # ── 3. PI Groups ─────────────────────────────────────────────────────────
    print("Migrating PI Groups …")
    pi_rows = sq.list_pi_groups()
    for row in pi_rows:
        if not dry_run:
            mg.upsert_pi_group(
                name=row["name"],
                pi_name=row.get("pi_name", ""),
                pi_email=row.get("pi_email", ""),
                institution=row.get("institution", ""),
                country=row.get("country", ""),
                state=row.get("state", ""),
                orcid_id=row.get("orcid_id", ""),
            )
            if row.get("technique"):
                mg.set_pi_group_technique(row["name"], row["technique"])
    print(f"  PI Groups: {len(pi_rows)}")

    # ── 4. Institution ROR ────────────────────────────────────────────────────
    print("Migrating Institution ROR …")
    ror_rows = sq.list_institution_ror()
    for row in ror_rows:
        if not dry_run:
            data = {k: v for k, v in row.items() if k != "name"}
            mg.upsert_institution_ror(row["name"], data)
            manual = data.get("manual_types")
            if manual:
                types = manual if isinstance(manual, list) else json.loads(manual or "[]")
                mg.set_institution_manual_types(row["name"], types)
    print(f"  Institutions: {len(ror_rows)}")

    # ── 5. Beamline Scientists ────────────────────────────────────────────────
    print("Migrating Beamline Scientists …")
    bs_rows = sq.list_beamline_scientists()
    for row in bs_rows:
        if not dry_run:
            mg.add_beamline_scientist(row["badge"], start_date=row.get("start_date", ""))
    print(f"  Beamline Scientists: {len(bs_rows)}")

    # ── 6. Custom Field Definitions ───────────────────────────────────────────
    print("Migrating Custom Field Definitions …")
    fd_rows = sq.list_field_definitions()
    for row in fd_rows:
        if not dry_run:
            opts = row.get("options", [])
            if isinstance(opts, str):
                try:
                    opts = json.loads(opts)
                except ValueError:
                    opts = []
            mg.upsert_field_definition(
                name=row["name"],
                label=row.get("label", row["name"]),
                field_type=row.get("field_type", "text"),
                options=opts,
            )
    print(f"  Field Definitions: {len(fd_rows)}")

    # ── 7. Domain Overrides ───────────────────────────────────────────────────
    print("Migrating Domain Overrides …")
    do_rows = sq.list_domain_overrides()
    for row in do_rows:
        if not dry_run:
            mg.set_domain_override(
                domain=row["domain"],
                institution=row.get("institution", ""),
                country=row.get("country", ""),
                state=row.get("state", ""),
            )
    print(f"  Domain Overrides: {len(do_rows)}")

    # ── 8. Admin Users ────────────────────────────────────────────────────────
    print("Migrating Admin Users …")
    admin_rows = sq.list_admin_users()
    for row in admin_rows:
        if not dry_run:
            mg.add_admin_user(
                email=row["email"],
                name=row.get("name", ""),
                password_hash=row.get("password_hash", ""),
            )
    print(f"  Admin Users: {len(admin_rows)}")

    # ── 9. Audit Log ──────────────────────────────────────────────────────────
    print("Migrating Audit Log …")
    # Fetch all audit log entries directly — list_audit_log is paginated
    audit_rows = _get_sqlite_rows(sqlite_path,
        "SELECT * FROM audit_log ORDER BY timestamp ASC")
    for row in audit_rows:
        changes = {}
        try:
            changes = json.loads(row.get("changes") or "{}")
        except (ValueError, TypeError):
            pass
        if not dry_run:
            mg.add_audit_log(
                user_email=row.get("user_email", ""),
                action=row.get("action", ""),
                table_name=row.get("table_name", ""),
                record_id=row.get("record_id", ""),
                description=row.get("description", ""),
                changes=changes,
            )
    print(f"  Audit Log: {len(audit_rows)} entries")

    # ── 10. Sync Log ──────────────────────────────────────────────────────────
    print("Migrating Sync Log …")
    sync_rows = _get_sqlite_rows(sqlite_path,
        "SELECT * FROM sync_log ORDER BY started_at ASC")
    for row in sync_rows:
        if not dry_run:
            mg.log_sync(
                beamlines=row.get("beamlines", ""),
                years=row.get("years", ""),
                added=row.get("added", 0),
                updated=row.get("updated", 0),
                error=row.get("error") or None,
            )
    print(f"  Sync Log: {len(sync_rows)} entries")

    print()
    if dry_run:
        print("DRY RUN complete — no data written to MongoDB.")
    else:
        print("Migration complete.")


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite → MongoDB")
    parser.add_argument("--db",      default="", help="SQLite DB path (overrides DB_PATH env)")
    parser.add_argument("--dry-run", action="store_true", help="Count rows, write nothing")
    args = parser.parse_args()

    sqlite_path = (args.db
                   or os.getenv("DB_PATH")
                   or str(Path.home() / ".aps-esaf-fetcher" / "esaf.db"))
    mongo_uri   = os.getenv("MONGODB_URI", "")
    mongo_db    = os.getenv("MONGODB_ESAF_DB", "aps_esaf")

    if not Path(sqlite_path).exists():
        print(f"ERROR: SQLite database not found: {sqlite_path}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and not mongo_uri:
        print("ERROR: MONGODB_URI environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Source : {sqlite_path}")
    print(f"Target : {mongo_uri or '(dry-run)'} / {mongo_db}")
    print()

    migrate(sqlite_path, mongo_uri, mongo_db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
