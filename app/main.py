"""FastAPI application: REST API + the Kingdom 1685 website (static files)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import config
from .db import init_db
from . import users
from .control import worker
from .api import (auth, control, events, mapdata, players, rallies, scans,
                  schedules, stats)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    users.ensure_bootstrap_admin()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Rise of Kingdoms 1685 Tracker", version="1.0.0",
              lifespan=lifespan)

# Allow a separately-hosted website (e.g. GitHub Pages) to call this API.
if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/api/health")
def health():
    return {"ok": True, "kingdom": config.KINGDOM_ID,
            "control_backend": config.CONTROL_BACKEND}


@app.get("/api/config")
def public_config():
    return {"kingdom": config.KINGDOM_ID, "control_backend": config.CONTROL_BACKEND}


for r in (auth.router, stats.router, players.router, scans.router,
          control.router, mapdata.router, rallies.router,
          schedules.router, events.router):
    app.include_router(r)

# The website. Mounted last so /api/* routes win. html=True serves index.html.
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
