"""aps-esaf-fetcher — FastAPI application entry point."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from . import db, sync, config
from .institution import _load_uni_db, load_overrides
from .routers import esafs, stats, sync_router, fields
from .routers import overrides as overrides_router
from .routers import pi_groups_router
from .routers import gups as gups_router
from .routers import institutions as institutions_router
from .routers import users_router
from .routers import beamline_scientists_router
from .routers import admin_router
from .routers import upload_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)
# Give app.* its own handler so the DM library importing mid-sync
# (which rewrites the root logger level) can't silence our messages.
_app_handler = logging.StreamHandler()
_app_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
)
_app_log = logging.getLogger("app")
_app_log.addHandler(_app_handler)
_app_log.setLevel(logging.DEBUG)
_app_log.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    load_overrides(db.list_domain_overrides())
    threading.Thread(target=_load_uni_db, daemon=True, name="uni-db-loader").start()
    sync.start_scheduler()
    yield
    sync.stop_scheduler()


app = FastAPI(
    title="APS ESAF Fetcher",
    description="Fetch, store, and browse APS Experiment Safety Assessment Forms",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Auth middleware — protect all write operations
# IMPORTANT: SessionMiddleware must be added AFTER this decorator so that
# it ends up as the outermost layer (Starlette inserts at position 0 and
# reverses the stack, so last-added = first-executed).
# ---------------------------------------------------------------------------

_PUBLIC_WRITE_PATHS = {"/admin/login", "/admin/setup"}


@app.middleware("http")
async def require_login_for_writes(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        path = request.url.path
        if path not in _PUBLIC_WRITE_PATHS:
            user = request.session.get("admin_user")
            if not user:
                from fastapi.responses import JSONResponse
                is_htmx = request.headers.get("HX-Request") == "true"
                if is_htmx:
                    return JSONResponse(
                        {"error": "Login required"},
                        status_code=401,
                        headers={"HX-Redirect": "/admin/login"},
                    )
                return RedirectResponse("/admin/login", status_code=303)
    return await call_next(request)


# SessionMiddleware must come after @app.middleware so it is outermost in the stack.
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET_KEY,
    session_cookie="esaf_admin_session",
    max_age=86400 * 7,
    https_only=False,
)


_static = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")

app.include_router(admin_router.router)
app.include_router(upload_router.router)
app.include_router(esafs.router)
app.include_router(gups_router.router)
app.include_router(stats.router)
app.include_router(sync_router.router)
app.include_router(fields.router)
app.include_router(overrides_router.router)
app.include_router(pi_groups_router.router)
app.include_router(institutions_router.router)
app.include_router(users_router.router)
app.include_router(beamline_scientists_router.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/esafs")
