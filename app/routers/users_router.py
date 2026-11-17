"""Unique users list endpoint."""

from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
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
    employment_level:   Optional[str] = None,
):
    from_yr = _parse_year(from_year)
    to_yr   = _parse_year(to_year)
    tech    = technique or None
    exc_sci = exclude_scientists == "1"

    users = db.list_unique_users(
        year_from=from_yr, year_to=to_yr,
        technique=tech, exclude_scientists=exc_sci,
    )
    # Career-stage filter: options come from the unfiltered list; blank = "Unknown".
    def _level(u: dict) -> str:
        return (u.get("employment_level") or "").strip() or "Unknown"

    levels = sorted({_level(u) for u in users}, key=lambda x: (x == "Unknown", x.lower()))
    if employment_level:
        users = [u for u in users if _level(u) == employment_level]

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
        "employment_level":   employment_level or "",
        "employment_levels":  levels,
        "all_years":          all_years,
        "all_techniques":     all_techniques,
    })


CAREER_STAGES = ["Undergraduate student", "Graduate student", "Post-doc",
                 "Faculty / professional staff", "Other", "No information provided"]


@router.post("/users/{badge}/esaf/{esaf_id}/career-stage", response_class=HTMLResponse)
def set_career_stage(request: Request, badge: str, esaf_id: str, level: str = Form("")):
    """Edit one user's career stage on one ESAF (the stage can differ between ESAFs)."""
    level = level.strip()
    if level and level not in CAREER_STAGES:
        raise HTTPException(400, f"Unknown career stage '{level}'")
    if not db.set_user_career_stage(esaf_id, badge, level):
        raise HTTPException(404, "That user is not on that ESAF")
    return templates.TemplateResponse("partials/career_stage_select.html", {
        "request": request, "badge": badge, "esaf_id": esaf_id, "level": level,
        "stages": CAREER_STAGES, "saved": True})


@router.get("/users/{badge}/detail", response_class=HTMLResponse)
def user_detail(badge: str, request: Request, institution: str = ""):
    user = db.get_user_detail(badge, institution)
    if user is None:
        return Response(status_code=204)
    return templates.TemplateResponse("partials/user_detail_row.html", {
        "request": request,
        "user":    user,
        "stages":  CAREER_STAGES,
    })
