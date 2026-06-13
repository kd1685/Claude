"""exchanges.py — Exchange connectors for Ascent Terminal.

Provides a thin async wrapper around the ccxt library so the rest of the
platform can call exchange operations without caring about which venue is
being used.

Supported exchanges (extend EXCHANGE_MAP to add more):
  - Binance  (BINANCE_API_KEY / BINANCE_SECRET)
  - MEXC     (MEXC_API_KEY / MEXC_SECRET)
  - Bybit    (BYBIT_API_KEY / BYBIT_SECRET)

All exchange objects are created once at import time (lazy-ish: only the
exchanges whose keys are present in the environment are instantiated).
"""

from __future__ import annotations

import logging
import os
from typing import Any

try:
    import ccxt.async_support as ccxt
except ImportError:  # pragma: no cover
    ccxt = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exchange registry
# ---------------------------------------------------------------------------

EXCHANGE_MAP: dict[str, Any] = {}


def _build_exchange(name: str, api_key: str, secret: str) -> Any | None:
    if not ccxt:
        logger.warning("ccxt not installed — exchange '%s' unavailable.", name)
        return None
    if not api_key or not secret:
        return None
    cls = getattr(ccxt, name, None)
    if cls is None:
        logger.warning("ccxt has no exchange '%s'.", name)
        return None
    return cls({"apiKey": api_key, "secret": secret, "enableRateLimit": True})


# Build at module load
for _name, _key_env, _secret_env in [
    ("binance", "BINANCE_API_KEY", "BINANCE_SECRET"),
    ("mexc", "MEXC_API_KEY", "MEXC_SECRET"),
    ("bybit", "BYBIT_API_KEY", "BYBIT_SECRET"),
]:
    ex = _build_exchange(_name, os.getenv(_key_env, ""), os.getenv(_secret_env, ""))
    if ex:
        EXCHANGE_MAP[_name] = ex
        logger.info("Exchange '%s' initialised.", _name)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def fetch_ticker(exchange_name: str, symbol: str) -> dict[str, Any]:
    ex = EXCHANGE_MAP.get(exchange_name)
    if ex is None:
        return {"error": f"Exchange '{exchange_name}' not configured."}
    return await ex.fetch_ticker(symbol)


async def fetch_order_book(exchange_name: str, symbol: str, limit: int = 20) -> dict[str, Any]:
    ex = EXCHANGE_MAP.get(exchange_name)
    if ex is None:
        return {"error": f"Exchange '{exchange_name}' not configured."}
    return await ex.fetch_order_book(symbol, limit)


async def fetch_ohlcv(
    exchange_name: str, symbol: str, timeframe: str = "1h", limit: int = 200
) -> list[list]:
    ex = EXCHANGE_MAP.get(exchange_name)
    if ex is None:
        return []
    return await ex.fetch_ohlcv(symbol, timeframe, limit=limit)


async def close_all() -> None:
    """Close all exchange connections (call on app shutdown)."""
    for ex in EXCHANGE_MAP.values():
        try:
            await ex.close()
        except Exception:  # noqa: BLE001
            pass
