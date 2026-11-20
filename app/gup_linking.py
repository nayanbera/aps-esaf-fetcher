"""Link ESAFs that have no GUP to the GUP they belong to (SQLite and MongoDB share this).

An ESAF only gets its GUP from its own PDF, or from a sibling ESAF (gup_inference.py).  An ESAF without either is
matched here against the imported GUPs:

* sure    - same PI and the same title (or one title is the start of the other); if several GUPs fit, the one whose
            run cycles include the ESAF's cycle, if that is a single one;
* likely  - same PI, no title match, and exactly one GUP asked for the ESAF's run cycle.  Only linked on request.
"""

from __future__ import annotations

import re

from . import db
from .esaf_matching import is_stub, run_cycle
from .pi_id_import import _same_person, _tokens


def _title(t) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _title_match(a: str, b: str) -> bool:
    a, b = _title(a), _title(b)
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return a == b or (len(short) >= 25 and long_.startswith(short))


def link_esafs_to_gups(apply: bool = False, likely: bool = False, gup_ids: set[str] | None = None) -> dict:
    """-> {sure: [(esaf_id, gup_id)], likely: [(esaf_id, gup_id)], ambiguous: n}.  gup_ids limits the GUPs considered."""
    esafs = [r for r in db.list_esafs(limit=1_000_000)
             if not (r.get("gup_id") or "").strip() and not is_stub(r) and (r.get("pi_name") or "").strip()]
    gups = [g for g in db.list_gups(limit=1_000_000) if gup_ids is None or g["gup_id"] in gup_ids]
    cycles: dict[str, set] = {}

    def gup_cycles(gid: str, g: dict) -> set:           # run cycles the GUP asked for (its ETR rows) + its own
        if gid not in cycles:
            cycles[gid] = {r["run_cycle"] for r in (db.get_gup(gid) or {}).get("etr") or [] if r.get("run_cycle")} | \
                          ({g["run_cycle"]} if g.get("run_cycle") else set())
        return cycles[gid]

    out = {"sure": [], "likely": [], "ambiguous": 0}
    for e in esafs:
        pi = _tokens(e["pi_name"])
        same_pi = [g for g in gups if _same_person(pi, _tokens(g.get("pi_name", "")))]
        if not same_pi:
            continue
        cyc = run_cycle(e.get("start_date"))
        hits = [g for g in same_pi if _title_match(e.get("title"), g.get("title"))]
        if len(hits) > 1 and cyc:
            hits = [g for g in hits if cyc in gup_cycles(g["gup_id"], g)] or hits
        if len(hits) == 1:
            out["sure"].append((e["esaf_id"], hits[0]["gup_id"]))
        elif len(hits) > 1:
            out["ambiguous"] += 1
        elif cyc:
            asked = [g for g in same_pi if cyc in gup_cycles(g["gup_id"], g)]
            if len(asked) == 1:
                out["likely"].append((e["esaf_id"], asked[0]["gup_id"]))
            elif asked:
                out["ambiguous"] += 1
    if apply:
        from . import gup_import
        chosen = out["sure"] + (out["likely"] if likely else [])
        for eid, gid in chosen:
            db.set_esaf_gup(eid, gid)
        touched = {gid for _e, gid in chosen}
        for gid in touched:                              # the new links bring funding and technique
            gup = db.get_gup(gid) or {}
            if gup.get("funding_sources"):
                gup_import.propagate_funding(gid, gup["funding_sources"])
        if touched:
            gup_import.update_techniques(touched)
    return out
