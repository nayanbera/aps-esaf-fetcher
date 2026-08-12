"""Authentication helpers for session-based admin auth."""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Request


def hash_password(pw: str) -> str:
    """Return a PBKDF2-HMAC-SHA256 hash string for *pw*.

    Format: ``pbkdf2:{salt_hex}:{digest_hex}``
    """
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 260_000)
    return f"pbkdf2:{salt.hex()}:{digest.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    """Return True when *pw* matches the *stored* hash (constant-time compare)."""
    try:
        _scheme, salt_hex, digest_hex = stored.split(":")
    except ValueError:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 260_000)
    return hmac.compare_digest(candidate, expected)


def get_session_user(request: Request) -> dict | None:
    """Return the admin user dict stored in the session, or None."""
    return request.session.get("admin_user")


def log_action(
    request: Request,
    action: str,
    table: str = "",
    record_id: str = "",
    description: str = "",
    changes: dict | None = None,
) -> None:
    """Record an admin action in the audit log.

    Imports ``db`` lazily to avoid circular imports.
    """
    if changes is None:
        changes = {}
    user = get_session_user(request)
    email = user.get("email", "") if user else ""
    from . import db  # lazy import — avoids circular dependency
    db.add_audit_log(
        user_email=email,
        action=action,
        table_name=table,
        record_id=record_id,
        description=description,
        changes=changes,
    )
