#!/usr/bin/env python3
"""Refill funding sources that earlier syncs erased, from each ESAF's linked GUP.

The APS sync has no funding data, and before this fix every sync emptied the funding of the ESAFs
it touched (this year and last).  Funding is still stored on the GUPs (read from their PDFs), so an
ESAF that is linked to a GUP and has NO funding now gets the GUP's funding.  ESAFs that already have
funding are never changed.  Dry run by default; works with SQLite and MongoDB (same settings as the app).

    python restore_funding.py            # report only
    python restore_funding.py --apply    # write
"""
import argparse

from app import db
from app.gup_import import fill_funding_from_gups


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the changes (default: report only)")
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args()

    db.init_db()
    r = fill_funding_from_gups(apply=False)
    have, restore, no_gup_data, no_link, labels_by_gup = r["have"], r["restore"], r["no_gup_data"], r["no_link"], r["labels"]
    print(f"{have} ESAFs already have funding.")
    print(f"{len(restore)} ESAFs have none but are linked to a GUP with funding -> can be refilled "
          f"(from {len({g for _, g in restore})} GUPs).")
    for eid, gid in restore[:a.show]:
        print(f"    {eid} <- GUP {gid}: {'; '.join(labels_by_gup[gid])}")
    if len(restore) > a.show:
        print(f"    ... and {len(restore) - a.show} more")
    print(f"{sum(map(len, no_gup_data.values()))} ESAFs have none and their GUP ({len(no_gup_data)}) has no funding data "
          f"(upload that GUP's PDF).")
    print(f"{len(no_link)} ESAFs have none and no GUP link (upload the ESAF PDF, or link the GUP).")

    if a.apply:
        fill_funding_from_gups(apply=True)
        print(f"\nRefilled {len(restore)} ESAFs.")
    elif restore:
        print("\nNothing written. Run with --apply to refill these.")


if __name__ == "__main__":
    main()
