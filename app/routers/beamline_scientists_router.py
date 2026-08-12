"""Beamline scientists management endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import db
from ..templates_env import templates

router = APIRouter()


@router.get("/beamline-scientists", response_class=HTMLResponse)
def scientists_page(request: Request):
    scientists = db.list_beamline_scientists()
    return templates.TemplateResponse("beamline_scientists.html", {
        "request":    request,
        "scientists": scientists,
    })


@router.post("/api/beamline-scientists")
async def add_scientist(request: Request):
    form = await request.form()
    badge = (form.get("badge") or "").strip()
    if not badge:
        return JSONResponse({"error": "badge required"}, status_code=400)
    ok = db.add_beamline_scientist(badge)
    if not ok:
        return JSONResponse({"error": f"Badge '{badge}' not found in users"}, status_code=404)
    scientists = db.list_beamline_scientists()
    return templates.TemplateResponse("partials/scientists_table.html", {
        "request":    request,
        "scientists": scientists,
    })


@router.delete("/api/beamline-scientists/{badge}")
def remove_scientist(badge: str, request: Request):
    db.remove_beamline_scientist(badge)
    scientists = db.list_beamline_scientists()
    return templates.TemplateResponse("partials/scientists_table.html", {
        "request":    request,
        "scientists": scientists,
    })
