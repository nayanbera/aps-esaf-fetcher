"""Sync control endpoints."""

import threading
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import db, sync
from ..templates_env import templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_sync_running = False
_last_result: dict | None = None


@router.get("/api/sync/status")
def api_sync_status():
    return {"running": _sync_running, "last_sync": db.get_last_sync()}


@router.post("/api/sync/trigger")
def api_trigger_sync():
    _trigger()
    return {"status": "started"}


@router.get("/sync", response_class=HTMLResponse)
def sync_page(request: Request):
    return templates.TemplateResponse("sync.html", {
        "request": request,
        "last_sync": db.get_last_sync(),
        "running": _sync_running,
        "last_result": _last_result,
    })


@router.post("/sync/trigger", response_class=HTMLResponse)
def web_trigger_sync(request: Request):
    _trigger()
    return templates.TemplateResponse("partials/sync_status.html", {
        "request": request,
        "last_sync": db.get_last_sync(),
        "running": _sync_running,
        "last_result": _last_result,
    })


@router.get("/sync/status", response_class=HTMLResponse)
def web_sync_status(request: Request):
    """HTMX polling target — returns updated status partial."""
    return templates.TemplateResponse("partials/sync_status.html", {
        "request": request,
        "last_sync": db.get_last_sync(),
        "running": _sync_running,
        "last_result": _last_result,
    })


def _trigger():
    global _sync_running, _last_result
    if _sync_running:
        return

    def _run():
        global _sync_running, _last_result
        _sync_running = True
        try:
            _last_result = sync.run_sync()
        finally:
            _sync_running = False

    threading.Thread(target=_run, daemon=True).start()
