"""Admin authentication and management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import db, sync
from ..auth import hash_password, verify_password, get_session_user, log_action
from ..templates_env import templates

router = APIRouter()


def _require_admin(request: Request):
    """Return None if admin is logged in, else a redirect response."""
    if get_session_user(request):
        return None
    return RedirectResponse("/admin/login", status_code=303)


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@router.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    no_admins = db.count_admin_users() == 0
    return templates.TemplateResponse("admin_login.html", {
        "request": request,
        "error": error,
        "no_admins": no_admins,
    })


@router.post("/admin/login")
async def login_submit(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = (form.get("password") or "")

    user = db.get_admin_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "error": "Invalid email or password.",
            "no_admins": False,
        }, status_code=401)

    request.session["admin_user"] = {"email": user["email"], "name": user["name"]}
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ---------------------------------------------------------------------------
# First-admin bootstrap
# ---------------------------------------------------------------------------

@router.post("/admin/setup")
async def setup_first_admin(request: Request):
    """Create the very first admin account (only works when no admins exist)."""
    if db.count_admin_users() > 0:
        return RedirectResponse("/admin/login", status_code=303)

    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    name = (form.get("name") or "").strip()
    password = (form.get("password") or "")
    confirm = (form.get("confirm") or "")

    errors = []
    if not email:
        errors.append("Email is required.")
    if not name:
        errors.append("Name is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")

    if errors:
        return templates.TemplateResponse("admin_login.html", {
            "request": request,
            "error": " ".join(errors),
            "no_admins": True,
        }, status_code=422)

    db.add_admin_user(email, name, hash_password(password))
    request.session["admin_user"] = {"email": email, "name": name}
    return RedirectResponse("/admin", status_code=303)


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    log_email: str = "",
    log_action_filter: str = "",
    log_from: str = "",
    log_to: str = "",
    log_page: int = 1,
):
    redir = _require_admin(request)
    if redir:
        return redir

    PAGE_SIZE = 50
    offset = (log_page - 1) * PAGE_SIZE

    admins = db.list_admin_users()
    audit_rows, audit_total = db.list_audit_log(
        limit=PAGE_SIZE,
        offset=offset,
        user_email=log_email,
        action=log_action_filter,
        from_date=log_from,
        to_date=log_to,
    )
    total_pages = max(1, (audit_total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "current_admin": get_session_user(request),
        "admins": admins,
        "audit_rows": audit_rows,
        "audit_total": audit_total,
        "log_page": log_page,
        "total_pages": total_pages,
        "log_email": log_email,
        "log_action_filter": log_action_filter,
        "log_from": log_from,
        "log_to": log_to,
        "sync_interval_hours": sync.get_interval_hours(),
    })


# ---------------------------------------------------------------------------
# Admin user management
# ---------------------------------------------------------------------------

@router.post("/admin/users", response_class=HTMLResponse)
async def add_admin_user(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir

    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    name = (form.get("name") or "").strip()
    password = (form.get("password") or "")

    errors = []
    if not email:
        errors.append("Email required.")
    if not name:
        errors.append("Name required.")
    if len(password) < 8:
        errors.append("Password must be ≥ 8 chars.")

    msg = ""
    if not errors:
        ok = db.add_admin_user(email, name, hash_password(password))
        if ok:
            log_action(request, "add", "admin_users", email, f"Added admin {name} ({email})")
            msg = f"Admin '{name}' added."
        else:
            errors.append(f"Email '{email}' already exists.")

    admins = db.list_admin_users()
    return templates.TemplateResponse("partials/admins_table.html", {
        "request": request,
        "admins": admins,
        "current_admin": get_session_user(request),
        "add_error": " ".join(errors),
        "add_msg": msg,
    })


@router.delete("/admin/users/{email:path}", response_class=HTMLResponse)
def remove_admin_user(email: str, request: Request):
    redir = _require_admin(request)
    if redir:
        return redir

    current = get_session_user(request)
    if current and current["email"] == email:
        admins = db.list_admin_users()
        return templates.TemplateResponse("partials/admins_table.html", {
            "request": request,
            "admins": admins,
            "current_admin": current,
            "add_error": "You cannot remove your own account.",
            "add_msg": "",
        })

    db.remove_admin_user(email)
    log_action(request, "delete", "admin_users", email, f"Removed admin {email}")
    admins = db.list_admin_users()
    return templates.TemplateResponse("partials/admins_table.html", {
        "request": request,
        "admins": admins,
        "current_admin": current,
        "add_error": "",
        "add_msg": "",
    })


# ---------------------------------------------------------------------------
# Sync settings
# ---------------------------------------------------------------------------

@router.post("/admin/sync-settings", response_class=HTMLResponse)
async def update_sync_settings(request: Request):
    redir = _require_admin(request)
    if redir:
        return redir

    form = await request.form()
    try:
        hours = int(form.get("sync_interval_hours") or 0)
        if hours < 0:
            hours = 0
    except ValueError:
        hours = 0

    sync.reschedule(hours)
    log_action(request, "edit", "settings", "sync_interval",
               f"Auto-sync interval set to {hours}h (0 = disabled)")

    msg = f"Auto-sync interval updated to every {hours} hour(s)." if hours > 0 \
          else "Auto-sync disabled."
    return templates.TemplateResponse("partials/sync_settings.html", {
        "request": request,
        "sync_interval_hours": sync.get_interval_hours(),
        "sync_settings_msg": msg,
    })
