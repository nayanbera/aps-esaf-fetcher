"""PI Groups management router."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

import html

from starlette.concurrency import run_in_threadpool

from .. import db, pi_id_import
from ..templates_env import templates

router = APIRouter()


# ---------------------------------------------------------------------------
# Management page
# ---------------------------------------------------------------------------

# One table per technique.  A group using several techniques is listed in each.
_SECTIONS = [("Surf", "Surf", "primary"), ("Xtal", "Xtal", "success"),
             ("ASWAXS", "ASWAXS", "warning"), ("Beamline", "Beamline", "info"),
             ("", "No technique assigned", "secondary")]


def _sections(groups: list[dict]) -> list[dict]:
    out = []
    for key, label, color in _SECTIONS:
        if key:
            members = [g for g in groups if key in (g.get("technique") or "").split(",")]
        else:
            members = [g for g in groups
                       if not any(k in (g.get("technique") or "").split(",")
                                  for k, _, _ in _SECTIONS if k)]
        out.append({"key": key, "label": label, "color": color, "groups": members})
    return out


@router.get("/pi-groups", response_class=HTMLResponse)
def pi_groups_page(request: Request):
    users = db.list_users_for_lookup()
    groups = db.list_pi_groups()
    return templates.TemplateResponse("pi_groups.html", {
        "request": request,
        "pi_groups": groups,
        "sections": _sections(groups),
        "all_users": users,
    })


# ---------------------------------------------------------------------------
# User search API (for autocomplete)
# ---------------------------------------------------------------------------

@router.get("/api/users-search")
def users_search(q: str = "") -> list[dict]:
    return db.list_users_for_lookup(q=q)


@router.get("/api/institutions")
def institutions_list() -> list[str]:
    return db.list_distinct_institutions()


def _clean_pi_id(raw: str) -> str:
    """'ac-50 ; as-08' -> 'AC-50, AS-08' (one ID per technique the group uses)."""
    ids = [t for t in re.split(r"[\s,;]+", (raw or "").upper()) if t]
    return ", ".join(dict.fromkeys(ids))


def _split_email_orcid(pi_email: str, orcid_id: str) -> tuple[str, str]:
    """An email typed into the ORCID box (it used to sit under the Email column) moves to the email field."""
    pi_email, orcid_id = pi_email.strip(), orcid_id.strip()
    if "@" in orcid_id:
        if not pi_email:
            pi_email = orcid_id
        orcid_id = ""
    return pi_email, orcid_id


_VALID_TECHNIQUES = {"", "Surf", "Xtal", "ASWAXS", "Beamline"}


@router.post("/pi-groups/{name}/toggle-technique", response_class=HTMLResponse)
def toggle_pi_group_technique(
    request: Request,
    name: str,
    technique: str = Form(""),
):
    from urllib.parse import quote
    technique = technique.strip()
    if technique not in {"Surf", "Xtal", "ASWAXS", "Beamline"}:
        raise HTTPException(400, f"Invalid technique '{technique}'")
    groups = {g["name"]: g for g in db.list_pi_groups()}
    pg = groups.get(name) or {}
    current = {t for t in (pg.get("technique", "") or "").split(",") if t}
    if technique in current:
        current.discard(technique)
    else:
        current.add(technique)
    _ORDER = ["Surf", "Xtal", "ASWAXS", "Beamline"]
    new_technique = ",".join(t for t in _ORDER if t in current)
    db.set_pi_group_technique(name, new_technique)
    post_url = f"/pi-groups/{quote(name, safe='')}/toggle-technique"
    return templates.TemplateResponse(
        "partials/pi_group_technique_toggles.html",
        {"request": request, "technique": new_technique, "post_url": post_url},
    )


# ---------------------------------------------------------------------------
# Create (from the add form at the top of the page)
# ---------------------------------------------------------------------------

@router.post("/pi-groups", response_class=HTMLResponse)
def create_pi_group(
    request:     Request,
    name:        str = Form(...),
    pi_name:     str = Form(""),
    pi_email:    str = Form(""),
    institution: str = Form(""),
    country:     str = Form(""),
    state:       str = Form(""),
    orcid_id:    str = Form(""),
    technique:   list[str] = Form([]),
    pi_id:       str = Form(""),
):
    name = name.strip()
    if not name:
        raise HTTPException(422, "PI Group name is required")
    pi_name = pi_name.strip()
    pi_email, orcid_id = _split_email_orcid(pi_email, orcid_id)
    db.upsert_pi_group(name, pi_name, pi_email,
                       institution.strip(), country.strip().upper(),
                       state.strip(), orcid_id, _clean_pi_id(pi_id))
    techniques = ",".join(k for k, _, _ in _SECTIONS if k and k in technique)
    if techniques:
        db.set_pi_group_technique(name, techniques)
    pg = {"name": name, "pi_name": pi_name, "pi_email": pi_email,
          "institution": institution.strip(), "country": country.strip().upper(),
          "state": state.strip(), "orcid_id": orcid_id,
          "pi_id": _clean_pi_id(pi_id), "technique": techniques, "created_at": ""}
    return templates.TemplateResponse("partials/pi_group_row_view.html",
                                      {"request": request, "pg": pg})


# ---------------------------------------------------------------------------
# Inline edit flow (HTMX)
# ---------------------------------------------------------------------------

@router.get("/pi-groups/{name}/edit", response_class=HTMLResponse)
def pi_group_edit_form(request: Request, name: str):
    groups = {g["name"]: g for g in db.list_pi_groups()}
    pg = groups.get(name) or {"name": name, "pi_name": "", "pi_email": "",
                               "institution": "", "country": "", "state": "",
                               "orcid_id": "", "technique": "", "created_at": ""}
    return templates.TemplateResponse("partials/pi_group_row_edit.html",
                                      {"request": request, "pg": pg})


@router.get("/pi-groups/{name}/view", response_class=HTMLResponse)
def pi_group_view_row(request: Request, name: str):
    groups = {g["name"]: g for g in db.list_pi_groups()}
    pg = groups.get(name)
    if not pg:
        raise HTTPException(404)
    return templates.TemplateResponse("partials/pi_group_row_view.html",
                                      {"request": request, "pg": pg})


@router.post("/pi-groups/{name}/propagate", response_class=HTMLResponse)
def propagate_pi_group(name: str):
    groups = {g["name"]: g for g in db.list_pi_groups()}
    pg = groups.get(name)
    if not pg or not pg.get("pi_name"):
        return HTMLResponse(
            '<span class="text-warning">No PI name set — cannot match ESAFs.</span>'
        )
    count = db.propagate_pi_group_by_pi_name(name, pg["pi_name"], pg.get("institution", ""))
    if count:
        return HTMLResponse(
            f'<span class="text-success">'
            f'<i class="bi bi-check-lg me-1"></i>Linked {count} ESAF(s).</span>'
        )
    return HTMLResponse(
        '<span class="text-muted">No unassigned ESAFs matched.</span>'
    )


@router.post("/pi-groups/{name}/clear-assignments", response_class=HTMLResponse)
def clear_pi_group_assignments(name: str):
    count = db.clear_pi_group_assignments(name)
    if count:
        return HTMLResponse(
            f'<span class="text-warning">'
            f'<i class="bi bi-x-lg me-1"></i>Cleared {count} ESAF(s).</span>'
        )
    return HTMLResponse('<span class="text-muted">No ESAFs were assigned to this group.</span>')


def _listing(title: str, items: list[str], limit: int = 25) -> str:
    if not items:
        return ""
    li = "".join(f"<li>{html.escape(i)}</li>" for i in items[:limit])
    more = f"<li>… and {len(items) - limit} more</li>" if len(items) > limit else ""
    return f"<div class='mt-2'><strong>{title}</strong><ul class='mb-0'>{li}{more}</ul></div>"


@router.post("/pi-groups/import-ids", response_class=HTMLResponse)
async def import_pi_ids(excel_file: UploadFile = File(...)):
    """Step 1: read the Teams sheet and show a report.  Nothing is written until confirmed."""
    data = await excel_file.read()
    try:
        teams = await run_in_threadpool(pi_id_import.read_teams, data)
    except Exception as exc:
        return HTMLResponse(f'<div class="alert alert-danger">Could not read the Excel file: '
                            f'{html.escape(str(exc))}</div>')
    if not teams:
        return HTMLResponse('<div class="alert alert-warning">No team rows (IDs like AC-01) '
                            'found in the Teams sheet.</div>')
    groups = db.list_pi_groups()
    res = pi_id_import.match_ids(teams, groups)
    by_name = {g["name"]: g for g in groups}

    new, changed, same = [], [], []
    for name, ids in res["assign"].items():
        old = _clean_pi_id(by_name[name].get("pi_id", "")).split(", ") if by_name[name].get("pi_id") else []
        if not old:
            new.append(f"{name}: (none) → {', '.join(ids)}")
        elif set(old) == set(ids):
            same.append(name)
        else:
            lost = [i for i in old if i not in ids]
            note = f" — <b>not in file: {html.escape(', '.join(lost))}</b>" if lost else ""
            changed.append(f"{html.escape(name)}: {html.escape(', '.join(old))} → "
                           f"{html.escape(', '.join(ids))}{note}")

    # Issues: the same Team ID proposed for several groups
    owners: dict[str, list[str]] = {}
    for name, ids in res["assign"].items():
        for i in ids:
            owners.setdefault(i, []).append(name)
    dupes = [f"{i} → {', '.join(sorted(n))}" for i, n in owners.items() if len(n) > 1]

    pending = [g["name"] for g in groups if g["name"] not in res["assign"]]
    pending_with_id = [g["name"] for g in groups
                       if g["name"] not in res["assign"] and g.get("pi_id")]
    has_issues = bool(res["unmatched"] or res["ambiguous"] or dupes)

    payload = html.escape(json.dumps(res["assign"]), quote=True)
    changed_li = "".join(f"<li>{c}</li>" for c in changed[:50])
    changed_html = (f"<div class='mt-2'><strong>Will change ({len(changed)}):</strong>"
                    f"<ul class='mb-0'>{changed_li}</ul></div>") if changed else ""
    body = (
        f"<strong>Preview — nothing has been saved yet.</strong><br>"
        f"{len(teams)} teams read from the file; {len(res['assign'])} of {len(groups)} PI Groups matched "
        f"({len(new)} new, {len(changed)} changed, {len(same)} already identical)."
        + _listing(f"New PI IDs ({len(new)}):", [html.escape(x) for x in new])
        + changed_html
        + (_listing("⚠ Same Team ID proposed for several PI Groups (check names):", dupes))
        + _listing(f"⚠ Teams matching more than one PI Group — will be skipped ({len(res['ambiguous'])}):",
                   res["ambiguous"])
        + _listing(f"⚠ Teams in the file with no PI Group — will be skipped ({len(res['unmatched'])}):",
                   res["unmatched"], 25)
        + _listing(f"PI Groups with an existing PI ID but no match in the file — will stay unchanged "
                   f"({len(pending_with_id)}):", pending_with_id)
        + (f"<div class='mt-2 text-muted'>{len(pending) - len(pending_with_id)} other PI Groups have no "
           f"match and no PI ID.</div>" if pending else "")
    )
    controls = f"""
<form class="mt-3 d-flex align-items-center gap-3 flex-wrap"
      hx-post="/pi-groups/import-ids/confirm" hx-target="#pi-id-import-result"
      hx-on::after-request="if (window.pgReloadSections) window.pgReloadSections()">
  <input type="hidden" name="assign" value="{payload}">
  <div class="form-check mb-0">
    <input class="form-check-input" type="checkbox" name="merge" value="1" id="pi-id-merge">
    <label class="form-check-label" for="pi-id-merge">Keep existing IDs that are not in the file (merge instead of replace)</label>
  </div>
  <button type="submit" class="btn btn-success btn-sm"><i class="bi bi-check-lg me-1"></i>Apply {len(new) + len(changed)} change(s)</button>
  <button type="button" class="btn btn-outline-secondary btn-sm"
          onclick="document.getElementById('pi-id-import-result').innerHTML=''">Cancel</button>
</form>"""
    cls = "alert-warning" if has_issues else "alert-info"
    return HTMLResponse(f'<div class="alert {cls}">{body}{controls}</div>')


@router.post("/pi-groups/import-ids/confirm", response_class=HTMLResponse)
async def import_pi_ids_confirm(assign: str = Form(...), merge: str = Form("")):
    """Step 2: write the previewed PI IDs."""
    try:
        proposed = json.loads(assign)
        assert isinstance(proposed, dict)
    except Exception:
        return HTMLResponse('<div class="alert alert-danger">Invalid import data — please upload the file again.</div>')
    by_name = {g["name"]: g for g in db.list_pi_groups()}
    done = skipped = 0
    for name, ids in proposed.items():
        g = by_name.get(name)
        if g is None or not isinstance(ids, list):
            skipped += 1
            continue
        ids = [str(i) for i in ids]
        if merge:
            ids = list(dict.fromkeys(
                [t for t in re.split(r"[\s,;]+", (g.get("pi_id") or "").upper()) if t] + ids))
        new_id = _clean_pi_id(", ".join(ids))
        if new_id == _clean_pi_id(g.get("pi_id", "")):
            continue
        db.upsert_pi_group(name, g.get("pi_name", ""), g.get("pi_email", ""),
                           g.get("institution", ""), g.get("country", ""),
                           g.get("state", ""), g.get("orcid_id", ""), new_id)
        done += 1
    extra = f" {skipped} group(s) no longer exist and were skipped." if skipped else ""
    return HTMLResponse(f'<div class="alert alert-success">Applied: {done} PI Group(s) updated '
                        f'({"merged with existing IDs" if merge else "existing IDs replaced"}).{extra}</div>')


@router.post("/pi-groups/{name}", response_class=HTMLResponse)
def update_pi_group(
    request:     Request,
    name:        str,           # old name from URL path
    new_name:    str = Form(""),
    pi_name:     str = Form(""),
    pi_email:    str = Form(""),
    institution: str = Form(""),
    country:     str = Form(""),
    state:       str = Form(""),
    orcid_id:    str = Form(""),
    pi_id:       str = Form(""),
):
    new_name = new_name.strip() or name
    if not new_name:
        raise HTTPException(422, "PI Group name is required")
    if new_name != name:
        try:
            db.rename_pi_group(name, new_name)
        except Exception:
            raise HTTPException(409, f"A PI Group named '{new_name}' already exists.")
    pi_email, orcid_id = _split_email_orcid(pi_email, orcid_id)
    db.upsert_pi_group(new_name, pi_name.strip(), pi_email,
                       institution.strip(), country.strip().upper(),
                       state.strip(), orcid_id, _clean_pi_id(pi_id))
    # Technique is managed independently by toggle-technique; read back from DB.
    groups = {g["name"]: g for g in db.list_pi_groups()}
    pg = groups.get(new_name) or {
        "name": new_name, "pi_name": pi_name.strip(), "pi_email": pi_email,
        "institution": institution.strip(), "country": country.strip().upper(),
        "state": state.strip(), "orcid_id": orcid_id,
        "pi_id": _clean_pi_id(pi_id), "technique": "",
    }
    return templates.TemplateResponse("partials/pi_group_row_view.html",
                                      {"request": request, "pg": pg})


@router.delete("/pi-groups/{name}", response_class=HTMLResponse)
def delete_pi_group_row(name: str):
    db.delete_pi_group(name)
    return HTMLResponse("")
