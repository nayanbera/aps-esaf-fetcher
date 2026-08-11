"""ESAF list, detail, and edit endpoints (web UI + JSON API)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from typing import Annotated

from .. import config, db
from ..esaf_pdf_parser import parse_esaf_pdf
from ..templates_env import templates

log = logging.getLogger(__name__)

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

_PER_PAGE = 100


@router.get("/esafs", response_class=HTMLResponse)
def esafs_page(
    request: Request,
    year: str | None = None,
    beamline: str | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
):
    year_int = int(year) if year else None
    page     = max(1, page)
    offset   = (page - 1) * _PER_PAGE

    total       = db.count_esafs(year=year_int, beamline=beamline, status=status, search=search)
    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    page        = min(page, total_pages)
    offset      = (page - 1) * _PER_PAGE

    esafs = db.list_esafs(year=year_int, beamline=beamline, status=status,
                          search=search, limit=_PER_PAGE, offset=offset)
    opts  = db.get_filter_options()

    return templates.TemplateResponse("esafs.html", {
        "request": request, "esafs": esafs,
        "years": opts["years"], "beamlines": opts["beamlines"], "statuses": opts["statuses"],
        "filter_year": year_int, "filter_beamline": beamline,
        "filter_status": status, "filter_search": search or "",
        "page": page, "total_pages": total_pages,
        "total": total, "per_page": _PER_PAGE,
        "offset": offset,
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

@router.get("/api/pi-groups")
def api_list_pi_groups() -> list[str]:
    return db.list_pi_groups()


_VALID_TECHNIQUES = {"", "Surf", "Xtal", "ASWAXS"}


@router.post("/esafs/{esaf_id}/set-technique", response_class=HTMLResponse)
def set_esaf_technique(
    request: Request,
    esaf_id: str,
    technique: str = Form(""),
):
    technique = technique.strip()
    if technique not in _VALID_TECHNIQUES:
        raise HTTPException(400, f"Invalid technique '{technique}'")
    db.set_esaf_technique(esaf_id, technique)
    return templates.TemplateResponse(
        "partials/esaf_technique_select.html",
        {"request": request, "esaf_id": esaf_id, "technique": technique},
    )


@router.get("/esafs/{esaf_id}/edit", response_class=HTMLResponse)
def esaf_edit_form(request: Request, esaf_id: str):
    """Return an HTMX partial: the edit form for notes + custom fields."""
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    field_defs = db.list_field_definitions()
    pi_groups  = db.list_pi_groups()
    return templates.TemplateResponse("partials/esaf_edit_form.html", {
        "request": request, "esaf": esaf, "field_defs": field_defs,
        "pi_groups": pi_groups,
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
    notes    = str(form.get("notes", ""))
    pi_group = str(form.get("pi_group", "")).strip()

    field_defs  = db.list_field_definitions()
    custom_fields = dict(esaf.get("custom_fields") or {})
    for fd in field_defs:
        key = fd["name"]
        if key in form:
            custom_fields[key] = str(form[key])

    db.update_esaf_fields(esaf_id, notes, custom_fields, pi_group)

    # Return updated detail partial for HTMX swap
    esaf = db.get_esaf(esaf_id)
    return templates.TemplateResponse("partials/esaf_view.html", {
        "request": request, "esaf": esaf, "field_defs": field_defs,
    })


# ---------------------------------------------------------------------------
# ESAF PDF upload
# ---------------------------------------------------------------------------

@router.get("/esafs/{esaf_id}/pdf")
def view_esaf_pdf(esaf_id: str):
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    pdf_path = esaf.get("pdf_path", "")
    if not pdf_path or not Path(pdf_path).is_file():
        raise HTTPException(404, "No PDF stored for this ESAF")
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f"ESAF-{esaf_id}.pdf")


@router.post("/esafs/{esaf_id}/upload-pdf", response_class=HTMLResponse)
async def upload_esaf_pdf(request: Request, esaf_id: str, pdf_file: UploadFile = File(...)):
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    if not pdf_file.filename.lower().endswith(".pdf"):
        return HTMLResponse(
            '<div class="alert alert-danger">File must be a PDF.</div>', status_code=400
        )
    raw = await pdf_file.read()
    try:
        result = parse_esaf_pdf(raw)
    except Exception as exc:
        log.exception("ESAF PDF parse error for %s", esaf_id)
        return HTMLResponse(
            f'<div class="alert alert-danger">Parse error: {exc}</div>', status_code=422
        )

    extracted = result["extracted"]
    parsed_esaf_id = extracted.get("esaf_id", "").strip()
    if parsed_esaf_id and parsed_esaf_id != esaf_id:
        return HTMLResponse(
            f'<div class="alert alert-warning">PDF appears to be for ESAF '
            f'<strong>{parsed_esaf_id}</strong>, not <strong>{esaf_id}</strong>. '
            f"Upload aborted — upload the PDF on the correct ESAF page.</div>",
            status_code=422,
        )

    # Store PDF
    pdf_dir = Path(config.PDF_DIR) / "esafs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(pdf_dir / f"{esaf_id}.pdf")
    Path(pdf_path).write_bytes(raw)

    gup_id = extracted.get("gup_id", "").strip()
    db.update_esaf_pdf(esaf_id, gup_id, pdf_path)

    msg = f'PDF stored for ESAF <strong>{esaf_id}</strong>.'
    if gup_id:
        msg += f' GUP ID <strong>{gup_id}</strong> extracted.'
        # Check whether this GUP exists and propagate funding if so
        gup = db.get_gup(gup_id)
        if gup and gup.get("funding_sources"):
            from .gups import _propagate_funding
            _propagate_funding(gup_id, gup["funding_sources"])
            msg += " Funding sources propagated from linked GUP."
    return HTMLResponse(f'<div class="alert alert-success">{msg}</div>')


# ---------------------------------------------------------------------------
# ESAF bulk PDF import from folder
# ---------------------------------------------------------------------------

@router.post("/esafs/bulk-import-pdfs", response_class=HTMLResponse)
async def bulk_import_esaf_pdfs(request: Request, folder_path: str = Form(...)):
    folder = Path(folder_path.strip())
    if not folder.is_dir():
        return HTMLResponse(
            f'<div class="alert alert-danger">Folder not found: <code>{folder_path}</code></div>',
            status_code=422,
        )

    pdf_files = list(folder.glob("*.pdf")) + list(folder.glob("*.PDF"))
    if not pdf_files:
        return HTMLResponse(
            '<div class="alert alert-warning">No PDF files found in that folder.</div>'
        )

    pdf_dir = Path(config.PDF_DIR) / "esafs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    matched = skipped = errors_count = 0
    errors: list[str] = []

    for p in pdf_files:
        try:
            result = parse_esaf_pdf(str(p))
            esaf_id = result["extracted"].get("esaf_id", "").strip()
            if not esaf_id:
                skipped += 1
                continue
            esaf = db.get_esaf(esaf_id)
            if esaf is None:
                skipped += 1
                continue
            import shutil
            dest = str(pdf_dir / f"{esaf_id}.pdf")
            shutil.copy2(str(p), dest)
            gup_id = result["extracted"].get("gup_id", "").strip()
            db.update_esaf_pdf(esaf_id, gup_id, dest)
            matched += 1
        except Exception as exc:
            errors.append(f"{p.name}: {exc}")
            errors_count += 1
            log.exception("Error importing ESAF PDF %s", p)

    msg = (f"Processed {len(pdf_files)} files: {matched} matched and stored, "
           f"{skipped} skipped (no ESAF ID or not in DB).")
    if errors:
        err_html = "<ul>" + "".join(f"<li>{e}</li>" for e in errors) + "</ul>"
        return HTMLResponse(
            f'<div class="alert alert-warning">{msg}<br>Errors:{err_html}</div>'
        )
    return HTMLResponse(f'<div class="alert alert-success">{msg}</div>')
