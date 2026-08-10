"""aps-esaf-fetcher — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import db, sync
from .routers import esafs, stats, sync_router, fields

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,  # override any handlers installed by uvicorn or DM library at import time
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
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
app.include_router(stats.router)
app.include_router(sync_router.router)
app.include_router(fields.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/esafs")
