"""Domain affiliation overrides router."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import db
from ..institution import set_override
from ..templates_env import templates

router = APIRouter()


@router.get("/overrides", response_class=HTMLResponse)
def overrides_page(request: Request):
    return templates.TemplateResponse("overrides.html", {
        "request": request,
        "overrides": db.list_domain_overrides(),
    })


@router.get("/api/domain-overrides")
def list_domain_overrides() -> list[dict]:
    return db.list_domain_overrides()


@router.post("/api/domain-overrides")
def create_domain_override(
    request:     Request,
    domain:      str = Form(...),
    institution: str = Form(""),
    country:     str = Form(""),
    state:       str = Form(""),
):
    domain = domain.lower().strip()
    if not domain:
        raise HTTPException(status_code=422, detail="domain is required")
    country = country.upper().strip()

    db.set_domain_override(domain, institution, country, state)
    updated_users = db.apply_domain_override(domain, institution, country, state)
    set_override(domain, institution, country, state)

    # Return HTML row when called from the overrides page (HTMX), JSON otherwise
    accept = request.headers.get("HX-Request", "")
    if accept:
        o = {"domain": domain, "institution": institution,
             "country": country, "state": state, "created_at": ""}
        return templates.TemplateResponse("partials/override_row_view.html",
                                          {"request": request, "o": o})
    return JSONResponse({"updated_users": updated_users})


@router.get("/overrides/{domain}/edit", response_class=HTMLResponse)
def override_edit_form(request: Request, domain: str):
    overrides = {o["domain"]: o for o in db.list_domain_overrides()}
    o = overrides.get(domain, {"domain": domain, "institution": "", "country": "", "state": ""})
    return templates.TemplateResponse("partials/override_row_edit.html",
                                      {"request": request, "o": o})


@router.get("/overrides/{domain}/view", response_class=HTMLResponse)
def override_view_row(request: Request, domain: str):
    overrides = {o["domain"]: o for o in db.list_domain_overrides()}
    o = overrides.get(domain)
    if not o:
        raise HTTPException(404)
    return templates.TemplateResponse("partials/override_row_view.html",
                                      {"request": request, "o": o})


@router.post("/overrides/{domain}", response_class=HTMLResponse)
def update_override(
    request:     Request,
    domain:      str,
    institution: str = Form(""),
    country:     str = Form(""),
    state:       str = Form(""),
):
    country = country.upper().strip()
    db.set_domain_override(domain, institution, country, state)
    updated = db.apply_domain_override(domain, institution, country, state)
    set_override(domain, institution, country, state)
    o = {"domain": domain, "institution": institution, "country": country,
         "state": state, "updated_users": updated}
    return templates.TemplateResponse("partials/override_row_view.html",
                                      {"request": request, "o": o})


@router.delete("/overrides/{domain}", response_class=HTMLResponse)
def delete_override_row(request: Request, domain: str):
    db.delete_domain_override(domain)
    return HTMLResponse("")   # HTMX swaps row out with nothing


@router.delete("/api/domain-overrides/{domain}")
def delete_domain_override(domain: str) -> Response:
    found = db.delete_domain_override(domain)
    if not found:
        raise HTTPException(status_code=404, detail="Override not found")
    return Response(status_code=204)
