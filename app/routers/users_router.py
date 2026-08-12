"""Unique users list endpoint."""

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from .. import db
from ..templates_env import templates

router = APIRouter()

_DEFAULT_FROM = 2024


def _parse_year(v: Optional[str]) -> Optional[int]:
    if not v:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


@router.get("/users", response_class=HTMLResponse)
def users_page(
    request:            Request,
    from_year:          Optional[str] = str(_DEFAULT_FROM),
    to_year:            Optional[str] = None,
    technique:          Optional[str] = None,
    exclude_scientists: Optional[str] = None,
):
    from_yr = _parse_year(from_year)
    to_yr   = _parse_year(to_year)
    tech    = technique or None
    exc_sci = exclude_scientists == "1"

    users = db.list_unique_users(
        year_from=from_yr, year_to=to_yr,
        technique=tech, exclude_scientists=exc_sci,
    )
    _meta = db.get_stats(year_from=None, year_to=None)
    all_techniques = _meta.get("all_techniques", [])
    all_years      = _meta.get("all_years", [])

    return templates.TemplateResponse("users.html", {
        "request":            request,
        "users":              users,
        "from_year":          from_yr,
        "to_year":            to_yr,
        "technique":          tech,
        "exclude_scientists": exc_sci,
        "all_years":          all_years,
        "all_techniques":     all_techniques,
    })


@router.get("/users/{badge}/detail", response_class=HTMLResponse)
def user_detail(badge: str, request: Request):
    user = db.get_user_detail(badge)
    if user is None:
        return Response(status_code=204)
    return templates.TemplateResponse("partials/user_detail_row.html", {
        "request": request,
        "user":    user,
    })
