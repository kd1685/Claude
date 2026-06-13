"""forex_data.py — Forex rates data provider for Ascent Terminal.

Fetches live forex rates from the exchangerate.host public API (no key
required for basic usage) and caches them for 60 seconds.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.exchangerate.host"
CACHE_TTL = 60  # seconds

_cache: dict[str, Any] = {}
_cache_ts: float = 0.0
_lock = asyncio.Lock()


async def get_forex_rates(base: str = "USD", symbols: str = "EUR,GBP,JPY,AUD,CAD,CHF") -> dict[str, Any]:
    """Return cached (or freshly fetched) forex rates."""
    global _cache, _cache_ts
    async with _lock:
        now = time.monotonic()
        if now - _cache_ts < CACHE_TTL and _cache:
            return _cache
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/live",
                    params={"source": base, "currencies": symbols},
                )
            if resp.status_code == 200:
                data = resp.json()
                _cache = data.get("quotes", {})
                _cache_ts = now
            else:
                logger.warning("Forex API returned %s", resp.status_code)
        except httpx.RequestError as exc:
            logger.warning("Forex fetch failed: %s", exc)
    return _cache
