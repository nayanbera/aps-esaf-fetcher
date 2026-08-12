"""Statistics endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import db
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


@router.get("/api/stats")
def api_stats(
    from_year: Optional[str] = None,
    to_year:   Optional[str] = None,
):
    return db.get_stats(year_from=_parse_year(from_year), year_to=_parse_year(to_year))


@router.get("/stats", response_class=HTMLResponse)
def stats_page(
    request:   Request,
    from_year: Optional[str] = str(_DEFAULT_FROM),
    to_year:   Optional[str] = None,
):
    from_yr = _parse_year(from_year)
    to_yr   = _parse_year(to_year)
    stats = db.get_stats(year_from=from_yr, year_to=to_yr)
    return templates.TemplateResponse("stats.html", {
        "request":      request,
        "stats":        stats,
        "from_year":    from_yr,
        "to_year":      to_yr,
        "current_year": datetime.now().year,
    })
