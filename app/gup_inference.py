"""Infer a missing GUP ID on an ESAF from its sibling ESAFs.

APS often issues several ESAFs for one proposal (same title and PI, different
ESAF IDs).  The GUP link normally comes from an ESAF's own PDF, so a sibling
without a PDF has none.  After each ESAF import we copy the GUP across siblings
— conservatively:

* only ESAFs whose gup_id is empty are filled; existing values are never touched;
* siblings = same normalised title + PI name + year;
* a group is filled only if its linked members agree on exactly one GUP.
"""

from __future__ import annotations

import logging
import re

from . import db
from .gup_import import propagate_funding

log = logging.getLogger(__name__)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def fill_gup_from_siblings() -> tuple[str, list[str]]:
    """Returns (short summary for the status line, detail lines for the banner)."""
    groups: dict[tuple, list[dict]] = {}
    for row in db.list_esaf_gup_rows():
        title, pi = _norm(row.get("title")), _norm(row.get("pi_name"))
        if not title or not pi:
            continue  # too little to call two ESAFs siblings
        groups.setdefault((title, pi, row.get("year")), []).append(row)

    filled: list[tuple[str, str]] = []
    ambiguous = 0
    for members in groups.values():
        gups = {(m.get("gup_id") or "").strip() for m in members} - {""}
        blanks = [m for m in members if not (m.get("gup_id") or "").strip()]
        if not blanks or not gups:
            continue
        if len(gups) > 1:
            ambiguous += 1
            continue
        gup_id = next(iter(gups))
        for m in blanks:
            db.set_esaf_gup(m["esaf_id"], gup_id)
            filled.append((m["esaf_id"], gup_id))

    for gup_id in {g for _, g in filled}:
        gup = db.get_gup(gup_id)
        if gup and gup.get("funding_sources"):
            propagate_funding(gup_id, gup["funding_sources"])

    for esaf_id, gup_id in filled:
        log.info("Inferred GUP %s for ESAF %s from sibling ESAFs", gup_id, esaf_id)
    if not filled and not ambiguous:
        return "", []
    short = f"GUP inferred for {len(filled)} ESAF(s) from siblings" if filled else ""
    details = [f"GUP inferred from sibling ESAFs: " + ", ".join(
        f"{e}→{g}" for e, g in filled[:25]) + (" …" if len(filled) > 25 else "")] if filled else []
    if ambiguous:
        details.append(f"{ambiguous} sibling group(s) have conflicting GUPs and were left blank.")
    return short, details
