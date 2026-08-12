"""Master file upload — preview and apply."""

from __future__ import annotations

import io
import json

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import db
from ..auth import get_session_user, log_action
from ..templates_env import templates

router = APIRouter()

# In-memory preview store keyed by session (simple enough for single-user admin)
_preview_cache: dict[str, list[dict]] = {}


def _require_admin(request: Request):
    if get_session_user(request):
        return None
    return RedirectResponse("/admin/login", status_code=303)


def _parse_file(upload: UploadFile) -> list[dict]:
    """Parse CSV or Excel upload into a list of dicts."""
    name = (upload.filename or "").lower()
    data = upload.file.read()

    if name.endswith(".csv"):
        import csv
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        return [dict(r) for r in reader]

    if name.endswith((".xlsx", ".xls")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(c).strip() if c is not None else "" for c in rows[0]]
        result = []
        for row in rows[1:]:
            result.append({h: (str(v).strip() if v is not None else "") for h, v in zip(headers, row)})
        return result

    raise ValueError(f"Unsupported file type: {upload.filename}")


# ---------------------------------------------------------------------------
# Upload page
# ---------------------------------------------------------------------------

@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "current_admin": get_session_user(request),
    })


# ---------------------------------------------------------------------------
# Preview endpoints
# ---------------------------------------------------------------------------

@router.post("/upload/preview/users", response_class=HTMLResponse)
async def preview_users(request: Request, file: UploadFile = File(...)):
    redir = _require_admin(request)
    if redir:
        return redir

    try:
        records = _parse_file(file)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="alert alert-danger">Parse error: {exc}</div>'
        )

    if not records:
        return HTMLResponse('<div class="alert alert-warning">File is empty.</div>')

    diffs = db.preview_user_import(records)
    session_key = get_session_user(request)["email"]
    _preview_cache[f"users:{session_key}"] = records

    return templates.TemplateResponse("partials/import_preview.html", {
        "request": request,
        "diffs": diffs,
        "import_type": "users",
        "total": len(records),
    })


@router.post("/upload/preview/esafs", response_class=HTMLResponse)
async def preview_esafs(request: Request, file: UploadFile = File(...)):
    redir = _require_admin(request)
    if redir:
        return redir

    try:
        records = _parse_file(file)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="alert alert-danger">Parse error: {exc}</div>'
        )

    if not records:
        return HTMLResponse('<div class="alert alert-warning">File is empty.</div>')

    diffs = db.preview_esaf_import(records)
    session_key = get_session_user(request)["email"]
    _preview_cache[f"esafs:{session_key}"] = records

    return templates.TemplateResponse("partials/import_preview.html", {
        "request": request,
        "diffs": diffs,
        "import_type": "esafs",
        "total": len(records),
    })


# ---------------------------------------------------------------------------
# Apply endpoints
# ---------------------------------------------------------------------------

@router.post("/upload/apply/users", response_class=HTMLResponse)
async def apply_users(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir

    session_key = get_session_user(request)["email"]
    records = _preview_cache.pop(f"users:{session_key}", None)
    if not records:
        return HTMLResponse('<div class="alert alert-warning">No pending preview. Please re-upload.</div>')

    n = db.apply_user_import(records)
    log_action(request, "import", "users", "", f"Master file import: {n} user records applied")
    return HTMLResponse(
        f'<div class="alert alert-success"><i class="bi bi-check-circle me-1"></i>'
        f'Applied {n} user record(s) from master file.</div>'
    )


@router.post("/upload/apply/esafs", response_class=HTMLResponse)
async def apply_esafs(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir

    session_key = get_session_user(request)["email"]
    records = _preview_cache.pop(f"esafs:{session_key}", None)
    if not records:
        return HTMLResponse('<div class="alert alert-warning">No pending preview. Please re-upload.</div>')

    n = db.apply_esaf_import(records)
    log_action(request, "import", "esafs", "", f"Master file import: {n} ESAF records applied")
    return HTMLResponse(
        f'<div class="alert alert-success"><i class="bi bi-check-circle me-1"></i>'
        f'Applied {n} ESAF record(s) from master file.</div>'
    )


@router.post("/upload/cancel/{import_type}", response_class=HTMLResponse)
def cancel_import(import_type: str, request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    user = get_session_user(request)
    if user:
        _preview_cache.pop(f"{import_type}:{user['email']}", None)
    return HTMLResponse('<div class="text-muted small">Import cancelled.</div>')
