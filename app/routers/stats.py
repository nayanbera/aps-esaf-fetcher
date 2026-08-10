"""Statistics endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import db
from ..templates_env import templates

router = APIRouter()


@router.get("/api/stats")
def api_stats():
    return db.get_stats()


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "stats": db.get_stats(),
    })
