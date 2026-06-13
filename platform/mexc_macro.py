"""mexc_macro.py — MEXC-specific macro data for Ascent Terminal.

Fetches funding rates and open interest for major perpetual contracts
from the MEXC public API (no API key required).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MEXC_BASE = "https://contract.mexc.com/api/v1/contract"
CACHE_TTL = 30  # seconds

_cache: dict[str, Any] = {}
_cache_ts: float = 0.0

TARGET_SYMBOLS = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT"]


async def get_mexc_macro() -> dict[str, Any]:
    """Return funding rates and open interest for key perp contracts."""
    global _cache, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < CACHE_TTL and _cache:
        return _cache

    result: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for sym in TARGET_SYMBOLS:
            try:
                resp = await client.get(f"{MEXC_BASE}/funding_rate/{sym}")
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    result[sym] = {
                        "funding_rate": data.get("fundingRate"),
                        "next_funding_time": data.get("nextSettleTime"),
                    }
                # Open interest
                oi_resp = await client.get(f"{MEXC_BASE}/open_interest/{sym}")
                if oi_resp.status_code == 200:
                    oi_data = oi_resp.json().get("data", {})
                    result.setdefault(sym, {})["open_interest"] = oi_data.get("openInterest")
            except httpx.RequestError as exc:
                logger.warning("MEXC fetch error for %s: %s", sym, exc)

    _cache = result
    _cache_ts = now
    return result
