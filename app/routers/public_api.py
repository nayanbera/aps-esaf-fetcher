"""Public JSON API — for consumption by external Python apps.

All endpoints are unauthenticated read-only GET routes.

Endpoints
---------
GET /api/users
    List / search users.
    Query params: q (name/email/badge search), badge (exact), institution,
                  limit (default 200, max 1000), offset (default 0)
    Returns: {"total": int, "users": [...]}

GET /api/users/{badge}
    Full user record plus their ESAF history.
    Returns: user dict with "esafs", "institution_type", "is_beamline_scientist"

GET /api/esafs                          (already in esafs.py — untouched)
GET /api/esafs/{esaf_id}               (enriched in backend with institution_type per user)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db

router = APIRouter()


@router.get("/api/users")
def api_list_users(
    q:           str = "",
    badge:       str = "",
    institution: str = "",
    limit:       int = 200,
    offset:      int = 0,
):
    limit = min(limit, 1000)
    users, total = db.list_users(q=q, badge=badge, institution=institution,
                                 limit=limit, offset=offset)
    return {"total": total, "limit": limit, "offset": offset, "users": users}


@router.get("/api/users/{badge}")
def api_get_user(badge: str):
    user = db.get_user_detail(badge)
    if user is None:
        raise HTTPException(404, f"User with badge {badge!r} not found")
    return user
