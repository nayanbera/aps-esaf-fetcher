"""Fill PI Group "PI ID"s from the Teams sheet of the user-reporting Excel file.

Each Teams row (Team ID, last name(s), first name(s), institution) is matched to
a PI Group by the PI's name.  A person with several team IDs (e.g. AC-50 and
AS-08) gets all of them on their group.
"""

from __future__ import annotations

import io
import re
import unicodedata

from openpyxl import load_workbook


def _tokens(*parts: str) -> frozenset:
    text = unicodedata.normalize("NFKD", " ".join(parts))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    toks = [t for t in re.split(r"[^a-z0-9]+", text) if len(t) > 1]   # drop initials
    return frozenset(toks)


def _same_person(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return False
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return len(small) >= 2 and small <= big


def _inst_score(a: str, b: str) -> int:
    return len(_tokens(a) & _tokens(b))


def read_teams(data: bytes) -> list[dict]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb["Teams"] if "Teams" in wb.sheetnames else wb.worksheets[0]
    out = []
    for row in ws.iter_rows(min_row=1, values_only=True):
        cells = list(row) + [None] * 5
        tid = str(cells[1] or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2,3}-\d+", tid):
            continue
        out.append({"id": tid, "last": str(cells[2] or "").strip(),
                    "first": str(cells[3] or "").strip(),
                    "institution": str(cells[4] or "").strip()})
    return out


def match_ids(teams: list[dict], groups: list[dict]) -> dict:
    """-> {"assign": {group name: [ids]}, "unmatched": [...], "ambiguous": [...]}"""
    gtoks = {g["name"]: _tokens(g.get("pi_name") or "") for g in groups}
    assign: dict[str, list[str]] = {}
    unmatched, ambiguous = [], []
    for t in teams:
        # first/last may be swapped or hold several people ("Vaknin, Wang"); the
        # whole name is compared as a bag of words, per person where possible
        lasts = [x.strip() for x in t["last"].split(",") if x.strip()] or [""]
        firsts = [x.strip() for x in t["first"].split(",") if x.strip()] or [""]
        people = [(firsts[i] if i < len(firsts) else "", lasts[i]) for i in range(len(lasts))]
        cands: set[str] = set()
        for first, last in people:
            tok = _tokens(first, last)
            cands |= {n for n, g in gtoks.items() if _same_person(tok, g)}
        label = f'{t["id"]} {t["first"]} {t["last"]} ({t["institution"]})'
        if not cands:
            unmatched.append(label)
            continue
        if len(cands) > 1:
            ranked = sorted(cands, key=lambda n: -_inst_score(
                t["institution"], next(g.get("institution", "") for g in groups if g["name"] == n)))
            top = [n for n in ranked if _inst_score(t["institution"], next(
                g.get("institution", "") for g in groups if g["name"] == n)) ==
                _inst_score(t["institution"], next(
                    g.get("institution", "") for g in groups if g["name"] == ranked[0]))]
            if len(top) > 1:
                ambiguous.append(f"{label} → {', '.join(sorted(top))}")
                continue
            cands = {top[0]}
        name = next(iter(cands))
        assign.setdefault(name, [])
        if t["id"] not in assign[name]:
            assign[name].append(t["id"])
    return {"assign": assign, "unmatched": unmatched, "ambiguous": ambiguous}
