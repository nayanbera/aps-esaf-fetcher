"""Institution ROR classification endpoints."""

from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import db
from ..ror_client import lookup_institution, type_badge_class
from ..templates_env import templates

router = APIRouter()
log = logging.getLogger(__name__)

_lock = threading.Lock()
_progress: dict = {"running": False, "total": 0, "done": 0, "errors": 0}


def _run_bulk_lookup() -> None:
    global _progress
    rows = db.list_institution_ror()
    pending = [r for r in rows if r["status"] == "pending"]
    _progress = {"running": True, "total": len(pending), "done": 0, "errors": 0}
    log.info("ROR bulk lookup: %d institutions pending", len(pending))
    for row in pending:
        result = lookup_institution(row["name"])
        db.upsert_institution_ror(row["name"], result)
        _progress["done"] += 1
        if result["status"] == "error":
            _progress["errors"] += 1
        time.sleep(0.15)
    _progress["running"] = False
    log.info("ROR lookup done: %d/%d, %d errors",
             _progress["done"], _progress["total"], _progress["errors"])


@router.get("/institutions", response_class=HTMLResponse)
def institutions_page(request: Request):
    db.sync_institution_names()
    rows = db.list_institution_ror()
    return templates.TemplateResponse("institutions.html", {
        "request":         request,
        "rows":            rows,
        "progress":        _progress,
        "type_badge_class": type_badge_class,
    })


@router.post("/institutions/lookup-ror", response_class=HTMLResponse)
def start_bulk_lookup(background_tasks: BackgroundTasks):
    global _progress
    db.sync_institution_names()
    with _lock:
        if _progress.get("running"):
            done = _progress["done"]
            total = _progress["total"]
            return HTMLResponse(
                f'<div class="alert alert-info">'
                f'<i class="bi bi-hourglass-split me-1"></i>'
                f'Lookup already running ({done}/{total})…</div>'
            )
        _progress = {"running": True, "total": 0, "done": 0, "errors": 0}
    background_tasks.add_task(_run_bulk_lookup)
    pending = sum(1 for r in db.list_institution_ror() if r["status"] == "pending")
    return HTMLResponse(
        f'<div class="alert alert-success">'
        f'<i class="bi bi-hourglass-split me-1"></i>'
        f'ROR lookup started for <strong>{pending}</strong> institution(s). '
        f'Refresh the page in a few seconds to see results.</div>'
    )


@router.get("/institutions/progress")
def lookup_progress():
    return JSONResponse(_progress)


@router.post("/institutions/lookup-one", response_class=HTMLResponse)
def lookup_one(request: Request, name: str = Form(...)):
    result = lookup_institution(name)
    db.upsert_institution_ror(name, result)
    row = next((r for r in db.list_institution_ror() if r["name"] == name), {
        "name": name, "ror_id": "", "ror_name": "", "org_types": [],
        "country": "", "website": "", "score": 0.0,
        "status": result.get("status", "error"), "looked_up_at": "",
    })
    return templates.TemplateResponse("partials/ror_row.html", {
        "request":         request,
        "row":             row,
        "type_badge_class": type_badge_class,
    })
