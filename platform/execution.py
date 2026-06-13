"""execution.py — Order execution bridge for Ascent Terminal.

Exposes POST /execution/order which:
  1. Validates the inbound request (HMAC signature optional but recommended).
  2. Routes the order to the appropriate exchange via exchanges.py.
  3. Returns the exchange response.

This module is intentionally minimal — it is a ‘thin bridge’ between the
platform and the exchange.  Risk management (position sizing, max exposure)
should be enforced upstream in the trading strategy / TradingView alert.

Security:
  Set EXECUTION_SECRET in .env.  Callers must include the header:
    X-Execution-Signature: <HMAC-SHA256(body, EXECUTION_SECRET)>
  If EXECUTION_SECRET is empty the signature check is skipped (dev mode).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_tier
from exchanges import EXCHANGE_MAP, fetch_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/execution", tags=["execution"])

EXECUTION_SECRET = os.getenv("EXECUTION_SECRET", "")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"] = "market"
    amount: float = Field(..., gt=0)
    price: float | None = None  # required for limit orders
    reduce_only: bool = False


class OrderResponse(BaseModel):
    exchange: str
    symbol: str
    order_id: str | None
    status: str
    raw: dict


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def _verify_signature(body: bytes, signature: str) -> bool:
    if not EXECUTION_SECRET:
        return True  # skip in dev mode
    expected = hmac.new(EXECUTION_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/order", response_model=OrderResponse)
async def place_order(
    request: Request,
    order: OrderRequest,
    x_execution_signature: str = Header(default=""),
    _user=Depends(require_tier("architect")),  # architect-only
):
    """Place an order on the specified exchange."""
    body = await request.body()
    if not _verify_signature(body, x_execution_signature):
        raise HTTPException(status_code=401, detail="Invalid execution signature.")

    ex = EXCHANGE_MAP.get(order.exchange)
    if ex is None:
        raise HTTPException(
            status_code=400,
            detail=f"Exchange '{order.exchange}' not configured or not available.",
        )

    try:
        if order.order_type == "market":
            result = await ex.create_order(
                order.symbol,
                "market",
                order.side,
                order.amount,
                params={"reduceOnly": order.reduce_only},
            )
        else:
            if order.price is None:
                raise HTTPException(status_code=422, detail="'price' required for limit orders.")
            result = await ex.create_order(
                order.symbol,
                "limit",
                order.side,
                order.amount,
                order.price,
                params={"reduceOnly": order.reduce_only},
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Exchange error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return OrderResponse(
        exchange=order.exchange,
        symbol=order.symbol,
        order_id=result.get("id"),
        status=result.get("status", "unknown"),
        raw=result,
    )


@router.get("/ticker")
async def get_ticker(
    exchange: str = "binance",
    symbol: str = "BTC/USDT",
    _user=Depends(require_tier("scout")),
):
    """Fetch live ticker from the specified exchange."""
    return await fetch_ticker(exchange, symbol)
