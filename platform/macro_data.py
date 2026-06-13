"""
macro_data.py — multi-broker macro / positioning context.

Self-contained: stdlib + requests only. Does NOT import any other project file.

These are POSITIONING / CONTEXT data — funding rate, open interest, long/short
account ratio, and BTC dominance. They describe how the crowd is positioned and
what the market backdrop looks like, NOT a profit signal. Read them for
analysis context, never as a trade trigger.

Binance is the PRIMARY public data source because its public futures-data API
is the richest (premiumIndex, openInterest, globalLongShortAccountRatio).
MEXC is retained as a fallback for funding rate only. BTC dominance comes from
CoinGecko's free global endpoint.

Symbols arrive in internal "BTC_USDT" form; Binance futures uses "BTCUSDT"
(underscore stripped), MEXC uses the underscored form as-is.

Every function is resilient: it returns None or a partial dict on any error
and never raises, so callers can wire it into an endpoint without try/except.
"""

import requests

BINANCE_FAPI = "https://fapi.binance.com"
MEXC = "https://contract.mexc.com"
COINGECKO = "https://api.coingecko.com"
TIMEOUT = 15


def _binance_symbol(symbol):
    """Convert internal 'BTC_USDT' form to Binance futures 'BTCUSDT'."""
    return symbol.replace("_", "")


def _funding_bias(rate_pct):
    if rate_pct > 0.001:
        return "crowded long (longs pay)"
    elif rate_pct < -0.001:
        return "crowded short (shorts pay)"
    return "neutral"


def _funding_binance(symbol):
    """Binance premiumIndex — 'lastFundingRate' is a fraction per 8h."""
    r = requests.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex",
                     params={"symbol": _binance_symbol(symbol)},
                     timeout=TIMEOUT).json()
    raw = r.get("lastFundingRate")
    if raw is None:
        return None
    return float(raw)


def _funding_mexc(symbol):
    """MEXC contract funding_rate — data.fundingRate is a fraction per 8h."""
    r = requests.get(f"{MEXC}/api/v1/contract/funding_rate/{symbol}",
                     timeout=TIMEOUT).json()
    raw = (r.get("data") or {}).get("fundingRate")
    if raw is None:
        return None
    return float(raw)


def funding_rate(symbol, source="binance"):
    """Funding rate with automatic cross-source fallback.

    Returns {"rate_pct": per-8h %, "annualized_pct": rate_pct * 3 * 365,
             "bias": str, "source": "binance"|"mexc"} or None on total failure.
    annualized assumes 3 funding windows/day.
    """
    fetchers = {"binance": _funding_binance, "mexc": _funding_mexc}
    order = ["binance", "mexc"] if source != "mexc" else ["mexc", "binance"]
    for src in order:
        try:
            frac = fetchers[src](symbol)
        except Exception:
            frac = None
        if frac is None:
            continue
        rate_pct = frac * 100.0
        return {"rate_pct": round(rate_pct, 6),
                "annualized_pct": round(rate_pct * 3 * 365, 2),
                "bias": _funding_bias(rate_pct),
                "source": src}
    return None


def open_interest(symbol):
    """Binance current open interest for the contract.

    Returns {"oi": float, "source": "binance"} or {"oi": None} on any error.
    """
    try:
        r = requests.get(f"{BINANCE_FAPI}/fapi/v1/openInterest",
                         params={"symbol": _binance_symbol(symbol)},
                         timeout=TIMEOUT).json()
        raw = r.get("openInterest")
        if raw is None:
            return {"oi": None}
        return {"oi": float(raw), "source": "binance"}
    except Exception:
        return {"oi": None}


def long_short_ratio(symbol):
    """Binance global long/short ACCOUNT ratio (retail positioning proxy).

    Returns {"ratio": float, "long_pct": float, "short_pct": float,
             "read": str} or None on any error. Thresholds: ratio > 1.5 =>
    "retail crowded long", ratio < 0.67 => "retail crowded short", else
    "balanced".
    """
    try:
        r = requests.get(
            f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio",
            params={"symbol": _binance_symbol(symbol),
                    "period": "1h", "limit": 1},
            timeout=TIMEOUT).json()
        if not isinstance(r, list) or not r:
            return None
        latest = r[-1]
        ratio = float(latest["longShortRatio"])
        if ratio > 1.5:
            read = "retail crowded long"
        elif ratio < 0.67:
            read = "retail crowded short"
        else:
            read = "balanced"
        return {"ratio": round(ratio, 4),
                "long_pct": round(float(latest["longAccount"]) * 100.0, 2),
                "short_pct": round(float(latest["shortAccount"]) * 100.0, 2),
                "read": read}
    except Exception:
        return None


def btc_dominance():
    """CoinGecko global market data — BTC share of total market cap.

    Returns {"btc_dominance_pct": float} or None on any error.
    """
    try:
        r = requests.get(f"{COINGECKO}/api/v3/global", timeout=TIMEOUT).json()
        raw = (r.get("data") or {}).get("market_cap_percentage", {}).get("btc")
        if raw is None:
            return None
        return {"btc_dominance_pct": round(float(raw), 2)}
    except Exception:
        return None


def macro(symbol):
    """Bundle the positioning/context data for one symbol."""
    return {
        "funding": funding_rate(symbol),
        "open_interest": open_interest(symbol),
        "long_short": long_short_ratio(symbol),
        "btc_dominance": btc_dominance(),
    }
