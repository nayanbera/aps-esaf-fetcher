"""ESAF list, detail, and edit endpoints (web UI + JSON API)."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from typing import Annotated

from .. import config, db, esaf_import, esaf_matching, gup_import, gup_linking, instruments
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
        "import_cfg": {k: v for k, v in esaf_import.load_settings().items() if k != "manifest"},
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
        "request": request, "esaf": esaf, "field_defs": field_defs, **_instrument_context(esaf),
    })


def _instrument_context(esaf: dict) -> dict:
    """The linked GUP's instrument rows and the technique they imply, for the ESAF page."""
    gup = db.get_gup(esaf["gup_id"]) if esaf.get("gup_id") else None
    etr = (gup or {}).get("etr") or []
    tech, why = instruments.suggest(esaf.get("start_date", ""), etr) if etr else ("", "")
    cyc = esaf_matching.run_cycle(esaf.get("start_date"))
    rows = [dict(r, technique_code=instruments.technique_of(r.get("instrument", "")), this_cycle=bool(cyc and r.get("run_cycle") == cyc))
            for r in etr]
    return {"etr_rows": rows, "etr_gup": esaf.get("gup_id") or "", "etr_suggested": tech, "etr_why": why}


# ---------------------------------------------------------------------------
# Web UI — inline edit (HTMX)
# ---------------------------------------------------------------------------

@router.get("/api/pi-groups")
def api_list_pi_groups() -> list[str]:
    return db.list_pi_groups()


_VALID_TECHNIQUES = {"", "Surf", "Xtal", "ASWAXS", "Beamline"}


@router.post("/esafs/sync-funding", response_class=HTMLResponse)
def sync_funding_all():
    """Link ESAFs to their GUP through sibling ESAFs where unambiguous, then give ESAFs with no
    funding the funding of their linked GUP.  ESAFs that already have funding are left alone."""
    from ..gup_inference import fill_gup_from_siblings
    linked, _details = fill_gup_from_siblings()
    by_pi = gup_linking.link_esafs_to_gups(apply=True)
    r = gup_import.fill_funding_from_gups(apply=True)
    t = gup_import.update_techniques(apply=True)
    parts = [f"{len(by_pi['sure'])} ESAF(s) linked to a GUP (same PI and title)"]
    if by_pi["likely"]:
        parts.append(f"{len(by_pi['likely'])} more look like a match by PI and run cycle only: run link_esafs_to_gups.py to review them")
    parts.append(f"{len(r['restore'])} ESAF(s) got funding from their GUP")
    parts.append(f"technique from the GUP's 15-ID instrument: {len(t['set'])} ESAF(s) set, {t['same']} already match")
    if t["differs"]:
        parts.append(f"{len(t['differs'])} ESAF(s) have a technique set by hand that differs from the instrument (left as is)")
    if t["unclear"]:
        parts.append(f"{t['unclear']} ESAF(s) left alone: their GUP lists no single 15-ID instrument")
    g = t["gups"]
    parts.append(f"GUP technique: {len(g['set'])} set, {g['same']} already match"
                 + (f", {len(g['differs'])} set by hand differ" if g["differs"] else ""))
    if linked:
        parts.append(linked)
    left = sum(map(len, r["no_gup_data"].values()))
    if left:
        parts.append(f"{left} ESAF(s) have a GUP with no funding data (upload that GUP's PDF)")
    if r["no_link"]:
        parts.append(f"{len(r['no_link'])} ESAF(s) have no funding and no GUP link")
    return HTMLResponse('<span class="text-success small"><i class="bi bi-check-lg me-1"></i>'
                        + html.escape("; ".join(parts)) + ".</span>")


@router.post("/esafs/{esaf_id}/apply-instrument-technique")
def apply_instrument_technique(esaf_id: str):
    """Set the technique the GUP's instrument implies (replaces a technique set by hand) and reload the page."""
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    gup = db.get_gup(esaf["gup_id"]) if esaf.get("gup_id") else None
    tech, _why = instruments.suggest(esaf.get("start_date", ""), (gup or {}).get("etr") or [])
    if not tech:
        raise HTTPException(409, "No technique can be derived from the GUP's instruments")
    db.set_esaf_technique(esaf_id, tech, "instrument")
    return HTMLResponse("", headers={"HX-Refresh": "true"})


@router.post("/esafs/{esaf_id}/sync-funding", response_class=HTMLResponse)
def sync_funding(request: Request, esaf_id: str):
    """Copy the linked GUP's funding sources onto this ESAF (replaces the ESAF's current list)."""
    esaf = db.get_esaf(esaf_id)
    if esaf is None:
        raise HTTPException(404, "ESAF not found")
    gup = db.get_gup(esaf.get("gup_id") or "") if esaf.get("gup_id") else None
    labels = gup_import.funding_labels((gup or {}).get("funding_sources") or [])
    note = ""
    if not esaf.get("gup_id"):
        note = "This ESAF is not linked to a GUP."
    elif gup is None:
        note = f"GUP {esaf['gup_id']} has not been imported yet."
    elif not labels:
        note = f"GUP {esaf['gup_id']} has no funding sources recorded (upload its PDF)."
    else:
        db.set_esaf_funding(esaf_id, labels)
        esaf = db.get_esaf(esaf_id)
        note = f"Copied {len(labels)} funding source(s) from GUP {esaf['gup_id']}."
    return templates.TemplateResponse("partials/esaf_funding.html",
                                      {"request": request, "esaf": esaf, "note": note})


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
    if technique:
        esaf = db.get_esaf(esaf_id)
        pi_group = (esaf or {}).get("pi_group", "")
        if pi_group:
            db.add_pi_group_technique(pi_group, technique)
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
        gup_import.update_techniques({gup_id})
    return HTMLResponse(f'<div class="alert alert-success">{msg}</div>')


# ---------------------------------------------------------------------------
# ESAF bulk PDF import from folder
# ---------------------------------------------------------------------------

@router.post("/esafs/bulk-import-pdfs", response_class=HTMLResponse)
async def bulk_import_esaf_pdfs(
    request: Request,
    folder_path: str = Form(...),
    recursive: str = Form(""),
    interval_hrs: int = Form(0),
    force: str = Form(""),
):
    """Import ESAF PDFs from a server folder and remember it as the watched folder.

    PDFs are read in place and never modified; the DB stores their original path.
    """
    folder = str(Path(folder_path.strip()).expanduser())
    if not Path(folder).is_dir():
        return HTMLResponse(
            f'<div class="alert alert-danger">Folder not found: <code>{html.escape(folder)}</code></div>',
            status_code=422,
        )
    try:
        esaf_import.configure(folder, bool(recursive), interval_hrs)
    except ValueError as exc:
        return HTMLResponse(f'<div class="alert alert-danger">{html.escape(str(exc))}</div>', status_code=422)
    try:
        counts = await run_in_threadpool(
            esaf_import.import_folder, folder, bool(recursive), bool(force))
    except RuntimeError as exc:
        return HTMLResponse(f'<div class="alert alert-warning">{html.escape(str(exc))}</div>')
    return HTMLResponse(esaf_import.format_result(counts))
