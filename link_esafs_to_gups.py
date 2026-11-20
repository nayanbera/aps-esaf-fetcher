#!/usr/bin/env python3
"""Link ESAFs that have no GUP to their GUP.  Dry run by default; works with SQLite and MongoDB.

  sure   = same PI and same title (the ESAF title equals, or starts the same as, the GUP title)
  likely = same PI, different title, and only one GUP of that PI asked for the ESAF's run cycle

Linking an ESAF also gives it the GUP's funding and (from its 15-ID instrument) its technique.

    python link_esafs_to_gups.py                  # report only
    python link_esafs_to_gups.py --apply          # link the 'sure' ones
    python link_esafs_to_gups.py --apply --likely # link the 'likely' ones too
"""
import argparse

from app import db, gup_linking


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--likely", action="store_true", help="with --apply, also link the 'likely' matches")
    a = ap.parse_args()
    db.init_db()
    esafs = {r["esaf_id"]: r for r in db.list_esafs(limit=1_000_000)}
    gups = {g["gup_id"]: g for g in db.list_gups(limit=1_000_000)}
    r = gup_linking.link_esafs_to_gups(apply=False)
    for kind in ("sure", "likely"):
        print(f"\n{kind.upper()} ({len(r[kind])}):")
        for eid, gid in r[kind]:
            print(f"  ESAF {eid} [{esafs[eid].get('pi_name')}] {esafs[eid].get('title', '')[:60]!r}\n"
                  f"    -> GUP {gid} [{gups[gid].get('pi_name')}] {gups[gid].get('title', '')[:60]!r}")
    print(f"\n{r['ambiguous']} ESAF(s) fit several GUPs and are left alone.")
    if a.apply:
        gup_linking.link_esafs_to_gups(apply=True, likely=a.likely)
        print(f"\nLinked {len(r['sure']) + (len(r['likely']) if a.likely else 0)} ESAF(s).")
    else:
        print("\nNothing written. Run with --apply (and --likely) to link.")


if __name__ == "__main__":
    main()
