"""Admin authentication and management endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import db, display_tz
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
    tz_saved: str = "",
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
        "tz_name": display_tz.get_timezone_name(),
        "tz_common": display_tz.COMMON_TZS,
        "tz_all": display_tz.all_timezones(),
        "tz_saved": tz_saved,
        "now_utc": datetime.now(timezone.utc),
        # change-password form initial state
        "cp_error": "",
        "cp_msg": "",
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


@router.post("/admin/users/{email:path}/reset-password", response_class=HTMLResponse)
async def reset_admin_password(email: str, request: Request):
    """Any logged-in admin can force-set another admin's password (no old password needed)."""
    redir = _require_admin(request)
    if redir:
        return redir

    current = get_session_user(request)
    form = await request.form()
    new_pw = (form.get("new_password") or "")
    confirm = (form.get("confirm_password") or "")

    errors = []
    if len(new_pw) < 8:
        errors.append("Password must be ≥ 8 characters.")
    if new_pw != confirm:
        errors.append("Passwords do not match.")

    msg = ""
    if not errors:
        db.update_admin_password(email, hash_password(new_pw))
        log_action(request, "edit", "admin_users", email, f"Reset password for {email}")
        msg = f"Password for {email} has been reset."

    admins = db.list_admin_users()
    return templates.TemplateResponse("partials/admins_table.html", {
        "request": request,
        "admins": admins,
        "current_admin": current,
        "add_error": " ".join(errors),
        "add_msg": msg,
    })


@router.post("/admin/change-password", response_class=HTMLResponse)
async def change_own_password(request: Request):
    """Logged-in admin changes their own password (current password required)."""
    redir = _require_admin(request)
    if redir:
        return redir

    current = get_session_user(request)
    form = await request.form()
    current_pw = (form.get("current_password") or "")
    new_pw = (form.get("new_password") or "")
    confirm = (form.get("confirm_password") or "")

    user = db.get_admin_user_by_email(current["email"])
    errors = []
    if not user or not verify_password(current_pw, user["password_hash"]):
        errors.append("Current password is incorrect.")
    if len(new_pw) < 8:
        errors.append("New password must be ≥ 8 characters.")
    if new_pw != confirm:
        errors.append("Passwords do not match.")

    msg = ""
    if not errors:
        db.update_admin_password(current["email"], hash_password(new_pw))
        log_action(request, "edit", "admin_users", current["email"], "Changed own password")
        msg = "Password updated successfully."

    return templates.TemplateResponse("partials/change_password_form.html", {
        "request": request,
        "cp_error": " ".join(errors),
        "cp_msg": msg,
    })




# ---------------------------------------------------------------------------
# Display time zone
# ---------------------------------------------------------------------------

@router.post("/admin/timezone")
async def set_display_timezone(request: Request):
    """Admin picks the time zone used to display timestamps across the UI."""
    redir = _require_admin(request)
    if redir:
        return redir
    form = await request.form()
    name = (form.get("timezone") or "").strip()
    try:
        display_tz.set_timezone_name(name)
    except ValueError:
        return RedirectResponse("/admin?tz_saved=0", status_code=303)
    log_action(request, "edit", "settings", "timezone", f"Display time zone set to {name}")
    return RedirectResponse("/admin?tz_saved=1", status_code=303)
