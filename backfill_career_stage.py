#!/usr/bin/env python3
"""Fill blank career stages that are safely implied (SQLite and MongoDB).

A blank stage on an ESAF is filled only when the SAME person's nearest known stage before it and
after it (across all their ESAFs and institutions) is identical, e.g. Post-doc ... [blank] ... Post-doc.
Blanks before the first or after the last known stage, and blanks between two different stages,
are left alone.  Dry run by default.

    python backfill_career_stage.py [--show 20] [--apply]
"""
import argparse
import collections

from app import db, unique_users as uu


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", type=int, default=20)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    db.init_db()
    slots = db.list_user_slots()
    blanks = sum(1 for s in slots if not (s.get("level") or "").strip())
    plan = uu.plan_backfill(slots)
    print(f"{len(slots)} user-on-ESAF entries, {blanks} with no career stage")
    print(f"{len(plan)} blanks can be filled (the person's stage just before and just after is the same); "
          f"{blanks - len(plan)} stay blank")
    for lv, n in collections.Counter(p["level"] for p in plan).most_common():
        print(f"    {n:5d} x {lv}")
    for p in plan[:a.show]:
        print(f"  ESAF {p['esaf_id']} ({p['start'][:10]}) badge {p['badge']} -> {p['level']}")
    if not a.apply:
        print("\nDry run - nothing changed. Back up first, then re-run with --apply.")
        return
    done = sum(1 for p in plan if db.set_user_career_stage(p["esaf_id"], p["badge"], p["level"]))
    print(f"\nFilled {done} career stages.")


if __name__ == "__main__":
    main()
