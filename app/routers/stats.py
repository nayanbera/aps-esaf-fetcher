"""Statistics endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import db, report
from ..templates_env import templates

router = APIRouter()

_DEFAULT_FROM = 2024


def _parse_year(v: Optional[str]) -> Optional[int]:
    """Convert a query-string year value to int, treating '' and None as None."""
    if not v:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _range(from_year, from_month, to_year, to_month) -> dict:
    """Year/month filter inputs -> get_stats kwargs.

    A bound with a month becomes an exact date bound on the ESAF start date
    (to-month is inclusive); a bound with only a year keeps the plain year filter.
    """
    fy, fm = _parse_year(from_year), _parse_month(from_month)
    ty, tm = _parse_year(to_year),   _parse_month(to_month)
    kw: dict = {"year_from": fy, "year_to": ty, "start_from": None, "start_before": None}
    if fy is not None and fm:
        kw.update(year_from=None, start_from=f"{fy:04d}-{fm:02d}-01")
    if ty is not None and tm:
        ny, nm = (ty + 1, 1) if tm == 12 else (ty, tm + 1)
        kw.update(year_to=None, start_before=f"{ny:04d}-{nm:02d}-01")
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
):
    return db.get_stats(
        **_range(from_year, from_month, to_year, to_month),
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
):
    from_yr  = _parse_year(from_year)
    to_yr    = _parse_year(to_year)
    tech     = technique or None
    exc_sci  = exclude_scientists == "1"
    stats = db.get_stats(
        **_range(from_year, from_month, to_year, to_month),
        technique=tech, exclude_scientists=exc_sci,
    )
    return templates.TemplateResponse("stats.html", {
        "request":            request,
        "stats":              stats,
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
