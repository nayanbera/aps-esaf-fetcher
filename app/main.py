"""aps-esaf-fetcher — FastAPI application entry point."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import db, sync
from .institution import _load_uni_db, load_overrides
from .routers import esafs, stats, sync_router, fields
from .routers import overrides as overrides_router
from .routers import pi_groups_router
from .routers import gups as gups_router

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

_static = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")

app.include_router(esafs.router)
app.include_router(gups_router.router)
app.include_router(stats.router)
app.include_router(sync_router.router)
app.include_router(fields.router)
app.include_router(overrides_router.router)
app.include_router(pi_groups_router.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/esafs")
