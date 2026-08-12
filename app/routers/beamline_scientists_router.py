"""Beamline scientists management endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import db
from ..templates_env import templates

router = APIRouter()


@router.get("/api/beamline-scientists/search", response_class=HTMLResponse)
def search_users(q: str = "", request: Request = None):
    """Return an HTML suggestion list for the user-search autocomplete."""
    if not q or len(q) < 2:
        return HTMLResponse("")
    users = db.list_users_for_lookup(q)
    # Build a simple <ul> of matches
    items = ""
    for u in users[:20]:
        name = f"{u['first_name']} {u['last_name']}".strip()
        items += (
            f'<li class="list-group-item list-group-item-action py-1 px-2 suggestion-item" '
            f'data-badge="{u["badge"]}" data-name="{name}" '
            f'style="cursor:pointer">'
            f'<span class="fw-semibold">{name}</span> '
            f'<span class="text-muted small">#{u["badge"]}</span>'
            f'{(" — " + u["institution"]) if u.get("institution") else ""}'
            f'</li>'
        )
    if not items:
        items = '<li class="list-group-item py-1 px-2 text-muted fst-italic small">No matches</li>'
    return HTMLResponse(f'<ul class="list-group shadow-sm">{items}</ul>')


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


@router.put("/api/beamline-scientists/{badge}")
async def update_scientist(badge: str, request: Request):
    form = await request.form()
    start_date = (form.get("start_date") or "").strip()
    db.update_beamline_scientist(badge, start_date)
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
