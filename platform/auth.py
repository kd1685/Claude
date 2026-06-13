"""auth.py — FastAPI application entry-point for Ascent Terminal.

Handles:
  - API-key authentication + tier enforcement
  - REST endpoints for market data, backtesting, execution, AI analysis
  - WebSocket hub (real-time market intelligence)
  - Stripe billing webhooks
  - Static file serving (download page)

Run with:
    uvicorn auth:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_analyst import router as ai_router
from backtest import router as backtest_router
from execution import router as execution_router
from market_intel import MarketIntelHub
from store_db import DatabaseManager
from webhook_store import router as webhook_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ACCESS_KEYS_RAW = os.getenv("ACCESS_KEYS", "")
ACCESS_KEYS: set[str] = set(filter(None, ACCESS_KEYS_RAW.split(",")))

KEYS_FILE = Path("keys.json")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_MAP: dict[str, str] = {
    os.getenv("STRIPE_PRICE_SCOUT", ""): "scout",
    os.getenv("STRIPE_PRICE_OPERATOR", ""): "operator",
    os.getenv("STRIPE_PRICE_ARCHITECT", ""): "architect",
}

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


# ---------------------------------------------------------------------------
# Key store helpers
# ---------------------------------------------------------------------------


def _load_keys() -> dict[str, dict]:
    """Load keys.json — returns {} on missing / malformed file."""
    try:
        return json.loads(KEYS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_keys(keys: dict[str, dict]) -> None:
    KEYS_FILE.write_text(json.dumps(keys, indent=2))


def _key_tier(api_key: str) -> str | None:
    """Return the tier for *api_key* or None if unknown / revoked."""
    # Env-var keys are architect-tier (legacy / admin)
    if api_key in ACCESS_KEYS:
        return "architect"
    # DEMO key — only active when ACCESS_KEYS env is empty
    if api_key == "DEMO-KEY" and not ACCESS_KEYS:
        return "scout"
    store = _load_keys()
    entry = store.get(api_key)
    if entry and entry.get("active", True):
        return entry.get("tier", "scout")
    return None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Ascent Terminal", version="1.0.0")

app.include_router(ai_router)
app.include_router(backtest_router)
app.include_router(execution_router)
app.include_router(webhook_router)

_static = Path("static")
if _static.is_dir():
    app.mount("/static", StaticFiles(directory="static"), name="static")

db = DatabaseManager()
hub = MarketIntelHub()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

TIER_RANK = {"scout": 1, "operator": 2, "architect": 3}


class AuthenticatedUser(BaseModel):
    api_key: str
    tier: str


async def get_current_user(x_api_key: str = Header(...)) -> AuthenticatedUser:
    tier = _key_tier(x_api_key)
    if tier is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    return AuthenticatedUser(api_key=x_api_key, tier=tier)


def require_tier(minimum: str):
    """Dependency factory — raises 403 if user tier is below *minimum*."""
    async def _check(user: AuthenticatedUser = Depends(get_current_user)):
        if TIER_RANK.get(user.tier, 0) < TIER_RANK.get(minimum, 99):
            raise HTTPException(
                status_code=403,
                detail=f"Requires '{minimum}' tier or above (you have '{user.tier}').",
            )
        return user
    return _check


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": int(time.time())}


# ---------------------------------------------------------------------------
# Market data endpoints
# ---------------------------------------------------------------------------


@app.get("/market/snapshot")
async def market_snapshot(user: AuthenticatedUser = Depends(get_current_user)):
    """Latest cached market intelligence snapshot."""
    return hub.latest_snapshot()


@app.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """Real-time market intelligence stream."""
    api_key = websocket.query_params.get("api_key", "")
    tier = _key_tier(api_key)
    if tier is None:
        await websocket.close(code=4001)
        return
    await hub.connect(websocket, tier)
    try:
        while True:
            await asyncio.sleep(30)  # keep-alive; hub pushes data
    except WebSocketDisconnect:
        hub.disconnect(websocket)


# ---------------------------------------------------------------------------
# Stripe billing
# ---------------------------------------------------------------------------


@app.post("/billing/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe subscription lifecycle events."""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=501, detail="Billing not configured.")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")

    etype = event["type"]
    data = event["data"]["object"]

    if etype in ("customer.subscription.created", "customer.subscription.updated"):
        price_id = data["items"]["data"][0]["price"]["id"]
        tier = STRIPE_PRICE_MAP.get(price_id, "scout")
        customer_id = data["customer"]
        # Store / update key linked to customer
        keys = _load_keys()
        # Find existing key for customer or create a stub
        for key, entry in keys.items():
            if entry.get("stripe_customer") == customer_id:
                entry["tier"] = tier
                entry["active"] = True
                break
        else:
            import secrets
            new_key = "AT-" + secrets.token_hex(16)
            keys[new_key] = {"tier": tier, "active": True, "stripe_customer": customer_id}
        _save_keys(keys)

    elif etype == "customer.subscription.deleted":
        customer_id = data["customer"]
        keys = _load_keys()
        for entry in keys.values():
            if entry.get("stripe_customer") == customer_id:
                entry["active"] = False
        _save_keys(keys)

    return {"received": True}


# ---------------------------------------------------------------------------
# Download page
# ---------------------------------------------------------------------------


@app.get("/download", response_class=HTMLResponse)
async def download_page():
    html_path = Path("static/download.html")
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Download page not found.</h1>", status_code=404)
