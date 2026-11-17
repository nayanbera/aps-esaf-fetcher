"""Update users' career stage (Employment Level) from a user-list sheet.

The sheet (Last Name, First Name, Institution, E-mail, Institutional Role, ...) carries no
badge, so people are matched to existing users by e-mail, then by name.  Only the
Institutional Role is used; people who are not in the database are reported, not added.
"""

from __future__ import annotations

import io
import re

from openpyxl import load_workbook

from .pi_id_import import _inst_score, _same_person, _tokens


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def sheet_names(data: bytes) -> list[str]:
    return load_workbook(io.BytesIO(data), read_only=True).sheetnames


def read_people(data: bytes, sheet: str = "") -> tuple[str, list[dict]]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    if sheet and sheet not in wb.sheetnames:
        raise ValueError(f'No sheet named "{sheet}". Sheets: {", ".join(wb.sheetnames)}')
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hi = next((i for i, r in enumerate(rows[:15])
               if {"last name", "first name"} <= {_s(c).lower() for c in r}), None)
    if hi is None:
        raise ValueError('No header row with "Last Name" and "First Name" found.')
    head = [_s(c).lower() for c in rows[hi]]

    def col(*names):
        return next((i for i, h in enumerate(head) if h in names), None)

    c_last, c_first, c_inst = col("last name"), col("first name"), col("institution")
    c_mail, c_role = col("e-mail", "email"), col("institutional role", "role", "employment level")
    if c_role is None:
        raise ValueError('No "Institutional Role" column found.')

    people = []
    for r in rows[hi + 1:]:
        get = lambda i: _s(r[i]) if i is not None and i < len(r) else ""
        if get(c_last) or get(c_first):
            people.append({"last_name": get(c_last), "first_name": get(c_first),
                           "institution": get(c_inst), "email": get(c_mail).lower(),
                           "employment_level": get(c_role)})
    return ws.title, people


def cycle_start(sheet: str) -> str:
    """'2026-3' -> '2026-09-01' (APS run cycles: 1 = Jan-Apr, 2 = May-Aug, 3 = Sep-Dec); '' if not a cycle name."""
    m = re.fullmatch(r"\s*(\d{4})-([123])\s*", sheet or "")
    return f"{m.group(1)}-{('01', '05', '09')[int(m.group(2)) - 1]}-01" if m else ""


def match(people: list[dict], users: list[dict]) -> list[dict]:
    """Match each person to a unique user (badge + institution) from list_unique_users().

    Adds 'status' (matched / new / ambiguous), 'badge' and 'matched_institution'."""
    by_email = {}
    for u in users:
        if u.get("email"):
            by_email.setdefault(u["email"].strip().lower(), []).append(u)
    utoks = [(u, _tokens(u.get("name", ""))) for u in users]

    out = []
    for p in people:
        cands = by_email.get(p["email"], []) if p["email"] else []
        if not cands:
            pt = _tokens(p["first_name"], p["last_name"])
            cands = [u for u, t in utoks if _same_person(pt, t)]
        if len(cands) > 1:
            best = max(_inst_score(p["institution"], u.get("institution", "")) for u in cands)
            cands = [u for u in cands if _inst_score(p["institution"], u.get("institution", "")) == best]
        q = dict(p, badge="", matched_institution="", groups=[], status="new", matches=[])
        if len({u["badge"] for u in cands}) > 1:
            q.update(status="ambiguous", matches=sorted(f'{u["badge"]} ({u.get("institution", "")})' for u in cands))
        elif cands:
            # one person; if the university appears under several spellings, the role applies to all of them
            q.update(status="matched", badge=cands[0]["badge"], matched_institution=cands[0].get("institution", ""),
                     groups=[u.get("institution", "") for u in cands])
        out.append(q)
    return out
