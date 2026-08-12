"""Statistics endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import db
from ..templates_env import templates

router = APIRouter()

_DEFAULT_FROM = 2024


@router.get("/api/stats")
def api_stats(
    from_year: Optional[int] = None,
    to_year:   Optional[int] = None,
):
    return db.get_stats(year_from=from_year, year_to=to_year)


@router.get("/stats", response_class=HTMLResponse)
def stats_page(
    request:   Request,
    from_year: Optional[int] = _DEFAULT_FROM,
    to_year:   Optional[int] = None,
):
    current_year = datetime.now().year
    # to_year=None means "up to the present" — pass None so no upper bound is applied
    stats = db.get_stats(year_from=from_year, year_to=to_year)
    return templates.TemplateResponse("stats.html", {
        "request":      request,
        "stats":        stats,
        "from_year":    from_year,
        "to_year":      to_year,
        "current_year": current_year,
    })
