"""Match master-file experiments to ESAFs synced from APS (SQLite and MongoDB share this).

The master file's "Experiment Id" is numbered differently from APS ESAF numbers, so the same
visit can exist twice: once as an "ESAF <id> (imported)" stub and once as the synced ESAF.
An experiment belongs to a real ESAF when ALL of its users are on that ESAF and the start dates
are within `DAYS` days; the nearest start date wins, and a tie is left unmatched.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

DAYS = 7
STUB_SUFFIX = "(imported)"


def parse_date(s) -> Optional[date]:
    s = str(s or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    return date(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None


def esaf_year(start, stored=None, basis: str = "calendar"):
    """Year an ESAF is counted in, from its start date: the calendar year, or the fiscal year (Oct-Sep, so
    Nov 2025 is FY2026).  Falls back to the stored year when there is no usable start date."""
    d = parse_date(start)
    if d is None:
        return stored
    return d.year + 1 if basis == "fiscal" and d.month >= 10 else d.year


def run_cycle(start) -> str:
    """APS run cycle of a start date: 1 = Jan-Apr, 2 = May-Aug, 3 = Sep-Dec ('2026-3'); '' without a date."""
    d = parse_date(start)
    return f"{d.year}-{(d.month - 1) // 4 + 1}" if d else ""


def is_stub(esaf: dict) -> bool:
    return (esaf.get("title") or "").endswith(STUB_SUFFIX)


class Index:
    """Real (non-stub) ESAFs by badge, for matching."""

    def __init__(self, esafs: list[dict]):
        """esafs: [{esaf_id, title, start_date, badges}] - see repository.list_esaf_badges()."""
        self.by_badge: dict[str, list[dict]] = {}
        for e in esafs:
            if is_stub(e):
                continue
            d = parse_date(e.get("start_date"))
            if d is None:
                continue
            rec = {"esaf_id": e["esaf_id"], "start": d, "badges": set(e.get("badges") or [])}
            for b in rec["badges"]:
                self.by_badge.setdefault(b, []).append(rec)

    def match(self, badges: set[str], start, days: int = DAYS) -> tuple[Optional[str], str]:
        """-> (esaf_id or None, reason)  reason: 'ok', 'no users/date', 'none', 'ambiguous'."""
        d = parse_date(start) if not isinstance(start, date) else start
        badges = {b for b in badges if b}
        if not badges or d is None:
            return None, "no users/date"
        pool = self.by_badge.get(next(iter(badges)), [])
        ok = [r for r in pool if badges <= r["badges"] and abs((r["start"] - d).days) <= days]
        if not ok:
            return None, "none"
        best = min(abs((r["start"] - d).days) for r in ok)
        top = {r["esaf_id"] for r in ok if abs((r["start"] - d).days) == best}
        return (top.pop(), "ok") if len(top) == 1 else (None, "ambiguous")


def tied_matches(index: "Index", badges: set[str], start, days: int = DAYS) -> list[str]:
    """The real ESAFs tied for nearest (the 'twin' ESAFs of one visit) when match() says ambiguous."""
    d = parse_date(start) if not isinstance(start, date) else start
    badges = {b for b in badges if b}
    if not badges or d is None:
        return []
    ok = [r for r in index.by_badge.get(next(iter(badges)), [])
          if badges <= r["badges"] and abs((r["start"] - d).days) <= days]
    if not ok:
        return []
    best = min(abs((r["start"] - d).days) for r in ok)
    top = [r for r in ok if abs((r["start"] - d).days) == best]
    if len({r["start"] for r in top}) > 1:          # equally far but on different days: not twins
        return []
    return sorted({r["esaf_id"] for r in top})


def resolve_experiments(normed: list[dict], esafs: list[dict], registry: dict[str, str]) -> tuple[list[dict], dict[str, str]]:
    """Point master-file rows at the ESAF they belong to.

    Order: experiments already registered on an ESAF, then an ESAF whose number equals the id
    (earlier imports), then a match by users + start date to a real ESAF.  Returns the rows with
    `esaf_id` replaced where an existing real ESAF was found (and `_attached` = True, so the import
    only fills blanks there), and the new {experiment id: esaf id} registrations to store.
    """
    by_id = {e["esaf_id"]: e for e in esafs}
    idx = Index(esafs)
    badges: dict[str, set] = {}
    dates: dict[str, str] = {}
    for r in normed:
        eid = r.get("esaf_id", "")
        if eid:
            badges.setdefault(eid, set()).add(r.get("badge", ""))
            dates.setdefault(eid, r.get("posted_date", ""))
    target: dict[str, str] = {}
    new_reg: dict[str, str] = {}
    for eid in badges:
        if eid in registry:
            target[eid] = registry[eid]
        elif eid in by_id:
            continue                                    # an earlier import's stub (or an ESAF with this very number)
        else:
            hit, _why = idx.match(badges[eid], dates[eid])
            if hit:
                target[eid] = hit
                new_reg[eid] = hit
    out = []
    for r in normed:
        eid = r.get("esaf_id", "")
        if eid in target:
            r = dict(r, esaf_id=target[eid], _attached=True, _experiment_id=eid)
        out.append(r)
    return out, new_reg
