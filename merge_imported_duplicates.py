#!/usr/bin/env python3
"""Merge "ESAF <id> (imported)" stubs into the real ESAF they duplicate (SQLite and MongoDB).

A stub is merged when ALL of its users are on a real (synced) ESAF whose start date is within
--days days of the stub's (nearest date wins; ties and partial matches are left alone).  What the
stub knows (career stage, institution, ON-SITE/OFF-SITE, research subject, local ID, funding,
notes, ...) is copied onto the real ESAF where that is blank, the stub's experiment id is
remembered on the real ESAF (so re-importing the master file does not recreate the stub), and the
stub is deleted.

Dry run by default - take a backup (mongodump / copy esaf.db) before --apply.

    python merge_imported_duplicates.py [--days 7] [--show 20] [--ties] [--apply]

--ties also handles stubs whose nearest real ESAFs are TIED (the 'twin' ESAFs of one visit, same start
time and users): the stub's data is copied onto every tied ESAF (blank fields only) and the stub removed.
"""
import argparse
import collections

from app import db, esaf_matching


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=esaf_matching.DAYS)
    ap.add_argument("--show", type=int, default=20)
    ap.add_argument("--ties", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    db.init_db()
    esafs = db.list_esaf_badges()
    stubs = [e for e in esafs if esaf_matching.is_stub(e)]
    idx = esaf_matching.Index(esafs)
    plan, why, tie_plan = [], collections.Counter(), []
    for s in stubs:
        real, reason = idx.match(set(s["badges"]), s["start_date"], a.days)
        if real:
            plan.append((s, real))
        elif reason == "ambiguous" and a.ties:
            tied = esaf_matching.tied_matches(idx, set(s["badges"]), s["start_date"], a.days)
            if tied:
                tie_plan.append((s, tied))
            else:
                why["ambiguous"] += 1       # tied on different days: not twins, left alone
        else:
            why[reason] += 1

    print(f"{len(esafs)} ESAFs: {len(stubs)} imported stubs, {len(esafs) - len(stubs)} others")
    print(f"{len(plan)} stubs can be merged into a real ESAF (all their users on it, start within {a.days} days)")
    names = {"none": "with no matching real ESAF", "ambiguous": "with several equally close real ESAFs",
             "no users/date": "without users or a start date"}
    print(f"{sum(why.values())} stubs stay as they are" + (": " if why else "") + ", ".join(f"{n} {names[r]}" for r, n in why.items()))
    if a.ties:
        print(f"{len(tie_plan)} stubs have tied real ESAFs: their data is copied onto each tied ESAF")
        for s, tied in tie_plan[:a.show]:
            print(f"  stub {s['esaf_id']} ({s['start_date']}) -> {', '.join(tied)}")
    for s, real in plan[:a.show]:
        print(f"  stub {s['esaf_id']} ({s['start_date']}) -> real {real}")
    if not a.apply:
        print("\nDry run - nothing changed. Back up first, then re-run with --apply.")
        return
    done = sum(1 for s, real in plan if db.merge_stub_into_esaf(s["esaf_id"], real))
    for s, tied in tie_plan:
        for t in tied[:-1]:
            db.merge_stub_into_esaf(s["esaf_id"], t, delete=False)
        done += db.merge_stub_into_esaf(s["esaf_id"], tied[-1])
    print(f"\nMerged and removed {done} stubs.")


if __name__ == "__main__":
    main()
