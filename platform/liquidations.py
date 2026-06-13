"""liquidations.py — Liquidation data provider for Ascent Terminal.

Subscribes to Binance WebSocket liquidation stream and maintains an
in-memory rolling buffer of recent liquidation events.  The REST
endpoint /liquidations/recent returns the buffer.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
from typing import Any

import websockets
from fastapi import APIRouter, Depends

from auth import require_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/liquidations", tags=["liquidations"])

BINANCE_LIQUIDATION_WS = "wss://fstream.binance.com/ws/!forceOrder@arr"
MAX_BUFFER = 500

_buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=MAX_BUFFER)
_ws_task: asyncio.Task | None = None


async def _listen() -> None:
    """Background task: subscribe to Binance liquidation stream."""
    while True:
        try:
            async with websockets.connect(BINANCE_LIQUIDATION_WS) as ws:
                logger.info("Liquidation WS connected.")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        order = msg.get("o", {})
                        _buffer.appendleft(
                            {
                                "symbol": order.get("s"),
                                "side": order.get("S"),
                                "quantity": float(order.get("q", 0)),
                                "price": float(order.get("ap", 0)),
                                "time": order.get("T"),
                            }
                        )
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Liquidation WS error: %s — reconnecting in 5 s", exc)
            await asyncio.sleep(5)


def start_listener() -> None:
    """Schedule the background listener (call from app startup)."""
    global _ws_task
    if _ws_task is None or _ws_task.done():
        _ws_task = asyncio.create_task(_listen())


@router.get("/recent")
async def recent_liquidations(
    limit: int = 50,
    _user=Depends(require_tier("scout")),
):
    """Return the most recent liquidation events (up to 500)."""
    return list(_buffer)[:limit]
