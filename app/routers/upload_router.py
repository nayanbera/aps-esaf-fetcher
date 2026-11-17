"""Master file upload — preview and apply."""

from __future__ import annotations

import io
import json

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

import html
import re
from datetime import datetime, timezone

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
# User list (sheet of names / e-mails / roles, no badge) — preview and apply
# ---------------------------------------------------------------------------

def _roster_id(p: dict) -> str:
    key = p.get("email") or f'{p["last_name"]}-{p["first_name"]}'
    return re.sub(r"[^a-z0-9@.]+", "-", key.lower()).strip("-")


_USERLIST_BUTTONS = (
    '<div class="mt-3 d-flex gap-2">'
    '<button class="btn btn-success btn-sm" hx-post="/upload/apply/userlist" '
    'hx-target="#preview-userlist" hx-swap="innerHTML"><i class="bi bi-check-lg me-1"></i>Apply</button>'
    '<button class="btn btn-outline-secondary btn-sm" hx-post="/upload/cancel/userlist" '
    'hx-target="#preview-userlist" hx-swap="innerHTML">Cancel</button></div>'
)


@router.post("/upload/preview/userlist", response_class=HTMLResponse)
async def preview_userlist(request: Request, file: UploadFile = File(...), sheet: str = Form("")):
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
    matched = user_list_import.match(people, db.list_users_for_lookup("", 100000))
    for m in matched:
        m["sheet"] = name
    _preview_cache[f"userlist:{get_session_user(request)['email']}"] = matched

    def lst(title, items, limit=40):
        if not items:
            return ""
        li = "".join(f"<li>{html.escape(i)}</li>" for i in items[:limit])
        more = f"<li>… and {len(items) - limit} more</li>" if len(items) > limit else ""
        return f"<div class='mt-2'><strong>{title}</strong><ul class='mb-0'>{li}{more}</ul></div>"

    def label(m):
        return f'{m["first_name"]} {m["last_name"]} ({m["institution"] or "no institution"})'

    new = [m for m in matched if m["status"] == "new"]
    amb = [m for m in matched if m["status"] == "ambiguous"]
    mat = [m for m in matched if m["status"] == "matched"]
    fills = [f'{label(m)} badge {m["badge"]}: ' + ", ".join(f"{k} = {v}" for k, v in m["fills"].items())
             for m in mat if m["fills"]]
    body = (
        f'<strong>Preview of sheet "{html.escape(name)}" — nothing saved yet.</strong><br>'
        f'{len(people)} people: {len(mat)} already in the database, {len(new)} new, {len(amb)} ambiguous.'
        + lst(f"Empty fields that will be filled for existing users ({len(fills)}):", fills)
        + lst(f"New — not in the database, kept in the User list only ({len(new)}):", [label(m) for m in new])
        + lst(f"⚠ Ambiguous name — several users match, will not be linked ({len(amb)}):",
              [f'{label(m)} → badges {", ".join(m["matches"])}' for m in amb])
        + '<div class="mt-2 text-muted small">Existing values are never overwritten; only empty e-mail, '
          'institution and career-stage fields are filled. Everyone is saved to the '
          '<a href="/user-list">User list</a> with their role (PI / SP) and funding.</div>'
    )
    cls = "alert-warning" if amb else "alert-info"
    return HTMLResponse(f'<div class="alert {cls} small">{body}{_USERLIST_BUTTONS}</div>')


@router.post("/upload/apply/userlist", response_class=HTMLResponse)
async def apply_userlist(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    matched = _preview_cache.pop(f"userlist:{get_session_user(request)['email']}", None)
    if not matched:
        return HTMLResponse('<div class="alert alert-warning">No pending preview. Please re-upload.</div>')
    records = [dict(badge=m["badge"], **m["fills"]) for m in matched if m["status"] == "matched" and m["fills"]]
    filled = db.apply_user_import(records) if records else 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for m in matched:
        rid = _roster_id(m)
        old = db.get_record("user_list", rid) or {}
        sheets = list(dict.fromkeys([*old.get("sheets", []), m["sheet"]]))
        db.save_record("user_list", rid, {
            "first_name": m["first_name"], "last_name": m["last_name"], "institution": m["institution"],
            "email": m["email"], "employment_level": m["employment_level"], "funding": m["funding"],
            "role_flag": m["role_flag"], "note": m["note"], "sheets": sheets,
            "badge": m["badge"] or old.get("badge", ""), "updated_at": now})
    log_action(request, "import", "users", "", f"User list import: {len(matched)} people, {filled} users filled")
    return HTMLResponse(
        f'<div class="alert alert-success"><i class="bi bi-check-circle me-1"></i>Saved {len(matched)} people '
        f'to the <a href="/user-list">User list</a>; filled missing fields for {filled} existing user(s).</div>')


@router.get("/user-list", response_class=HTMLResponse)
def user_list_page(request: Request):
    people = sorted(db.list_records("user_list"),
                    key=lambda p: (p.get("last_name", "").lower(), p.get("first_name", "").lower()))
    return templates.TemplateResponse("user_list.html", {
        "request": request, "people": people, "current_admin": get_session_user(request)})


@router.post("/upload/cancel/{import_type}", response_class=HTMLResponse)
def cancel_import(import_type: str, request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    user = get_session_user(request)
    if user:
        _preview_cache.pop(f"{import_type}:{user['email']}", None)
    return HTMLResponse('<div class="text-muted small">Import cancelled.</div>')
