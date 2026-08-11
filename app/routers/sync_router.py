"""Sync control endpoints."""

import threading
from datetime import datetime
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from typing import Annotated, Optional

from .. import db, sync
from ..templates_env import templates

router = APIRouter()

_sync_running = False
_last_result: dict | None = None

_CURRENT_YEAR = datetime.now().year
_YEAR_CHOICES = list(range(_CURRENT_YEAR, 2009, -1))   # 2025 … 2010


def _years_from_range(from_year: Optional[int], to_year: Optional[int]) -> list[str] | None:
    """Return a list of year strings for [from_year, to_year], or None to use config default."""
    if from_year is None and to_year is None:
        return None
    fy = from_year or _CURRENT_YEAR
    ty = to_year   or _CURRENT_YEAR
    if fy > ty:
        fy, ty = ty, fy
    return [str(y) for y in range(fy, ty + 1)]


@router.get("/api/sync/status")
def api_sync_status():
    return {"running": _sync_running, "last_sync": db.get_last_sync()}


@router.post("/api/sync/trigger")
def api_trigger_sync(
    from_year: Optional[int] = None,
    to_year:   Optional[int] = None,
):
    _trigger(_years_from_range(from_year, to_year))
    return {"status": "started"}


def _sync_context():
    return {
        "last_sync":    db.get_last_sync(),
        "running":      _sync_running,
        "last_result":  _last_result,
        "year_choices": _YEAR_CHOICES,
        "current_year": _CURRENT_YEAR,
    }


@router.get("/sync", response_class=HTMLResponse)
def sync_page(request: Request):
    return templates.TemplateResponse("sync.html", {"request": request, **_sync_context()})


@router.post("/sync/trigger", response_class=HTMLResponse)
def web_trigger_sync(
    request:   Request,
    from_year: Annotated[Optional[int], Form()] = None,
    to_year:   Annotated[Optional[int], Form()] = None,
):
    _trigger(_years_from_range(from_year, to_year))
    return templates.TemplateResponse("partials/sync_status.html",
                                      {"request": request, **_sync_context()})


@router.get("/sync/status", response_class=HTMLResponse)
def web_sync_status(request: Request):
    """HTMX polling target — returns updated status partial."""
    return templates.TemplateResponse("partials/sync_status.html",
                                      {"request": request, **_sync_context()})


def _trigger(years: list[str] | None = None):
    global _sync_running, _last_result
    if _sync_running:
        return

    def _run():
        global _sync_running, _last_result
        _sync_running = True
        try:
            _last_result = sync.run_sync(years=years)
        finally:
            _sync_running = False

    threading.Thread(target=_run, daemon=True).start()
