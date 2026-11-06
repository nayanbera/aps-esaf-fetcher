"""Excel user report (Teams / Experiments / Users) for one project year.

Project years run Sep 1 – Aug 31; PY1 starts in September 2024.  Teams are PI
Groups: a group listed in several technique tables gets one team ID per
technique (prefix + running number, e.g. LI-09, AC-09).
"""

from __future__ import annotations

import io
import re
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from . import db
from .funding_groups import classify

PY1_START_YEAR = 2024            # PY1 = 1 Sep 2024 – 31 Aug 2025

# technique -> (team-ID prefix, capability name in the report)
TECHNIQUES = {
    "Xtal":   ("AC", "Advanced Crystallography"),
    "ASWAXS": ("AS", "ASWAXS"),
    "Surf":   ("LI", "Liquid Interface Science"),
}
_PREFIX_ORDER = ("AC", "AS", "LI")   # order of the Teams sheet, as in the reference report


def project_year_range(py: int) -> tuple[date, date]:
    y = PY1_START_YEAR + py - 1
    return date(y, 9, 1), date(y + 1, 8, 31)


def project_year_of(d: date) -> int:
    return (d.year if d.month >= 9 else d.year - 1) - PY1_START_YEAR + 1


def py_month_label(d: date) -> str:
    """PY2M7 for March 2026 (months count from September)."""
    return f"PY{project_year_of(d)}M{(d.month - 9) % 12 + 1}"


def _parse_date(s) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s or ""))
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def split_name(full: str) -> tuple[str, str]:
    """'Yu-Sheng Chen' -> ('Chen', 'Yu-Sheng')."""
    parts = (full or "").split()
    if not parts:
        return "", ""
    return parts[-1], " ".join(parts[:-1])


def title_from_career_stage(level: str) -> str:
    s = (level or "").strip()
    low = s.lower()
    if not s:
        return ""
    if "undergrad" in low:
        return "Undergraduate student"
    if "grad" in low or "student" in low:
        return "Graduate student"
    if "post" in low:
        return "Post-doc"
    if re.search(r"faculty|professor|staff|scientist|employee|researcher|engineer|technician", low):
        return "Employee"
    return s


_AWARD_RE = re.compile(r"(?<![A-Za-z])([A-Z]{3,5})\s*-?\s*(\d{6,7})\b")


def split_awards(labels: list[str]) -> tuple[str, str]:
    """(NSF awards, other awards) strings for one ESAF's funding labels."""
    nsf, other = [], []
    for label in labels:
        clean = re.sub(r"\s*\(\d+(\.\d+)?%\)\s*$", "", label).strip()
        agency, _ = classify(label)
        if agency == "NSF":
            m = _AWARD_RE.search(clean.replace("—", " "))
            if m:
                nsf.append(f"{m[1]}-{m[2]}")
                continue
            m = re.search(r"\b(\d{6,7})\b", clean)
            if m:
                nsf.append(m[1])
                continue
        if clean:
            other.append(clean)
    dedupe = lambda xs: list(dict.fromkeys(xs))
    return "; ".join(dedupe(nsf)), "; ".join(dedupe(other))


def access_type(users: list[dict]) -> str:
    """remote if every user with a known type is OFF-SITE, otherwise on-site."""
    kinds = [(u.get("user_type") or "").upper() for u in users]
    kinds = [k for k in kinds if k]
    return "remote" if kinds and all("OFF" in k for k in kinds) else "on-site"


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def build_report_data(py: int) -> dict:
    start, end = project_year_range(py)

    # Teams: one per (PI group, technique), numbered in creation order per prefix.
    groups = db.list_pi_groups()
    groups.sort(key=lambda g: (str(g.get("created_at") or "~"), g["name"]))
    teams, team_id = [], {}
    counters = {p: 0 for p in _PREFIX_ORDER}
    for g in groups:
        for tech in (g.get("technique") or "").split(","):
            if tech not in TECHNIQUES:
                continue
            prefix = TECHNIQUES[tech][0]
            counters[prefix] += 1
            tid = f"{prefix}-{counters[prefix]:02d}"
            team_id[(g["name"], tech)] = tid
            last, first = split_name(g.get("pi_name") or "")
            teams.append({"prefix": prefix, "id": tid, "last": last, "first": first,
                          "institution": g.get("institution") or ""})
    teams.sort(key=lambda t: (_PREFIX_ORDER.index(t["prefix"]), t["id"]))

    group_techs = {g["name"]: [t for t in (g.get("technique") or "").split(",") if t in TECHNIQUES]
                   for g in groups}
    scientists = {s["badge"] for s in db.list_beamline_scientists()}

    experiments, users = [], []
    rows = db.list_esafs(status="Approved", limit=1_000_000)
    rows = [r for r in rows
            if (d := _parse_date(r.get("start_date"))) and start <= d <= end]
    rows.sort(key=lambda r: (str(r.get("start_date")), r["esaf_id"]))
    for r in rows:
        esaf = db.get_esaf(r["esaf_id"])
        if not esaf:
            continue
        pg = esaf.get("pi_group") or ""
        techs = group_techs.get(pg, [])
        tech = esaf.get("technique") if esaf.get("technique") in techs else (techs[0] if techs else esaf.get("technique"))
        tid = team_id.get((pg, tech), "")
        nsf, other = split_awards(esaf.get("funding_sources") or [])
        d = _parse_date(esaf["start_date"])
        experiments.append({
            "team": tid, "esaf_id": esaf["esaf_id"],
            "capability": TECHNIQUES.get(tech, ("", tech or ""))[1],
            "access": access_type(esaf.get("users") or []),
            "date": py_month_label(d), "nsf": nsf, "other": other,
        })
        for u in esaf.get("users") or []:
            if u.get("badge") in scientists:
                continue
            users.append({
                "team": tid, "esaf_id": esaf["esaf_id"],
                "name": f"{u.get('last_name', '')}, {u.get('first_name', '')}".strip(", "),
                "title": title_from_career_stage(u.get("employment_level")),
                "institution": u.get("institution") or "",
            })
    users.sort(key=lambda u: (u["name"].lower(), u["esaf_id"]))
    return {"py": py, "start": start, "end": end,
            "teams": teams, "experiments": experiments, "users": users}


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------

_THIN = Side(style="thin", color="999999")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEAD_FILL = PatternFill("solid", fgColor="D9E1F2")
_WRAP = Alignment(wrap_text=True, vertical="top")
_CENTER = Alignment(wrap_text=True, vertical="top", horizontal="center")


def _sheet(wb: Workbook, title: str, columns: list[tuple], rows: list[list], first: bool):
    """columns: (header, description, width, centered)."""
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    n = len(columns)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14, color="FF0000")
    ws["A1"].alignment = Alignment(horizontal="center")
    all_cols = [("No.", "", 6, True)] + list(columns)
    for i, (head, desc, width, _) in enumerate(all_cols, start=1):
        c = ws.cell(row=2, column=i, value=head)
        c.font = Font(bold=True); c.fill = _HEAD_FILL; c.alignment = _CENTER; c.border = _BORDER
        d = ws.cell(row=3, column=i, value=desc or None)
        d.font = Font(italic=True, color="555555"); d.alignment = _WRAP; d.border = _BORDER
        ws.column_dimensions[ws.cell(row=2, column=i).column_letter].width = width
    ws.row_dimensions[3].height = 78
    ws.freeze_panes = "A4"
    for n_, row in enumerate(rows, start=1):
        for i, val in enumerate([n_] + row, start=1):
            c = ws.cell(row=3 + n_, column=i, value=val)
            c.border = _BORDER
            c.alignment = _CENTER if all_cols[i - 1][3] else _WRAP
    return ws


def build_workbook(data: dict) -> bytes:
    wb = Workbook()
    _sheet(wb, "Teams", [
        ("Team ID", "Unique ID associated with individual PI, or collaborative PI team. "
                    "One individual could be associated with more than one Team ID.", 12, True),
        ("Team Lead(s) — Last Name", "Last Name(s) of team leads, i.e., Name1, Name2,…", 24, False),
        ("Team Lead(s) — First Name", "First Name(s) of team leads, i.e., Name1, Name2,…", 24, False),
        ("Institution", "Institution", 60, False),
    ], [[t["id"], t["last"], t["first"], t["institution"]] for t in data["teams"]], True)

    _sheet(wb, "Experiments", [
        ("Team ID", "Team ID from teams table.", 11, True),
        ("Experiment ID", "Unique ID associated with experiment or experimental run.", 16, True),
        ("Capability Used", "List of instrument(s) and/or capability identifiers", 26, True),
        ("Access", "Type of access, e.g. on-site, remote, mail-in", 12, True),
        ("Date", "Project year and month, e.g., PY1M4", 11, True),
        ("Associated Awards (NSF)", "NSF awards supporting science, including divisional abbreviation, "
                                    "e.g. CHE-#######. Multiple award list possible", 28, False),
        ("Associated Awards (Other)", "Awards from other sources (federal and private) supporting "
                                      "science. Multiple award list possible.", 40, False),
    ], [[e["team"], int(e["esaf_id"]) if str(e["esaf_id"]).isdigit() else e["esaf_id"],
         e["capability"], e["access"], e["date"], e["nsf"] or None, e["other"] or None]
        for e in data["experiments"]], False)

    _sheet(wb, "Users", [
        ("Team ID", "ID from teams table", 12, True),
        ("Experiment ID", "ID from experiments table", 16, True),
        ("Name", "Last, First", 28, False),
        ("Title", "e.g., Assistant Professor, Professor, Student, Scientist, etc.", 24, False),
        ("Institution", "Institution Name", 60, False),
    ], [[u["team"], int(u["esaf_id"]) if str(u["esaf_id"]).isdigit() else u["esaf_id"],
         u["name"], u["title"], u["institution"]] for u in data["users"]], False)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
