"""macro_data.py — Macro economic data provider for Ascent Terminal.

Fetches key macro indicators from public APIs:
  - US Treasury yields (FRED / alternative public source)
  - Fear & Greed Index (alternative.me)
  - Global M2 proxy (cached, updated daily)

All data is cached to avoid hammering upstream APIs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}  # key -> (timestamp, data)


def _cached(key: str, ttl: float) -> Any | None:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < ttl:
        return entry[1]
    return None


def _store(key: str, data: Any) -> None:
    _cache[key] = (time.monotonic(), data)


# ---------------------------------------------------------------------------
# Fear & Greed Index
# ---------------------------------------------------------------------------


async def get_fear_greed() -> dict[str, Any]:
    """Return the current Crypto Fear & Greed Index."""
    cached = _cached("fear_greed", 300)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=1")
        data = resp.json()["data"][0]
        result = {
            "value": int(data["value"]),
            "classification": data["value_classification"],
            "timestamp": data["timestamp"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fear & Greed fetch failed: %s", exc)
        result = {"value": None, "classification": "unknown", "timestamp": None}
    _store("fear_greed", result)
    return result


# ---------------------------------------------------------------------------
# US Treasury yields (10-year)
# ---------------------------------------------------------------------------


async def get_treasury_yield() -> dict[str, Any]:
    """Return the latest 10-year US Treasury yield from stlouisfed (FRED)."""
    cached = _cached("treasury", 3600)
    if cached is not None:
        return cached
    # FRED public API (no key for basic observations)
    url = (
        "https://fred.stlouisfed.org/graph/fredgraph.csv"
        "?id=DGS10"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
        lines = resp.text.strip().split("\n")
        last = lines[-1].split(",")
        result = {"date": last[0], "yield_pct": float(last[1]) if last[1] != "." else None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Treasury yield fetch failed: %s", exc)
        result = {"date": None, "yield_pct": None}
    _store("treasury", result)
    return result


# ---------------------------------------------------------------------------
# Unified macro snapshot
# ---------------------------------------------------------------------------


async def get_macro_snapshot() -> dict[str, Any]:
    """Fetch all macro indicators concurrently and return a unified dict."""
    fear_greed, treasury = await asyncio.gather(
        get_fear_greed(),
        get_treasury_yield(),
    )
    return {"fear_greed": fear_greed, "treasury_10y": treasury}
