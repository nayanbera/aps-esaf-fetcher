"""PI Groups management router."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import db
from ..templates_env import templates

router = APIRouter()


# ---------------------------------------------------------------------------
# Management page
# ---------------------------------------------------------------------------

@router.get("/pi-groups", response_class=HTMLResponse)
def pi_groups_page(request: Request):
    users = db.list_users_for_lookup()
    return templates.TemplateResponse("pi_groups.html", {
        "request": request,
        "pi_groups": db.list_pi_groups(),
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
):
    name = name.strip()
    if not name:
        raise HTTPException(422, "PI Group name is required")
    pi_name = pi_name.strip()
    db.upsert_pi_group(name, pi_name, pi_email.strip(),
                       institution.strip(), country.strip().upper(),
                       state.strip(), orcid_id.strip())
    pg = {"name": name, "pi_name": pi_name, "pi_email": pi_email.strip(),
          "institution": institution.strip(), "country": country.strip().upper(),
          "state": state.strip(), "orcid_id": orcid_id.strip(), "created_at": ""}
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
                               "orcid_id": "", "created_at": ""}
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


@router.post("/pi-groups/{name}", response_class=HTMLResponse)
def update_pi_group(
    request:     Request,
    name:        str,
    pi_name:     str = Form(""),
    pi_email:    str = Form(""),
    institution: str = Form(""),
    country:     str = Form(""),
    state:       str = Form(""),
    orcid_id:    str = Form(""),
):
    pi_name = pi_name.strip()
    db.upsert_pi_group(name, pi_name, pi_email.strip(),
                       institution.strip(), country.strip().upper(),
                       state.strip(), orcid_id.strip())
    pg = {"name": name, "pi_name": pi_name, "pi_email": pi_email.strip(),
          "institution": institution.strip(), "country": country.strip().upper(),
          "state": state.strip(), "orcid_id": orcid_id.strip()}
    return templates.TemplateResponse("partials/pi_group_row_view.html",
                                      {"request": request, "pg": pg})


@router.delete("/pi-groups/{name}", response_class=HTMLResponse)
def delete_pi_group_row(name: str):
    db.delete_pi_group(name)
    return HTMLResponse("")
