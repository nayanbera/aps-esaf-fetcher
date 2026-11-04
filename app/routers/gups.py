"""GUP (General User Proposal) endpoints."""

from __future__ import annotations

import html
import json
import logging
import os
from urllib.parse import quote
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import config, db, gup_import
from ..gup_pdf_parser import parse_gup_pdf
from ..templates_env import templates

router = APIRouter()
log = logging.getLogger(__name__)

_PER_PAGE = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gup_pdf_dir() -> Path:
    p = Path(config.PDF_DIR) / "gups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _esaf_pdf_dir() -> Path:
    p = Path(config.PDF_DIR) / "esafs"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# GUP list page
# ---------------------------------------------------------------------------

@router.get("/gups", response_class=HTMLResponse)
def gups_page(
    request: Request,
    search: str | None = None,
    run_cycle: str | None = None,
    page: int = 1,
):
    page   = max(1, page)
    offset = (page - 1) * _PER_PAGE
    total  = db.count_gups(search=search, run_cycle=run_cycle)
    pages  = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    gups   = db.list_gups(search=search, run_cycle=run_cycle, limit=_PER_PAGE, offset=offset)
    cycles = db.get_gup_run_cycles()
    return templates.TemplateResponse("gups.html", {
        "request":    request,
        "gups":       gups,
        "total":      total,
        "page":       page,
        "pages":      pages,
        "search":     search or "",
        "run_cycle":  run_cycle or "",
        "run_cycles": cycles,
        "import_cfg": {k: v for k, v in gup_import.load_settings().items() if k != "manifest"},
    })


_VALID_TECHNIQUES = {"", "Surf", "Xtal", "ASWAXS", "Beamline"}


@router.post("/gups/{gup_id}/set-technique", response_class=HTMLResponse)
def set_gup_technique(
    request: Request,
    gup_id: str,
    technique: str = Form(""),
):
    technique = technique.strip()
    if technique not in _VALID_TECHNIQUES:
        raise HTTPException(400, f"Invalid technique '{technique}'")
    db.set_gup_technique(gup_id, technique)
    post_url = f"/gups/{gup_id}/set-technique"
    return templates.TemplateResponse(
        "partials/technique_select.html",
        {"request": request, "technique": technique, "post_url": post_url},
    )


# ---------------------------------------------------------------------------
# GUP detail page
# ---------------------------------------------------------------------------

@router.get("/gups/{gup_id}", response_class=HTMLResponse)
def gup_detail(request: Request, gup_id: str):
    gup = db.get_gup(gup_id)
    if gup is None:
        raise HTTPException(404, f"GUP {gup_id} not found")
    linked_esafs = db.get_esafs_for_gup(gup_id)
    return templates.TemplateResponse("gup_detail.html", {
        "request":      request,
        "gup":          gup,
        "linked_esafs": linked_esafs,
    })


# ---------------------------------------------------------------------------
# Upload a single GUP PDF
# ---------------------------------------------------------------------------

@router.post("/gups/upload", response_class=HTMLResponse)
async def upload_gup_pdf(request: Request, pdf_file: UploadFile = File(...)):
    if not pdf_file.filename.lower().endswith(".pdf"):
        return HTMLResponse(
            '<div class="alert alert-danger">File must be a PDF.</div>', status_code=400
        )
    raw = await pdf_file.read()
    try:
        result = parse_gup_pdf(raw)
    except Exception as exc:
        log.exception("GUP PDF parse error")
        return HTMLResponse(
            f'<div class="alert alert-danger">Parse error: {exc}</div>', status_code=422
        )

    extracted = result["extracted"]
    gup_id = extracted.get("gup_id", "").strip()
    if not gup_id:
        return HTMLResponse(
            '<div class="alert alert-warning">Could not extract GUP ID from PDF. '
            "Check the file is an APS GUP PDF.</div>",
            status_code=422,
        )

    # Store PDF
    pdf_path = str(_gup_pdf_dir() / f"{gup_id}.pdf")
    Path(pdf_path).write_bytes(raw)

    data = gup_import.build_gup_data(result, pdf_path)
    now = _now_iso()
    action = db.upsert_gup(data, now)
    _propagate_funding(gup_id, result.get("funding_sources", []))

    verb = "Added" if action == "added" else "Updated"
    return HTMLResponse(
        f'<div class="alert alert-success">{verb} GUP <strong>{gup_id}</strong> — '
        f'<a href="/gups/{gup_id}">View details</a></div>'
    )


# ---------------------------------------------------------------------------
# Bulk import GUPs from a server-side folder
# ---------------------------------------------------------------------------

@router.post("/gups/import", response_class=HTMLResponse)
async def bulk_import_gups(
    request: Request,
    folder_path: str = Form(...),
    recursive: str = Form(""),
    interval_hrs: int = Form(0),
    force: str = Form(""),
):
    """Import GUP PDFs from a server folder and remember it as the watched folder."""
    folder = str(Path(folder_path.strip()).expanduser())
    if not Path(folder).is_dir():
        return HTMLResponse(
            f'<div class="alert alert-danger">Folder not found: <code>{html.escape(folder)}</code></div>',
            status_code=422,
        )
    try:
        gup_import.configure(folder, bool(recursive), interval_hrs)
    except ValueError as exc:
        return HTMLResponse(f'<div class="alert alert-danger">{html.escape(str(exc))}</div>', status_code=422)
    try:
        counts = await run_in_threadpool(
            gup_import.import_folder, folder, bool(recursive), bool(force))
    except RuntimeError as exc:
        return HTMLResponse(f'<div class="alert alert-warning">{html.escape(str(exc))}</div>')
    return HTMLResponse(gup_import.format_result(counts))


# ---------------------------------------------------------------------------
# Server-side folder browser (for choosing the import folder)
# ---------------------------------------------------------------------------

@router.get("/gups/browse", response_class=HTMLResponse)
def browse_folders(folder_path: str = ""):
    """Return an HTML fragment listing the sub-folders of *folder_path*."""
    p = Path(folder_path.strip() or gup_import.load_settings()["folder"] or "~").expanduser()
    while not p.is_dir() and p != p.parent:  # climb to the nearest existing folder
        p = p.parent
    p = p.resolve()

    error = ""
    subdirs: list[Path] = []
    try:
        subdirs = sorted(
            (c for c in p.iterdir() if not c.name.startswith(".") and c.is_dir()),
            key=lambda c: c.name.lower(),
        )
    except OSError as exc:
        error = f"Cannot read folder: {exc.strerror or exc}"
    try:
        n_pdfs = sum(1 for c in p.iterdir() if c.suffix.lower() == ".pdf" and c.is_file())
    except OSError:
        n_pdfs = 0

    def nav(target: Path, label: str, icon: str = "bi-folder") -> str:
        return (
            f'<a href="#" class="list-group-item list-group-item-action py-1" '
            f'hx-get="/gups/browse?folder_path={quote(str(target))}" '
            f'hx-target="#gup-browse-body" hx-swap="innerHTML">'
            f'<i class="bi {icon} me-2"></i>{html.escape(label)}</a>'
        )

    esc = html.escape(str(p), quote=True)
    parts = [
        f'<div class="d-flex align-items-center gap-2 mb-2">'
        f'<code class="flex-grow-1 text-break">{html.escape(str(p))}</code>'
        f'<span class="text-muted small text-nowrap">{n_pdfs} PDF(s) here</span>'
        f'<button type="button" class="btn btn-primary btn-sm text-nowrap" data-select-path="{esc}">'
        f'<i class="bi bi-check-lg me-1"></i>Select this folder</button></div>',
    ]
    if error:
        parts.append(f'<div class="alert alert-warning py-1 small">{html.escape(error)}</div>')
    parts.append('<div class="list-group" style="max-height:50vh;overflow:auto">')
    if p != p.parent:
        parts.append(nav(p.parent, "..  (parent folder)", "bi-arrow-up"))
    parts.extend(nav(c, c.name) for c in subdirs)
    if not subdirs and not error:
        parts.append('<div class="list-group-item text-muted small">No sub-folders</div>')
    parts.append("</div>")
    return HTMLResponse("".join(parts))


# ---------------------------------------------------------------------------
# Serve stored GUP PDF
# ---------------------------------------------------------------------------

@router.get("/gups/{gup_id}/pdf")
def view_gup_pdf(gup_id: str):
    gup = db.get_gup(gup_id)
    if gup is None:
        raise HTTPException(404, f"GUP {gup_id} not found")
    pdf_path = gup.get("pdf_path", "")
    if not pdf_path or not Path(pdf_path).is_file():
        raise HTTPException(404, "No PDF stored for this GUP")
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f"GUP-{gup_id}.pdf")


# ---------------------------------------------------------------------------
# Re-propagate funding sources to linked ESAFs
# ---------------------------------------------------------------------------

@router.post("/gups/{gup_id}/propagate-funding", response_class=HTMLResponse)
def propagate_funding(gup_id: str):
    gup = db.get_gup(gup_id)
    if gup is None:
        raise HTTPException(404, f"GUP {gup_id} not found")
    funding_sources = gup.get("funding_sources") or []
    if not funding_sources:
        return HTMLResponse(
            '<span class="text-warning"><i class="bi bi-exclamation-triangle me-1"></i>'
            "No funding sources on this GUP to propagate.</span>"
        )
    _propagate_funding(gup_id, funding_sources)
    count = gup.get("linked_esaf_count", 0)
    return HTMLResponse(
        f'<span class="text-success"><i class="bi bi-check-lg me-1"></i>'
        f"Propagated {len(funding_sources)} source(s) to {count} linked ESAF(s).</span>"
    )


# ---------------------------------------------------------------------------
# Delete GUP
# ---------------------------------------------------------------------------

@router.delete("/gups/{gup_id}")
def delete_gup(gup_id: str):
    gup = db.get_gup(gup_id)
    # Only remove PDFs we stored ourselves; files in a watched folder are the user's.
    if gup and gup.get("pdf_path") and gup_import.is_managed_pdf(gup["pdf_path"]):
        try:
            Path(gup["pdf_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    found = db.delete_gup(gup_id)
    if not found:
        raise HTTPException(404, f"GUP {gup_id} not found")
    return JSONResponse({"deleted": gup_id})


# ---------------------------------------------------------------------------
# Helper: propagate funding sources to linked ESAFs
# ---------------------------------------------------------------------------

_propagate_funding = gup_import.propagate_funding
