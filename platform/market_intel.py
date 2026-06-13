"""market_intel.py — Unified market intelligence WebSocket hub.

The MarketIntelHub class:
  - Manages connected WebSocket clients (with tier awareness)
  - Periodically fetches data from all data providers
  - Broadcasts a unified snapshot to all connected clients
  - Maintains the latest snapshot for REST polling
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import WebSocket

from forex_data import get_forex_rates
from liquidations import _buffer as liquidation_buffer
from macro_data import get_macro_snapshot
from mexc_macro import get_mexc_macro
from orderflow import get_orderflow_snapshot

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 15  # seconds between hub broadcasts


class MarketIntelHub:
    """Central broadcast hub for real-time market intelligence."""

    def __init__(self) -> None:
        self._clients: dict[WebSocket, str] = {}  # ws -> tier
        self._snapshot: dict[str, Any] = {}
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket, tier: str) -> None:
        await websocket.accept()
        self._clients[websocket] = tier
        logger.info("WS client connected (tier=%s). Total=%d", tier, len(self._clients))
        # Send current snapshot immediately on connect
        if self._snapshot:
            try:
                await websocket.send_text(json.dumps(self._snapshot))
            except Exception:  # noqa: BLE001
                pass
        # Start background task if not running
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._broadcast_loop())

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.pop(websocket, None)
        logger.info("WS client disconnected. Total=%d", len(self._clients))

    def latest_snapshot(self) -> dict[str, Any]:
        return self._snapshot

    # ------------------------------------------------------------------
    # Data aggregation
    # ------------------------------------------------------------------

    async def _build_snapshot(self) -> dict[str, Any]:
        macro, forex, mexc = await asyncio.gather(
            get_macro_snapshot(),
            get_forex_rates(),
            get_mexc_macro(),
            return_exceptions=True,
        )
        orderflow = await get_orderflow_snapshot()
        liquidations = list(liquidation_buffer)[:20]

        return {
            "timestamp": int(time.time()),
            "macro": macro if not isinstance(macro, Exception) else {},
            "forex": forex if not isinstance(forex, Exception) else {},
            "mexc": mexc if not isinstance(mexc, Exception) else {},
            "orderflow": orderflow,
            "liquidations": liquidations,
        }

    # ------------------------------------------------------------------
    # Broadcast loop
    # ------------------------------------------------------------------

    async def _broadcast_loop(self) -> None:
        while self._clients:
            try:
                self._snapshot = await self._build_snapshot()
                dead: list[WebSocket] = []
                for ws in list(self._clients):
                    try:
                        await ws.send_text(json.dumps(self._snapshot))
                    except Exception:  # noqa: BLE001
                        dead.append(ws)
                for ws in dead:
                    self.disconnect(ws)
            except Exception as exc:  # noqa: BLE001
                logger.error("Hub broadcast error: %s", exc)
            await asyncio.sleep(REFRESH_INTERVAL)
