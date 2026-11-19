"""Statistics endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import db, report, stats_export
from ..templates_env import templates

router = APIRouter()

# Categorical slots 1-8 of the validated default palette (light mode), in fixed order; grey = Unknown / Other.
_SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
_GREY = "#a8a7a1"
_STAGE_ORDER = ["Undergraduate student", "Graduate student", "Post-doc", "Faculty / professional staff", "Other"]


def _charts(stats: dict, basis: str = "calendar") -> dict:
    """Plain data for the Statistics charts (colours are decided here, once)."""
    # Career stage: a stage keeps its colour whatever the filters show.
    stages = []
    for r in stats["by_employment"]:
        lv = r["employment_level"]
        known = lv in _STAGE_ORDER
        stages.append({"label": lv, "value": r["unique_users"],
                       "color": _SERIES[_STAGE_ORDER.index(lv)] if known else _GREY})
    # Funding: the biggest agencies in order; the rest fold into Other.
    groups = sorted(stats.get("funding_groups", []), key=lambda g: -g["count"])
    funding = [{"label": g["agency"], "value": g["count"], "color": _SERIES[i]} for i, g in enumerate(groups[:7])]
    if len(groups) > 7:
        funding.append({"label": "Other", "value": sum(g["count"] for g in groups[7:]), "color": _GREY})
    return {
        "year_label": "Fiscal year" if basis == "fiscal" else "Year",
        "years": [{"year": r["year"], "label": f'FY{r["year"]}' if basis == "fiscal" else str(r["year"]), "count": r["count"]}
                  for r in sorted(stats["by_year"], key=lambda r: r["year"] or 0)],
        "stages": stages,
        "funding": funding,
        "countries": stats.get("by_country", []),
        "states": stats.get("by_state", []),
        "no_country": stats.get("users_no_country", 0),
        "us_no_state": stats.get("us_users_no_state", 0),
    }

_DEFAULT_FROM = 2024


def _parse_year(v: Optional[str]) -> Optional[int]:
    """Convert a query-string year value to int, treating '' and None as None."""
    if not v:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _basis(v: Optional[str]) -> str:
    return "fiscal" if v == "fiscal" else "calendar"


def _range(from_year, from_month, to_year, to_month, basis: str = "calendar") -> dict:
    """Year/month filter inputs -> get_stats kwargs: bounds on the ESAF start date.

    A year means a calendar year (Jan-Dec) or, for basis 'fiscal', a fiscal year (Oct-Sep: FY2026 is Oct 2025 - Sep 2026).
    A month chosen with the year is a month of that year; in fiscal mode Oct-Dec belong to the previous calendar year.
    """
    fy, fm = _parse_year(from_year), _parse_month(from_month)
    ty, tm = _parse_year(to_year),   _parse_month(to_month)
    fiscal = basis == "fiscal"
    cal = lambda y, m: y - 1 if (fiscal and m >= 10) else y          # calendar year of month m of year y
    kw: dict = {"year_from": None, "year_to": None, "start_from": None, "start_before": None, "year_basis": basis}
    if fy is not None:
        kw["start_from"] = (f"{cal(fy, fm):04d}-{fm:02d}-01" if fm
                            else f"{fy - 1:04d}-10-01" if fiscal else f"{fy:04d}-01-01")
    if ty is not None:
        if tm:
            y = cal(ty, tm)
            ny, nm = (y + 1, 1) if tm == 12 else (y, tm + 1)
            kw["start_before"] = f"{ny:04d}-{nm:02d}-01"
        else:
            kw["start_before"] = f"{ty:04d}-10-01" if fiscal else f"{ty + 1:04d}-01-01"
    return kw


def _parse_month(v: Optional[str]) -> Optional[int]:
    try:
        m = int(v) if v else None
    except (ValueError, TypeError):
        return None
    return m if m and 1 <= m <= 12 else None


@router.get("/api/stats")
def api_stats(
    from_year:          Optional[str] = None,
    to_year:            Optional[str] = None,
    from_month:         Optional[str] = None,
    to_month:           Optional[str] = None,
    technique:          Optional[str] = None,
    exclude_scientists: Optional[str] = None,
    year_basis:         Optional[str] = None,
):
    return db.get_stats(
        **_range(from_year, from_month, to_year, to_month, _basis(year_basis)),
        technique=technique or None,
        exclude_scientists=bool(exclude_scientists),
    )


@router.get("/stats", response_class=HTMLResponse)
def stats_page(
    request:            Request,
    from_year:          Optional[str] = str(_DEFAULT_FROM),
    to_year:            Optional[str] = None,
    from_month:         Optional[str] = None,
    to_month:           Optional[str] = None,
    technique:          Optional[str] = None,
    exclude_scientists: Optional[str] = None,
    year_basis:         Optional[str] = None,
):
    from_yr  = _parse_year(from_year)
    to_yr    = _parse_year(to_year)
    tech     = technique or None
    exc_sci  = exclude_scientists == "1"
    stats = db.get_stats(
        **_range(from_year, from_month, to_year, to_month, _basis(year_basis)),
        technique=tech, exclude_scientists=exc_sci,
    )
    return templates.TemplateResponse("stats.html", {
        "request":            request,
        "stats":              stats,
        "charts":             _charts(stats, _basis(year_basis)),
        "year_basis":         _basis(year_basis),
        "notes":              stats_export.NOTES,
        "from_year":          from_yr,
        "to_year":            to_yr,
        "from_month":         _parse_month(from_month) if from_yr else None,
        "to_month":           _parse_month(to_month) if to_yr else None,
        "months":             ["January", "February", "March", "April", "May", "June", "July",
                               "August", "September", "October", "November", "December"],
        "technique":          tech,
        "exclude_scientists": exc_sci,
        "current_year":       datetime.now().year,
        "report_years":       list(range(1, report.project_year_of(datetime.now().date()) + 1)),
        "report_default":     max(1, report.project_year_of(datetime.now().date()) - 1),
    })


@router.get("/stats/data.xlsx")
async def stats_data(
    from_year:          Optional[str] = str(_DEFAULT_FROM),
    to_year:            Optional[str] = None,
    from_month:         Optional[str] = None,
    to_month:           Optional[str] = None,
    technique:          Optional[str] = None,
    exclude_scientists: Optional[str] = None,
    year_basis:         Optional[str] = None,
):
    """Everything on the Statistics page as an Excel workbook (one sheet per table, charts where Excel has them)."""
    fy, ty = _parse_year(from_year), _parse_year(to_year)
    fm = _parse_month(from_month) if fy else None
    tm = _parse_month(to_month) if ty else None
    exc = exclude_scientists == "1"
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    yp = "FY" if _basis(year_basis) == "fiscal" else ""
    text = (f"Approved ESAFs from {months[fm - 1] + ' ' if fm else ''}{(yp + str(fy)) if fy else 'the beginning'} to "
            f"{months[tm - 1] + ' ' if tm else ''}{(yp + str(ty)) if ty else 'present'}"
            + ("; fiscal years (Oct-Sep)" if yp else "; calendar years")
            + (f"; technique {technique}" if technique else "") + ("; beamline scientists excluded" if exc else ""))
    stats = await run_in_threadpool(lambda: db.get_stats(
        **_range(from_year, from_month, to_year, to_month, _basis(year_basis)), technique=technique or None, exclude_scientists=exc))
    content = await run_in_threadpool(stats_export.build_stats_workbook, stats, _charts(stats, _basis(year_basis)), text)
    name = f"ESAF_statistics_{(yp + str(fy)) if fy else 'all'}-{(yp + str(ty)) if ty else 'present'}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/stats/report.xlsx")
async def stats_report(py: int):
    """User report workbook (Teams / Experiments / Users) for one project year."""
    if py < 1 or py > 50:
        raise HTTPException(422, "Invalid project year")
    data = await run_in_threadpool(report.build_report_data, py)
    content = await run_in_threadpool(report.build_workbook, data)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="User Reporting_YR{py}.xlsx"'},
    )
