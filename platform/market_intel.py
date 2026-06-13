"""
market_intel.py — EdgeFinder-style market-context layer for Ascent Terminal.

Self-contained (stdlib math + requests only). Does NOT import app.py.
Everything here is *market analysis / context* — never a profit guarantee.

  - fear_greed()           crypto-WIDE Fear & Greed gauge (one number)
  - composite_score(c)     per-coin 0-9 technical score + direction
  - multi_tf(symbol)       daily vs 4h trend alignment

The composite score blends EMA9/EMA21 cross, RSI14, MACD histogram sign,
Bollinger %B, and EMA30 trend. It is a neutral technical read, not advice.
"""

import math
import requests

FNG_URL = "https://api.alternative.me/fng/?limit=1"
MEXC = "https://contract.mexc.com"


# ---------------------------------------------------------------------------
# Indicator primitives (inline, stdlib only)
# ---------------------------------------------------------------------------

def _ema(values, period):
    """EMA series; returns [] if not enough data. Aligned to values[period-1:]."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _ema_last(values, period):
    e = _ema(values, period)
    return e[-1] if e else None


def _rsi(values, period=14):
    """Wilder's RSI, latest value. Returns None if not enough data."""
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        ch = values[i] - values[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd_hist(values, fast=12, slow=26, signal=9):
    """MACD histogram (latest). Returns None if not enough data."""
    if len(values) < slow + signal:
        return None
    ef = _ema(values, fast)
    es = _ema(values, slow)
    if not ef or not es:
        return None
    # align both EMA series to the same (slow-based) index
    off = slow - fast
    macd_line = [ef[off + i] - es[i] for i in range(len(es))]
    sig = _ema(macd_line, signal)
    if not sig:
        return None
    return macd_line[-1] - sig[-1]


def _bollinger_pctb(values, period=20, mult=2.0):
    """Bollinger %B (latest): 0 = lower band, 1 = upper band. None if short."""
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    var = sum((v - mean) ** 2 for v in window) / period
    sd = math.sqrt(var)
    if sd == 0:
        return 0.5
    upper = mean + mult * sd
    lower = mean - mult * sd
    return (values[-1] - lower) / (upper - lower)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def fear_greed():
    """Crypto-wide Fear & Greed index. Returns {"value":int,"label":str} or None."""
    try:
        r = requests.get(FNG_URL, timeout=10)
        data = r.json().get("data", [])
        if not data:
            return None
        item = data[0]
        return {"value": int(item["value"]),
                "label": str(item.get("value_classification", "")).strip()}
    except Exception:
        return None


def composite_score(candles):
    """0-9 technical score + direction from daily OHLC candles (newest last).

    Five components, each contributing up to ~1.8 pts (5 * 1.8 = 9):
      ema   EMA9 vs EMA21 (fast-trend cross)
      rsi   RSI14 (momentum)
      macd  MACD histogram sign (momentum confirmation)
      bb    Bollinger %B position
      trend price vs EMA30 (primary trend)

    Returns {"score":float,"direction":"LONG"/"SHORT","components":{...}} or None.
    This is an ANALYSIS read of current technicals, not a profit signal.
    """
    if not candles or len(candles) < 35:
        return None
    closes = [c["close"] for c in candles]
    W = 1.8  # per-component weight (5 * 1.8 = 9.0 max)

    comp = {}

    # 1) EMA9 vs EMA21 trend cross
    e9 = _ema_last(closes, 9)
    e21 = _ema_last(closes, 21)
    if e9 is not None and e21 is not None:
        comp["ema"] = round(W if e9 > e21 else 0.0, 2)
    else:
        comp["ema"] = round(W / 2, 2)

    # 2) RSI14 — scaled 0..1 across the 30..70 band, clamped
    rsi = _rsi(closes, 14)
    if rsi is not None:
        scaled = (rsi - 30) / 40.0
        scaled = max(0.0, min(1.0, scaled))
        comp["rsi"] = round(W * scaled, 2)
    else:
        comp["rsi"] = round(W / 2, 2)

    # 3) MACD histogram sign
    hist = _macd_hist(closes)
    if hist is not None:
        comp["macd"] = round(W if hist > 0 else 0.0, 2)
    else:
        comp["macd"] = round(W / 2, 2)

    # 4) Bollinger %B position (clamped 0..1)
    pctb = _bollinger_pctb(closes, 20)
    if pctb is not None:
        comp["bb"] = round(W * max(0.0, min(1.0, pctb)), 2)
    else:
        comp["bb"] = round(W / 2, 2)

    # 5) Primary trend: price vs EMA30
    e30 = _ema_last(closes, 30)
    if e30 is not None:
        comp["trend"] = round(W if closes[-1] > e30 else 0.0, 2)
    else:
        comp["trend"] = round(W / 2, 2)

    score = round(sum(comp.values()), 1)
    direction = "LONG" if score >= W * 2.5 else "SHORT"  # >= half of max
    return {"score": score, "direction": direction, "components": comp}


def _trend_from_candles(candles):
    """LONG/SHORT from price vs EMA30; None if insufficient."""
    if not candles or len(candles) < 31:
        return None
    closes = [c["close"] for c in candles]
    e30 = _ema_last(closes, 30)
    if e30 is None:
        return None
    return "LONG" if closes[-1] > e30 else "SHORT"


def fetch_4h(symbol, exchange="binance", limit=120):
    """4h candles, broker-neutral: ccxt for any exchange, MEXC native fallback.
    Returns [{time,open,high,low,close}]."""
    if exchange != "mexc":
        try:
            import ccxt
            if hasattr(ccxt, exchange):
                ex = getattr(ccxt, exchange)({"enableRateLimit": True})
                rows = ex.fetch_ohlcv(symbol.replace("_", "/"), timeframe="4h", limit=limit)
                return [{"time": int(r[0]/1000), "open": float(r[1]), "high": float(r[2]),
                         "low": float(r[3]), "close": float(r[4])} for r in rows]
        except Exception:
            pass   # fall through to MEXC native
    return _fetch_mexc_4h(symbol, limit)


def _fetch_mexc_4h(symbol, limit=120):
    """Direct MEXC contract 4h kline -> [{time,open,high,low,close}]."""
    try:
        d = requests.get(f"{MEXC}/api/v1/contract/kline/{symbol}",
                         params={"interval": "Hour4", "limit": limit},
                         timeout=15).json().get("data", {})
    except Exception:
        return []
    t = d.get("time", [])
    o, h, l, c = (d.get(k, []) for k in ("open", "high", "low", "close"))
    out = []
    for i in range(len(t)):
        try:
            out.append({"time": int(t[i]), "open": float(o[i]), "high": float(h[i]),
                        "low": float(l[i]), "close": float(c[i])})
        except Exception:
            pass
    return out


def multi_tf(symbol, exchange="mexc"):
    """Daily vs 4h trend alignment (price vs EMA30 on each timeframe).

    Returns {"d1":..,"h4":..,"aligned":bool}. Parts may be None on failure.
    Imports exchanges lazily (module-level data layer) — does not touch app.py.
    """
    d1 = h4 = None
    try:
        import exchanges
        d1 = _trend_from_candles(exchanges.fetch_daily(symbol, exchange, 60))
    except Exception:
        d1 = None
    try:
        h4 = _trend_from_candles(_fetch_mexc_4h(symbol))
    except Exception:
        h4 = None
    aligned = (d1 is not None and h4 is not None and d1 == h4)
    return {"d1": d1, "h4": h4, "aligned": aligned}
