"""ESAF list, detail, and edit endpoints (web UI + JSON API)."""

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Annotated

from .. import db
from ..templates_env import templates

router = APIRouter()


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@router.get("/api/esafs")
def api_list_esafs(
    year: str | None = None,
    beamline: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
):
    year_int = int(year) if year else None
    return db.list_esafs(year=year_int, beamline=beamline, status=status,
                         search=search, limit=limit, offset=offset)


@router.get("/api/esafs/{esaf_id}")
def api_get_esaf(esaf_id: str):
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    return esaf


# ---------------------------------------------------------------------------
# Web UI — list
# ---------------------------------------------------------------------------

@router.get("/esafs", response_class=HTMLResponse)
def esafs_page(
    request: Request,
    year: str | None = None,
    beamline: str | None = None,
    status: str | None = None,
    search: str | None = None,
):
    year_int = int(year) if year else None
    esafs = db.list_esafs(year=year_int, beamline=beamline, status=status, search=search)
    opts  = db.get_filter_options()

    return templates.TemplateResponse("esafs.html", {
        "request": request, "esafs": esafs,
        "years": opts["years"], "beamlines": opts["beamlines"], "statuses": opts["statuses"],
        "filter_year": year_int, "filter_beamline": beamline,
        "filter_status": status, "filter_search": search or "",
    })


# ---------------------------------------------------------------------------
# Web UI — detail
# ---------------------------------------------------------------------------

@router.get("/esafs/{esaf_id}", response_class=HTMLResponse)
def esaf_detail(request: Request, esaf_id: str):
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    field_defs = db.list_field_definitions()
    return templates.TemplateResponse("esaf_detail.html", {
        "request": request, "esaf": esaf, "field_defs": field_defs,
    })


# ---------------------------------------------------------------------------
# Web UI — inline edit (HTMX)
# ---------------------------------------------------------------------------

@router.get("/esafs/{esaf_id}/edit", response_class=HTMLResponse)
def esaf_edit_form(request: Request, esaf_id: str):
    """Return an HTMX partial: the edit form for notes + custom fields."""
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    field_defs = db.list_field_definitions()
    return templates.TemplateResponse("partials/esaf_edit_form.html", {
        "request": request, "esaf": esaf, "field_defs": field_defs,
    })


@router.get("/esafs/{esaf_id}/edit-cancel", response_class=HTMLResponse)
def esaf_edit_cancel(request: Request, esaf_id: str):
    """Restore the read-only view without saving."""
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    field_defs = db.list_field_definitions()
    return templates.TemplateResponse("partials/esaf_view.html", {
        "request": request, "esaf": esaf, "field_defs": field_defs,
    })


@router.put("/esafs/{esaf_id}", response_class=HTMLResponse)
async def esaf_save(request: Request, esaf_id: str):
    """Save notes + custom fields from HTMX form submission."""
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")

    form = await request.form()
    notes = str(form.get("notes", ""))

    field_defs  = db.list_field_definitions()
    custom_fields = dict(esaf.get("custom_fields") or {})
    for fd in field_defs:
        key = fd["name"]
        if key in form:
            custom_fields[key] = str(form[key])

    db.update_esaf_fields(esaf_id, notes, custom_fields)

    # Return updated detail partial for HTMX swap
    esaf = db.get_esaf(esaf_id)
    return templates.TemplateResponse("partials/esaf_view.html", {
        "request": request, "esaf": esaf, "field_defs": field_defs,
    })
