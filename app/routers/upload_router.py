"""Master file upload — preview and apply."""

from __future__ import annotations

import io
import json

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import html
import re

from starlette.concurrency import run_in_threadpool

from .. import db, excel_table, user_list_import
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
        return excel_table.rows_to_records(list(ws.iter_rows(values_only=True)))

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


# ---------------------------------------------------------------------------
# User list sheet — update the career stage of unique users (badge + institution)
# for the ESAFs from the sheet's period on; earlier ESAFs keep the stage they had.
# ---------------------------------------------------------------------------

_USERLIST_BUTTONS = (
    '<div class="mt-3 d-flex gap-2">'
    '<button class="btn btn-success btn-sm" hx-post="/upload/apply/userlist" '
    'hx-target="#preview-userlist" hx-swap="innerHTML"><i class="bi bi-check-lg me-1"></i>Apply {n} update(s)</button>'
    '<button class="btn btn-outline-secondary btn-sm" hx-post="/upload/cancel/userlist" '
    'hx-target="#preview-userlist" hx-swap="innerHTML">Cancel</button></div>'
)


@router.post("/upload/preview/userlist", response_class=HTMLResponse)
async def preview_userlist(request: Request, file: UploadFile = File(...),
                           sheet: str = Form(""), since: str = Form("")):
    redir = _require_admin(request)
    if redir:
        return redir
    data = await file.read()
    try:
        name, people = await run_in_threadpool(user_list_import.read_people, data, sheet.strip())
    except Exception as exc:
        return HTMLResponse(f'<div class="alert alert-danger">{html.escape(str(exc))}</div>')
    if not people:
        return HTMLResponse('<div class="alert alert-warning">No people found in that sheet.</div>')
    since = since.strip() or user_list_import.cycle_start(name)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
        return HTMLResponse('<div class="alert alert-warning">This sheet name is not a run cycle (like 2026-3), so '
                            'enter the date the list applies from (YYYY-MM-DD) in the "Applies from" box.</div>')

    matched = user_list_import.match(people, db.list_unique_users())
    cand = [m for m in matched if m["status"] == "matched" and m["employment_level"]]
    plans = db.preview_career_stage(
        [{"badge": m["badge"], "institution": m["matched_institution"], "employment_level": m["employment_level"]}
         for m in cand], since)
    for m, p in zip(cand, plans):
        m["plan"] = p
    _preview_cache[f"userlist:{get_session_user(request)['email']}"] = {"since": since, "matched": matched}

    def lst(title, items, limit=40):
        if not items:
            return ""
        li = "".join(f"<li>{html.escape(i)}</li>" for i in items[:limit])
        more = f"<li>… and {len(items) - limit} more</li>" if len(items) > limit else ""
        return f"<div class='mt-2'><strong>{title}</strong><ul class='mb-0'>{li}{more}</ul></div>"

    def label(m):
        return f'{m["first_name"]} {m["last_name"]} ({m["matched_institution"] or m["institution"] or "no institution"})'

    upd = [m for m in cand if m["plan"]["targets"]]
    same = [m for m in cand if m["plan"]["esafs"] and not m["plan"]["targets"]]
    none = [m for m in cand if not m["plan"]["esafs"]]
    new = [m for m in matched if m["status"] == "new"]
    amb = [m for m in matched if m["status"] == "ambiguous"]
    body = (
        f'<strong>Preview of sheet "{html.escape(name)}", applying to ESAFs from {since} on — nothing saved yet.</strong><br>'
        f'{len(people)} people: {len(upd)} to update, {len(same)} already correct, {len(none)} with no ESAF since that date, '
        f'{len(new)} not in the database, {len(amb)} ambiguous.'
        + lst(f"Career stage will change ({len(upd)}):",
              [f'{label(m)} badge {m["badge"]}: {", ".join(m["plan"]["old"]) or "(empty)"} → '
               f'{m["employment_level"]} on {len(m["plan"]["targets"])} ESAF(s)' for m in upd])
        + lst(f"⚠ Ambiguous — several users match, skipped ({len(amb)}):",
              [f'{label(m)} → {", ".join(m["matches"])}' for m in amb])
        + lst(f"No ESAF from {since} on — nothing to update ({len(none)}):", [label(m) for m in none])
        + lst(f"Not in the database — skipped ({len(new)}):", [label(m) for m in new])
        + '<div class="mt-2 text-muted small">A unique user is a badge at one institution. Only that user\'s ESAFs '
          'from the date above on are changed; earlier ESAFs keep the stage they had.</div>'
    )
    cls = "alert-warning" if amb else "alert-info"
    buttons = _USERLIST_BUTTONS.format(n=len(upd)) if upd else ""
    return HTMLResponse(f'<div class="alert {cls} small">{body}{buttons}</div>')


@router.post("/upload/apply/userlist", response_class=HTMLResponse)
async def apply_userlist(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    pending = _preview_cache.pop(f"userlist:{get_session_user(request)['email']}", None)
    if not pending:
        return HTMLResponse('<div class="alert alert-warning">No pending preview. Please re-upload.</div>')
    updates = [{"badge": m["badge"], "institution": m["matched_institution"], "employment_level": m["employment_level"]}
               for m in pending["matched"] if m.get("plan", {}).get("targets")]
    n = db.apply_career_stage(updates, pending["since"]) if updates else 0
    log_action(request, "import", "users", "",
               f"User list import: career stage updated for {n} users from {pending['since']}")
    return HTMLResponse(f'<div class="alert alert-success"><i class="bi bi-check-circle me-1"></i>'
                        f'Career stage updated for {n} user(s) from {pending["since"]} on.</div>')


@router.post("/upload/cancel/{import_type}", response_class=HTMLResponse)
def cancel_import(import_type: str, request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    user = get_session_user(request)
    if user:
        _preview_cache.pop(f"{import_type}:{user['email']}", None)
    return HTMLResponse('<div class="text-muted small">Import cancelled.</div>')
