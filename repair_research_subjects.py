#!/usr/bin/env python3
"""Move Research Subjects out of the ESAF "technique" field (MongoDB).

An earlier master-file import wrote the Excel "Research Subject" column into
`technique`, which is reserved for Surf / Xtal / ASWAXS / Beamline.  This moves any
technique value that is not one of those four into `research_subject`.

Where the import REPLACED a technique that had been assigned by hand, the original
cannot be recovered from the live data.  Options for the techniques that were lost:
  --backup-db NAME   restore them from a restored mongodump (a database on the same
                     server holding the pre-import `esafs` collection)
  --sqlite-db PATH   restore them from the old SQLite database the data was migrated
                     from (esaf.db) - holds techniques as of the migration
  --guess-from-pi-group
                     fall back to the ESAF's PI Group technique when the group has
                     exactly one technique (a guess - review the report)
Without either option those ESAFs are left with an empty technique.

Dry run by default; pass --apply to write.  Uses the same MongoDB settings as the app (MONGODB_URI / MONGODB_ESAF_DB).
"""
import argparse
import sqlite3

from pymongo import MongoClient, UpdateOne

from app import config

VALID = {"Surf", "Xtal", "ASWAXS", "Beamline"}
ORDER = ["Surf", "Xtal", "ASWAXS", "Beamline"]


def split(v):
    return [t.strip() for t in (v or "").split(",") if t.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-db")
    ap.add_argument("--sqlite-db")
    ap.add_argument("--guess-from-pi-group", action="store_true")
    a = ap.parse_args()

    client = MongoClient(config.MONGODB_URI)
    db = client[config.MONGODB_ESAF_DB]
    backup = client[a.backup_db]["esafs"] if a.backup_db else None
    old_sqlite = {}
    if a.sqlite_db:
        with sqlite3.connect(f"file:{a.sqlite_db}?mode=ro", uri=True) as conn:
            old_sqlite = {r[0]: r[1] for r in conn.execute("SELECT esaf_id, technique FROM esafs")}
        print(f"Read {len(old_sqlite)} ESAFs from {a.sqlite_db}")
    if backup is not None:
        print(f"Backup database has {backup.count_documents({})} ESAFs")
    groups = {g["name"]: split(g.get("technique")) for g in db["pi_groups"].find({}, {"name": 1, "technique": 1})}

    ops, stats = [], dict(moved=0, kept=0, from_backup=0, from_group=0, empty=0)
    for d in db["esafs"].find({"technique": {"$nin": ["", None]}},
                              {"esaf_id": 1, "technique": 1, "research_subject": 1, "pi_group": 1}):
        toks = split(d["technique"])
        bad = [t for t in toks if t not in VALID]
        if not bad:
            stats["kept"] += 1
            continue
        good = [t for t in toks if t in VALID]
        subject = d.get("research_subject") or ", ".join(bad)
        if not good:                                   # the manual technique was overwritten
            if backup is not None:
                old = backup.find_one({"esaf_id": d["esaf_id"]}, {"technique": 1}) or {}
                good = [t for t in split(old.get("technique")) if t in VALID]
                stats["from_backup"] += bool(good)
            if not good and old_sqlite:
                good = [t for t in split(old_sqlite.get(d["esaf_id"])) if t in VALID]
                stats["from_backup"] += bool(good)
            if not good and a.guess_from_pi_group:
                g = groups.get(d.get("pi_group") or "", [])
                if len(g) == 1:
                    good = g
                    stats["from_group"] += 1
            if not good:
                stats["empty"] += 1
        new_tech = ",".join(t for t in ORDER if t in good)
        stats["moved"] += 1
        ops.append(UpdateOne({"_id": d["_id"]}, {"$set": {"technique": new_tech, "research_subject": subject}}))

    print(f"ESAFs with a valid technique left alone: {stats['kept']}")
    print(f"ESAFs fixed (subject moved to research_subject): {stats['moved']}")
    print(f"  technique restored from backup / SQLite: {stats['from_backup']}")
    print(f"  technique guessed from PI Group: {stats['from_group']}")
    print(f"  left with no technique (assign manually): {stats['empty']}")
    if a.apply and ops:
        db["esafs"].bulk_write(ops, ordered=False)
        print("Applied.")
    else:
        print("Dry run - nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
