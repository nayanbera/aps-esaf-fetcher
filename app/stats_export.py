"""Excel workbook with the data behind the Statistics page: one sheet per table, native Excel charts
(bar / pie) next to the tables that have one.  The maps have no Excel equivalent, so those sheets are tables only."""

from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

_HEAD = PatternFill("solid", fgColor="D9E1F2")
_LINE = Side(style="thin", color="BFBFBF")
_BOX = Border(left=_LINE, right=_LINE, top=_LINE, bottom=_LINE)
BLUE = "2A78D6"

# How the numbers are obtained - shown on the Statistics page and in the Excel Summary sheet.
NOTES: list[tuple[str, str]] = [
    ("What is counted",
     "Only Approved ESAFs are counted. The filters at the top (from/to year and month, technique, exclude beamline "
     "scientists) apply to every chart and table: a year bound keeps ESAFs whose year is in range, a month bound keeps "
     "ESAFs whose start date is in range."),
    ("Approved ESAFs per year",
     "The number of Approved ESAFs for each ESAF year. For ESAFs synced from APS the year is the calendar year of the start "
     "date; for ESAFs that exist only through the master-file import it is the master file's Exp FY (fiscal year), so an "
     "imported ESAF starting in Oct-Dec can fall in the next year."),
    ("Unique users",
     "A unique user is a badge at one institution: the same badge at another institution is a different user, and ESAF "
     "rows with no institution join the badge's most frequent one. Each unique user is counted once, however many ESAFs "
     "they are on. 'Participation slots' count every (user, ESAF) pair."),
    ("Users by career stage",
     "Each unique user takes the career stage of their most recent ESAF (by start date) that has one; users with none are "
     "Unknown. Stages come from the master-file import, the user-list import and manual edits on the Users page. "
     "Slice numbers are unique users; the percentage is the share of the users in the chart."),
    ("ESAFs by funding agency",
     "Funding sources of each Approved ESAF (from GUP PDFs, ESAF PDFs and the master file) are grouped by agency "
     "(NSF, DOE, ...). An ESAF counts once per agency, so an ESAF funded by two agencies is in both slices and the slices "
     "can add up to more than the number of ESAFs; ESAFs with no funding recorded are not in the chart. The seven largest "
     "agencies are shown, the rest together as Other."),
    ("Maps (US states, countries)",
     "Each unique user is placed by the country (and, for US users, the state) saved on the user - from the e-mail "
     "domain / institution lookup or a manual edit. Country codes and names are both understood. Users with no "
     "recognisable country or state are not drawn; their number is printed under the map. The number on a region is its "
     "unique users, the percentage is its share of the users drawn on that map, and the shading is on a log scale."),
]


def _table(ws, top: int, left: int, headers: list[str], rows: list[list], widths: list[int] | None = None) -> int:
    """Write a header + rows at (top, left); returns the last row used."""
    for j, h in enumerate(headers):
        c = ws.cell(row=top, column=left + j, value=h)
        c.font = Font(bold=True); c.fill = _HEAD; c.border = _BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if widths:
            ws.column_dimensions[c.column_letter].width = widths[j]
    for i, row in enumerate(rows, start=1):
        for j, v in enumerate(row):
            c = ws.cell(row=top + i, column=left + j, value=v)
            c.border = _BOX
    return top + len(rows)


def _bar(ws, title: str, n_rows: int, anchor: str, y_title: str, x_title: str = "") -> None:
    ch = BarChart(); ch.type = "col"; ch.title = title; ch.legend = None
    ch.y_axis.title = y_title; ch.x_axis.title = x_title or None
    ch.add_data(Reference(ws, min_col=2, min_row=1, max_row=1 + n_rows), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=1 + n_rows))
    ch.series[0].graphicalProperties.solidFill = BLUE
    ch.series[0].graphicalProperties.line.solidFill = BLUE
    ch.gapWidth = 60; ch.height = 9; ch.width = 18
    ch.x_axis.delete = False; ch.y_axis.delete = False
    ws.add_chart(ch, anchor)


def _pie(ws, title: str, n_rows: int, colors: list[str], anchor: str, col: int = 2, label_col: int = 1, top: int = 1) -> None:
    ch = PieChart(); ch.title = title; ch.height = 9; ch.width = 14
    ch.add_data(Reference(ws, min_col=col, min_row=top, max_row=top + n_rows), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=label_col, min_row=top + 1, max_row=top + n_rows))
    ch.dataLabels = DataLabelList(); ch.dataLabels.showVal = True      # the counts on the slices, as on the page
    ch.dataLabels.showPercent = False; ch.dataLabels.showCatName = False
    ch.dataLabels.showSerName = False; ch.dataLabels.showLegendKey = False
    for i, color in enumerate(colors):                       # same colours as the page
        pt = DataPoint(idx=i); pt.graphicalProperties.solidFill = color.lstrip("#").upper()
        pt.graphicalProperties.line.solidFill = "FFFFFF"
        ch.series[0].dPt.append(pt)
    ws.add_chart(ch, anchor)


def build_stats_workbook(stats: dict, charts: dict, filters_text: str) -> bytes:
    wb = Workbook()

    ws = wb.active; ws.title = "Summary"
    ws["A1"] = "ChemMatCARS - ESAF statistics"; ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = filters_text
    ws["A3"] = f"Generated {datetime.now():%Y-%m-%d %H:%M}"
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top"); ws.merge_cells("A2:C2"); ws.row_dimensions[2].height = 32
    _table(ws, 5, 1, ["Measure", "Value"], [
        ["Approved ESAFs", stats["total_esafs"]],
        ["All ESAFs in this range (any status)", stats["total_all_esafs"]],
        ["Unique users (badge + institution)", stats["unique_users"]],
        ["Participation slots (user x ESAF)", stats["participation_slots"]],
        ["Users without a known country", stats.get("users_no_country", 0)],
        ["US users without a state", stats.get("us_users_no_state", 0)],
    ], [44, 14])
    ws.cell(row=13, column=1, value="How the numbers are obtained").font = Font(bold=True)
    for i, (title, text) in enumerate(NOTES):
        r = 14 + i
        ws.cell(row=r, column=1, value=title).font = Font(bold=True)
        c = ws.cell(row=r, column=2, value=text); c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=1).alignment = Alignment(vertical="top", wrap_text=True)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
        ws.row_dimensions[r].height = 15 * (len(text) // 70 + 1)
    ws.column_dimensions["C"].width = 60

    ws = wb.create_sheet("ESAFs per year")
    years = charts["years"]
    _table(ws, 1, 1, ["Year", "Approved ESAFs"], [[str(r["year"]), r["count"]] for r in years], [10, 16])
    if years:
        _bar(ws, "Approved ESAFs per year", len(years), "D2", "Approved ESAFs")

    ws = wb.create_sheet("Career stage")
    rows = [[r["employment_level"], r["unique_users"], r["esaf_slots"]] for r in stats["by_employment"]]
    _table(ws, 1, 1, ["Career stage", "Unique users", "Participation slots"], rows, [32, 14, 20])
    if rows:
        _pie(ws, "Unique users by career stage", len(rows), [s["color"] for s in charts["stages"]], "F2")

    ws = wb.create_sheet("Funding")
    groups = sorted(stats.get("funding_groups", []), key=lambda g: -g["count"])
    _table(ws, 1, 1, ["Funding agency", "ESAFs"], [[g["agency"], g["count"]] for g in groups], [38, 10])
    if charts["funding"]:
        ws.cell(row=1, column=4, value="Chart data (largest agencies, rest as Other)").font = Font(italic=True, color="555555")
        _table(ws, 2, 4, ["Agency", "ESAFs"], [[f["label"], f["value"]] for f in charts["funding"]], [38, 10])
        ws.column_dimensions["D"].width = 38
        _pie(ws, "ESAFs by funding agency", len(charts["funding"]), [f["color"] for f in charts["funding"]],
             "G2", col=5, label_col=4, top=2)

    ws = wb.create_sheet("Funding detail")
    detail = []
    for g in groups:
        for sub in g["subgroups"]:
            if sub["labels"]:
                for label, n in sub["labels"]:
                    detail.append([g["agency"], sub["name"] or "", label, n])
            else:
                detail.append([g["agency"], sub["name"] or "", "", sub["count"]])
    _table(ws, 1, 1, ["Agency", "Division / office", "Funding label", "ESAFs"], detail, [34, 22, 70, 10])
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Users per US state")
    _table(ws, 1, 1, ["State", "Code", "Unique users"],
           [[r["name"], r["state"], r["unique_users"]] for r in charts["states"]], [24, 8, 14])
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Users per country")
    _table(ws, 1, 1, ["Country", "ISO code", "Unique users"],
           [[r["country"], r["iso3"], r["unique_users"]] for r in charts["countries"]], [30, 10, 14])
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Institutions")
    _table(ws, 1, 1, ["Institution", "Unique users", "ESAF slots"],
           [[r["institution"], r["unique_users"], r["esaf_slots"]] for r in stats["by_institution"]], [60, 14, 12])
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Top users")
    _table(ws, 1, 1, ["Name", "Institution", "ESAFs"],
           [[r["name"], r["institution"], r["experiments"]] for r in stats["top_users"]], [30, 50, 10])
    ws.freeze_panes = "A2"

    ws = wb.create_sheet("Beamlines")
    _table(ws, 1, 1, ["Beamline", "Approved ESAFs"], [[r["beamline"], r["count"]] for r in stats["by_beamline"]], [26, 16])

    ws = wb.create_sheet("ESAF status")
    _table(ws, 1, 1, ["Status", "ESAFs"], [[r["status"], r["count"]] for r in stats["by_status"]], [26, 10])

    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()
