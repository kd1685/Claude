"""orderflow.py — Order-flow analysis for Ascent Terminal.

Fetches the Binance order book for a set of tracked symbols and computes
simple order-flow metrics:
  - bid/ask imbalance
  - large-order clusters (walls)
  - cumulative delta proxy
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BINANCE_DEPTH = "https://api.binance.com/api/v3/depth"
TRACKED_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
CALL_LIMIT = 20  # order book depth
CACHE_TTL = 5  # seconds

_cache: dict[str, Any] = {}
_cache_ts: float = 0.0


def _imbalance(bids: list, asks: list) -> float:
    bid_vol = sum(float(b[1]) for b in bids)
    ask_vol = sum(float(a[1]) for a in asks)
    total = bid_vol + ask_vol
    return round((bid_vol - ask_vol) / total, 4) if total else 0.0


def _walls(orders: list, threshold_multiplier: float = 5.0) -> list[dict]:
    """Find order-book walls (orders significantly larger than the mean)."""
    if not orders:
        return []
    sizes = [float(o[1]) for o in orders]
    mean = sum(sizes) / len(sizes)
    return [
        {"price": float(o[0]), "size": float(o[1])}
        for o in orders
        if float(o[1]) >= mean * threshold_multiplier
    ]


async def _fetch_depth(symbol: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(BINANCE_DEPTH, params={"symbol": symbol, "limit": CALL_LIMIT})
    if resp.status_code != 200:
        return {}
    data = resp.json()
    bids = data.get("bids", [])
    asks = data.get("asks", [])
    return {
        "symbol": symbol,
        "imbalance": _imbalance(bids, asks),
        "bid_walls": _walls(bids),
        "ask_walls": _walls(asks),
        "best_bid": float(bids[0][0]) if bids else None,
        "best_ask": float(asks[0][0]) if asks else None,
    }


async def get_orderflow_snapshot() -> list[dict[str, Any]]:
    """Return order-flow metrics for all tracked symbols."""
    global _cache, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < CACHE_TTL and _cache:
        return _cache  # type: ignore[return-value]
    results = await asyncio.gather(*[_fetch_depth(s) for s in TRACKED_SYMBOLS], return_exceptions=True)
    data = [r for r in results if isinstance(r, dict)]
    _cache = data  # type: ignore[assignment]
    _cache_ts = now
    return data
