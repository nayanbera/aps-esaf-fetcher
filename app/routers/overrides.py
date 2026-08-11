"""Domain affiliation overrides router."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, Response

from .. import db
from ..institution import set_override

router = APIRouter()


@router.get("/api/domain-overrides")
def list_domain_overrides() -> list[dict]:
    return db.list_domain_overrides()


@router.post("/api/domain-overrides")
def create_domain_override(
    domain:      str = Form(...),
    institution: str = Form(""),
    country:     str = Form(""),
    state:       str = Form(""),
) -> JSONResponse:
    domain = domain.lower().strip()
    if not domain:
        raise HTTPException(status_code=422, detail="domain is required")

    db.set_domain_override(domain, institution, country, state)
    updated_users = db.apply_domain_override(domain, institution, country, state)
    set_override(domain, institution, country, state)

    return JSONResponse({"updated_users": updated_users})


@router.delete("/api/domain-overrides/{domain}")
def delete_domain_override(domain: str) -> Response:
    found = db.delete_domain_override(domain)
    if not found:
        raise HTTPException(status_code=404, detail="Override not found")
    return Response(status_code=204)
