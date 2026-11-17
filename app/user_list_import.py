"""Read a user-list sheet (Last Name, First Name, Institution, E-mail, Institutional Role,
Funding 1-3, and an unnamed column holding PI / SP) and match people to existing users.

These lists carry no badge or ESAF ID, so people are matched by e-mail, then by name.
"""

from __future__ import annotations

import io
import re

from openpyxl import load_workbook

from .pi_id_import import _inst_score, _same_person, _tokens

_FILLABLE = ("email", "institution", "employment_level")


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

    c_last, c_first = col("last name"), col("first name")
    c_inst, c_mail = col("institution"), col("e-mail", "email")
    c_role = col("institutional role", "role", "employment level")
    c_fund = [i for i, h in enumerate(head) if h.startswith("funding")]
    c_extra = [i for i, h in enumerate(head) if not h and i > max(c for c in (c_last, c_first, c_inst, c_role) if c is not None)]

    people = []
    for r in rows[hi + 1:]:
        get = lambda i: _s(r[i]) if i is not None and i < len(r) else ""
        last, first = get(c_last), get(c_first)
        if not last and not first:
            continue
        funding = []
        for i in c_fund:
            for f in re.split(r";", get(i)):
                if f.strip() and f.strip() not in funding:
                    funding.append(f.strip())
        extra = [get(i) for i in c_extra if get(i)]
        flag = next((e for e in extra if e.upper() in ("PI", "SP")), "")
        note = "; ".join(e for e in extra if e != flag)
        if not flag and note.upper().startswith("PI"):
            flag, note = "PI", note
        people.append({"last_name": last, "first_name": first, "institution": get(c_inst),
                       "email": get(c_mail).lower(), "employment_level": get(c_role),
                       "funding": funding, "role_flag": flag, "note": note})
    return ws.title, people


def match(people: list[dict], users: list[dict]) -> list[dict]:
    """Add 'status' (matched / new / ambiguous), 'badge' and 'fills' {field: value} to each person."""
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
        q = dict(p, badge="", fills={}, status="new", matches=[])
        if len(badges) > 1:
            q.update(status="ambiguous", matches=sorted(badges))
        elif badges:
            u = cands[0]
            q.update(status="matched", badge=u["badge"], matches=[u["badge"]],
                     fills={f: p[f] for f in _FILLABLE if p[f] and not (u.get(f) or "").strip()})
        out.append(q)
    return out
