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
# User list workbook — choose sheets, then update the career stage of unique users
# (badge + institution) for the ESAFs from each sheet's start date on; earlier
# ESAFs keep the stage they had.  Sheets are applied in workbook order, so a later
# sheet overrides an earlier one where their periods overlap.
# ---------------------------------------------------------------------------

_USERLIST_BUTTONS = (
    '<div class="mt-3 d-flex gap-2">'
    '<button class="btn btn-success btn-sm" hx-post="/upload/apply/userlist" '
    'hx-target="#preview-userlist" hx-swap="innerHTML"><i class="bi bi-check-lg me-1"></i>Apply {n} update(s)</button>'
    '<button class="btn btn-outline-secondary btn-sm" hx-post="/upload/cancel/userlist" '
    'hx-target="#preview-userlist" hx-swap="innerHTML">Cancel</button></div>'
)


@router.post("/upload/userlist/sheets", response_class=HTMLResponse)
async def userlist_sheets(request: Request):
    """Step 1: list the workbook's sheets as checkboxes, each with its 'applies from' date."""
    redir = _require_admin(request)
    if redir:
        return redir
    upload = (await request.form()).get("file")
    if upload is None or not getattr(upload, "filename", ""):
        return HTMLResponse("")
    try:
        names = await run_in_threadpool(user_list_import.sheet_names, await upload.read())
    except Exception as exc:
        return HTMLResponse(f'<div class="alert alert-danger py-1 small">{html.escape(str(exc))}</div>')
    rows = "".join(
        f'<div class="d-flex align-items-center gap-2 mb-1">'
        f'<div class="form-check mb-0" style="min-width:210px">'
        f'<input class="form-check-input" type="checkbox" name="sheets" value="{html.escape(n, quote=True)}" id="ulsheet{i}"'
        f'{" checked" if len(names) == 1 else ""}>'
        f'<label class="form-check-label" for="ulsheet{i}">{html.escape(n)}</label></div>'
        f'<input type="text" name="since::{html.escape(n, quote=True)}" class="form-control form-control-sm" '
        f'style="max-width:150px" placeholder="YYYY-MM-DD" '
        f'value="{html.escape(user_list_import.cycle_start(n), quote=True)}"></div>'
        for i, n in enumerate(names))
    return HTMLResponse(
        '<div class="small fw-semibold mb-1">Sheets to import <span class="text-muted fw-normal">'
        '(second box: date the sheet applies from; sheets are applied in this order, later ones override earlier ones)'
        f'</span></div>{rows}')


@router.post("/upload/preview/userlist", response_class=HTMLResponse)
async def preview_userlist(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    form = await request.form()
    upload, chosen = form.get("file"), set(form.getlist("sheets"))
    if upload is None or not getattr(upload, "filename", ""):
        return HTMLResponse('<div class="alert alert-warning">Choose a file first.</div>')
    data = await upload.read()
    try:
        names = [n for n in await run_in_threadpool(user_list_import.sheet_names, data) if n in chosen]
    except Exception as exc:
        return HTMLResponse(f'<div class="alert alert-danger">{html.escape(str(exc))}</div>')
    if not names:
        return HTMLResponse('<div class="alert alert-warning">Tick at least one sheet to import.</div>')

    def lst(title, items, limit=40):
        if not items:
            return ""
        li = "".join(f"<li>{html.escape(i)}</li>" for i in items[:limit])
        more = f"<li>… and {len(items) - limit} more</li>" if len(items) > limit else ""
        return f"<div class='mt-2'><strong>{title}</strong><ul class='mb-0'>{li}{more}</ul></div>"

    def label(m):
        return f'{m["first_name"]} {m["last_name"]} ({m["matched_institution"] or m["institution"] or "no institution"})'

    users = db.list_unique_users()
    sections, sheets, roles, total_upd = [], [], {}, 0
    for name in names:
        since = (form.get(f"since::{name}") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
            return HTMLResponse(f'<div class="alert alert-warning">Sheet "{html.escape(name)}" needs an "applies from" '
                                'date (YYYY-MM-DD).</div>')
        try:
            _n, people = await run_in_threadpool(user_list_import.read_people, data, name)
        except Exception as exc:
            return HTMLResponse(f'<div class="alert alert-danger">{html.escape(name)}: {html.escape(str(exc))}</div>')
        for p in people:
            roles.setdefault((p["last_name"].lower(), p["first_name"].lower()), {})[name] = p["employment_level"]
        matched = user_list_import.match(people, users)
        cand = [m for m in matched if m["status"] == "matched" and m["employment_level"]]
        flat = [{"badge": m["badge"], "institution": inst, "employment_level": m["employment_level"]}
                for m in cand for inst in m["groups"]]
        plans = iter(db.preview_career_stage(flat, since))
        for m in cand:
            ps = [next(plans) for _ in m["groups"]]
            m["plan"] = {"esafs": sum(p["esafs"] for p in ps), "blank": sum(p["blank"] for p in ps),
                         "changed": sum(p["changed"] for p in ps), "targets": [t for p in ps for t in p["targets"]],
                         "old": sorted({o for p in ps for o in p["old"]})}
        chg = [m for m in cand if m["plan"]["changed"]]
        fill = [m for m in cand if m["plan"]["blank"] and not m["plan"]["changed"]]
        same = [m for m in cand if m["plan"]["esafs"] and not m["plan"]["targets"]]
        none = [m for m in cand if not m["plan"]["esafs"]]
        new = [m for m in matched if m["status"] == "new"]
        amb = [m for m in matched if m["status"] == "ambiguous"]
        total_upd += len(chg) + len(fill)
        sheets.append({"name": name, "since": since, "matched": matched})
        sections.append(
            f'<div class="border-top pt-2 mt-2"><strong>Sheet "{html.escape(name)}"</strong>, ESAFs from {since} on: '
            f'{len(people)} people — {len(chg)} with a different stage, {len(fill)} with only an empty stage to fill, '
            f'{len(same)} already correct, {len(none)} with no ESAF since then, {len(new)} not in the database, '
            f'{len(amb)} ambiguous.'
            + lst(f"Career stage will CHANGE ({len(chg)}):",
                  [f'{label(m)} badge {m["badge"]}: {", ".join(m["plan"]["old"])} → {m["employment_level"]} '
                   f'(different on {m["plan"]["changed"]} ESAF(s)'
                   + (f', empty on {m["plan"]["blank"]}' if m["plan"]["blank"] else "") + ")" for m in chg])
            + lst(f"Empty stage will be FILLED, nothing overwritten ({len(fill)}):",
                  [f'{label(m)} badge {m["badge"]}: → {m["employment_level"]} on {m["plan"]["blank"]} ESAF(s)' for m in fill])
            + lst(f"⚠ Ambiguous — different people match, skipped ({len(amb)}):",
                  [f'{label(m)} → {", ".join(m["matches"])}' for m in amb])
            + lst(f"Not in the database — skipped ({len(new)}):", [label(m) for m in new], 15)
            + '</div>')

    conflicts = [f'{k[1].title()} {k[0].title()}: ' + "; ".join(f"{s} = {r or '(empty)'}" for s, r in v.items())
                 for k, v in roles.items() if len({r.lower() for r in v.values() if r}) > 1]
    _preview_cache[f"userlist:{get_session_user(request)['email']}"] = {"sheets": sheets}
    body = (
        '<strong>Preview — nothing saved yet.</strong> '
        + ('Sheets are applied in this order: ' + " → ".join(html.escape(n) for n in names) + '.' if len(names) > 1 else '')
        + lst(f"⚠ The selected sheets disagree about these people — the LAST sheet wins where the periods overlap "
              f"({len(conflicts)}):", conflicts)
        + "".join(sections)
        + '<div class="mt-2 text-muted small">A unique user is a badge at one institution. Only that user\'s ESAFs '
          'from each sheet\'s date on are changed; earlier ESAFs keep the stage they had. The counts above are '
          'computed against the current database, one sheet at a time.</div>'
    )
    cls = "alert-warning" if conflicts else "alert-info"
    buttons = _USERLIST_BUTTONS.format(n=total_upd) if total_upd else ""
    return HTMLResponse(f'<div class="alert {cls} small">{body}{buttons}</div>')


@router.post("/upload/apply/userlist", response_class=HTMLResponse)
async def apply_userlist(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    pending = _preview_cache.pop(f"userlist:{get_session_user(request)['email']}", None)
    if not pending:
        return HTMLResponse('<div class="alert alert-warning">No pending preview. Please re-upload.</div>')
    done = []
    for sh in pending["sheets"]:                        # in workbook order: later sheets override earlier ones
        # every matched person: apply_career_stage works out what still differs *now*, after earlier sheets
        updates = [{"badge": m["badge"], "institution": inst, "employment_level": m["employment_level"]}
                   for m in sh["matched"] if m["status"] == "matched" and m["employment_level"] for inst in m["groups"]]
        n = db.apply_career_stage(updates, sh["since"]) if updates else 0
        done.append(f'{sh["name"]}: {n} user(s) from {sh["since"]}')
        log_action(request, "import", "users", "", f'User list "{sh["name"]}": career stage updated for {n} users from {sh["since"]}')
    return HTMLResponse('<div class="alert alert-success"><i class="bi bi-check-circle me-1"></i>Career stage updated — '
                        + html.escape("; ".join(done)) + '.</div>')


@router.post("/upload/cancel/{import_type}", response_class=HTMLResponse)
def cancel_import(import_type: str, request: Request):
    redir = _require_admin(request)
    if redir:
        return redir
    user = get_session_user(request)
    if user:
        _preview_cache.pop(f"{import_type}:{user['email']}", None)
    return HTMLResponse('<div class="text-muted small">Import cancelled.</div>')
