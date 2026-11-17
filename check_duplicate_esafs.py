#!/usr/bin/env python3
"""Read-only: find "(imported)" ESAFs that look like duplicates of ESAFs synced from APS.

The master-file import creates a stub "ESAF <id> (imported)" for every Experiment Id it does not
find.  Its Experiment Ids are numbered differently from the APS ESAF numbers, so the same visit
can exist twice.  A stub is reported as a likely duplicate when a real ESAF shares at least one
badge with it and starts within --days days.  Works with SQLite and MongoDB (same settings as the app).

    python check_duplicate_esafs.py [--days 7] [--show 20]
"""
import argparse
import re
from datetime import date, datetime

from app import db


def parse(s: str):
    s = (s or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--show", type=int, default=20)
    a = ap.parse_args()

    db.init_db()          # same connection and (idempotent) schema setup as the app's startup
    rows = db.list_esafs(limit=1_000_000)
    stubs = [r for r in rows if (r.get("title") or "").endswith("(imported)")]
    real = [r for r in rows if r not in stubs]
    print(f"{len(rows)} ESAFs: {len(stubs)} imported stubs, {len(real)} others")

    # badge -> real ESAFs (id, start date)
    by_badge: dict[str, list] = {}
    for r in real:
        d = parse(r.get("start_date"))
        if d is None:
            continue
        for u in (db.get_esaf(r["esaf_id"]) or {}).get("users", []):
            by_badge.setdefault(u.get("badge", ""), []).append((r["esaf_id"], d))

    dup, shown = 0, 0
    for s in stubs:
        d = parse(s.get("start_date"))
        users = [u.get("badge", "") for u in (db.get_esaf(s["esaf_id"]) or {}).get("users", [])]
        hits = {}
        for b in users:
            for eid, rd in by_badge.get(b, []):
                if d and abs((rd - d).days) <= a.days:
                    hits.setdefault(eid, set()).add(b)
        if hits:
            dup += 1
            if shown < a.show:
                shown += 1
                best = max(hits, key=lambda e: len(hits[e]))
                print(f"  stub {s['esaf_id']} ({s.get('start_date')}) ~ real {best} "
                      f"({len(hits[best])} shared of {len(users)} users)")
    print(f"\n{dup} of {len(stubs)} imported stubs have a likely duplicate (shared badge, start within {a.days} days).")


if __name__ == "__main__":
    main()
