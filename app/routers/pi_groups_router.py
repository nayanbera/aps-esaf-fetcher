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
    db.upsert_pi_group(name, pi_name.strip(), pi_email.strip(),
                       institution.strip(), country.strip().upper(),
                       state.strip(), orcid_id.strip())
    pg = {"name": name, "pi_name": pi_name.strip(), "pi_email": pi_email.strip(),
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
    users = db.list_users_for_lookup()
    return templates.TemplateResponse("partials/pi_group_row_edit.html",
                                      {"request": request, "pg": pg, "all_users": users})


@router.get("/pi-groups/{name}/view", response_class=HTMLResponse)
def pi_group_view_row(request: Request, name: str):
    groups = {g["name"]: g for g in db.list_pi_groups()}
    pg = groups.get(name)
    if not pg:
        raise HTTPException(404)
    return templates.TemplateResponse("partials/pi_group_row_view.html",
                                      {"request": request, "pg": pg})


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
    db.upsert_pi_group(name, pi_name.strip(), pi_email.strip(),
                       institution.strip(), country.strip().upper(),
                       state.strip(), orcid_id.strip())
    pg = {"name": name, "pi_name": pi_name.strip(), "pi_email": pi_email.strip(),
          "institution": institution.strip(), "country": country.strip().upper(),
          "state": state.strip(), "orcid_id": orcid_id.strip()}
    return templates.TemplateResponse("partials/pi_group_row_view.html",
                                      {"request": request, "pg": pg})


@router.delete("/pi-groups/{name}", response_class=HTMLResponse)
def delete_pi_group_row(name: str):
    db.delete_pi_group(name)
    return HTMLResponse("")
