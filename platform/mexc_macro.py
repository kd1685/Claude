"""
mexc_macro.py — free MEXC futures positioning / macro context.

Self-contained: stdlib + requests only. Does NOT import app.py.

These are POSITIONING / CONTEXT data — funding rate, open interest, and (where
available) long/short ratio. They describe how the crowd is positioned, NOT a
profit signal. Read them for context, never as a trade trigger.

MEXC's public contract API exposes funding rate well and a coarse open-interest
field on the ticker. It does NOT publicly expose a global long/short account
ratio. Binance offers a richer long/short ratio and OI history endpoint
(futures/data/globalLongShortAccountRatio, openInterestHist) — a better source
and a likely future addition.

Every function is resilient: it returns None / empty on any error and never
raises, so callers can wire it into an endpoint without try/except.
"""

import requests

MEXC = "https://contract.mexc.com"
TIMEOUT = 15


def funding_rate(symbol):
    """GET /api/v1/contract/funding_rate/{symbol}.

    Returns {"rate": float (per-8h, as %), "annualized": float %, "bias": str}
    or None on any error. annualized = rate% * 3 * 365 (3 funding windows/day).
    """
    try:
        d = requests.get(f"{MEXC}/api/v1/contract/funding_rate/{symbol}",
                         timeout=TIMEOUT).json().get("data", {})
        raw = d.get("fundingRate")
        if raw is None:
            return None
        rate_pct = float(raw) * 100.0            # API returns a fraction
        annualized = rate_pct * 3 * 365
        if rate_pct > 0.001:
            bias = "longs pay shorts (crowded long)"
        elif rate_pct < -0.001:
            bias = "shorts pay longs (crowded short)"
        else:
            bias = "neutral"
        return {"rate": round(rate_pct, 6),
                "annualized": round(annualized, 2),
                "bias": bias}
    except Exception:
        return None


def open_interest(symbol):
    """GET /api/v1/contract/ticker?symbol={symbol}, read an OI-like field.

    MEXC ticker carries holdVol (open positions) and amount24 (24h notional).
    Returns {"oi": float or None, "raw": <field used>}; {"oi": None} if absent.
    """
    try:
        d = requests.get(f"{MEXC}/api/v1/contract/ticker",
                         params={"symbol": symbol}, timeout=TIMEOUT).json().get("data", {})
        # ticker may come back as a dict or a single-element list
        if isinstance(d, list):
            d = d[0] if d else {}
        for field in ("holdVol", "amount24"):
            val = d.get(field)
            if val is not None:
                try:
                    return {"oi": float(val), "raw": field}
                except Exception:
                    pass
        return {"oi": None}
    except Exception:
        return {"oi": None}


def long_short_ratio(symbol):
    """Global long/short account ratio.

    MEXC's public contract API does not expose a long/short account ratio, so
    we do not fabricate one — return None. Binance's
    futures/data/globalLongShortAccountRatio is the better source (future
    addition).
    """
    return None


def macro(symbol):
    """Bundle the positioning/context data for one symbol."""
    return {
        "funding": funding_rate(symbol),
        "open_interest": open_interest(symbol),
        "long_short": long_short_ratio(symbol),
    }
