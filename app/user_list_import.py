"""Update users' career stage (Employment Level) from a user-list sheet.

The sheet (Last Name, First Name, Institution, E-mail, Institutional Role, ...) carries no
badge, so people are matched to existing users by e-mail, then by name.  Only the
Institutional Role is used; people who are not in the database are reported, not added.
"""

from __future__ import annotations

import io

from openpyxl import load_workbook

from .pi_id_import import _inst_score, _same_person, _tokens


def _s(v) -> str:
    return "" if v is None else str(v).strip()


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


def match(people: list[dict], users: list[dict]) -> list[dict]:
    """Add 'status' (matched / unchanged / empty / new / ambiguous), 'badge' and 'old' to each person."""
    by_email = {}
    for u in users:
        if u.get("email"):
            by_email.setdefault(u["email"].strip().lower(), []).append(u)
    utoks = [(u, _tokens(u.get("first_name", ""), u.get("last_name", ""))) for u in users]

    out = []
    for p in people:
        cands = by_email.get(p["email"], []) if p["email"] else []
        if not cands:
            pt = _tokens(p["first_name"], p["last_name"])
            cands = [u for u, t in utoks if _same_person(pt, t)]
        if len({u["badge"] for u in cands}) > 1:
            best = max(_inst_score(p["institution"], u.get("institution", "")) for u in cands)
            cands = [u for u in cands if _inst_score(p["institution"], u.get("institution", "")) == best]
        badges = {u["badge"] for u in cands}
        q = dict(p, badge="", old="", status="new", matches=sorted(badges))
        if len(badges) > 1:
            q["status"] = "ambiguous"
        elif badges:
            u = cands[0]
            q.update(badge=u["badge"], old=(u.get("employment_level") or "").strip())
            if not p["employment_level"]:
                q["status"] = "empty"                   # no role in the sheet - leave the user alone
            elif p["employment_level"].lower() == q["old"].lower():
                q["status"] = "unchanged"
            else:
                q["status"] = "matched"                 # will be updated
        out.append(q)
    return out
