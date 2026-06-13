"""webhook_store.py — TradingView webhook receiver for Ascent Terminal.

Exposes POST /webhook/tradingview which:
  1. Validates the shared secret (TV_WEBHOOK_SECRET env var).
  2. Parses the alert payload.
  3. Persists the event to PostgreSQL via store_db.
  4. Optionally forwards to the execution bridge.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from store_db import DatabaseManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET", "")

db = DatabaseManager()


class TVAlert(BaseModel):
    secret: str = ""
    symbol: str
    action: str  # "buy" | "sell" | "close"
    api_key: str = ""
    extra: dict[str, Any] = {}


@router.post("/tradingview")
async def tradingview_webhook(alert: TVAlert, request: Request):
    """Receive and store a TradingView alert."""
    # Validate secret if configured
    if TV_WEBHOOK_SECRET:
        if not hmac.compare_digest(alert.secret, TV_WEBHOOK_SECRET):
            raise HTTPException(status_code=403, detail="Invalid webhook secret.")

    # Persist
    await db.init_schema()
    # We store under the api_key embedded in the alert (or 'anonymous')
    api_key = alert.api_key or "anonymous"
    payload = alert.model_dump()

    # Inline DB insert (avoiding circular import with auth)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    async with db._session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO webhook_events (api_key, symbol, action, payload) "
                    "VALUES (:k, :s, :a, :p::jsonb)"
                ),
                {"k": api_key, "s": alert.symbol, "a": alert.action, "p": str(payload)},
            )

    logger.info("Webhook received: %s %s", alert.symbol, alert.action)
    return {"received": True, "symbol": alert.symbol, "action": alert.action}
