"""Custom field definition management."""

import json
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Annotated

from .. import db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

FIELD_TYPES = ["text", "textarea", "number", "date", "select"]


@router.get("/fields", response_class=HTMLResponse)
def fields_page(request: Request):
    return templates.TemplateResponse("fields.html", {
        "request": request,
        "field_defs": db.list_field_definitions(),
        "field_types": FIELD_TYPES,
    })


@router.post("/fields", response_class=HTMLResponse)
def create_field(
    request: Request,
    name:       Annotated[str, Form()],
    label:      Annotated[str, Form()],
    field_type: Annotated[str, Form()],
    options:    Annotated[str, Form()] = "",
):
    # Sanitise name to a safe identifier
    safe_name = name.strip().lower().replace(" ", "_")
    options_list = [o.strip() for o in options.split(",") if o.strip()]
    db.upsert_field_definition(safe_name, label.strip(), field_type, options_list)
    return RedirectResponse("/fields", status_code=303)


@router.delete("/fields/{name}", response_class=HTMLResponse)
def delete_field(request: Request, name: str):
    db.delete_field_definition(name)
    return templates.TemplateResponse("partials/field_list.html", {
        "request": request,
        "field_defs": db.list_field_definitions(),
        "field_types": FIELD_TYPES,
    })
