"""FastAPI application: REST API + the Kingdom 1685 website (static files)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import config
from .db import init_db
from .control import worker
from .api import control, mapdata, players, rallies, scans, stats

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Rise of Kingdoms 1685 Tracker", version="1.0.0",
              lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"ok": True, "kingdom": config.KINGDOM_ID,
            "control_backend": config.CONTROL_BACKEND}


@app.get("/api/config")
def public_config():
    return {"kingdom": config.KINGDOM_ID, "control_backend": config.CONTROL_BACKEND}


for r in (stats.router, players.router, scans.router, control.router,
          mapdata.router, rallies.router):
    app.include_router(r)

# The website. Mounted last so /api/* routes win. html=True serves index.html.
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
