"""
exchanges.py — unified multi-broker data layer for Ascent Terminal.

MEXC is supported natively (no extra dependency). Every other exchange is
supported through `ccxt` (pip install ccxt) — Binance, Bybit, OKX, KuCoin,
Gate, Bitget, and ~100 more — behind the SAME fetch_daily() call. Adding a
broker is then config, not code.

  pip install ccxt          # enables all non-MEXC exchanges
"""

import requests

MEXC = "https://contract.mexc.com"

# Exchanges we expose by default (must exist in the installed ccxt build).
# Broad set of well-known exchanges; supported()/list_assets() filter to those
# actually present in the installed ccxt build at runtime.
PREFERRED = [
    "binance", "coinbase", "kraken", "bybit", "okx", "kucoin", "gateio",
    "bitget", "htx", "bitfinex", "cryptocom", "bingx", "mexc", "bitmart",
    "woo", "phemex", "bitmex", "deribit", "gemini", "poloniex", "hyperliquid",
]

# Cache of ccxt load_markets() results, keyed by exchange id (load_markets is slow).
_MARKETS_CACHE = {}

# Cache of ccxt fetch_tickers() results, keyed by (exchange, quote). TTL below.
_TICKERS_CACHE = {}
_TICKERS_TTL = 300          # 5 min — movers don't need to be tick-fresh


def segments(exchange: str = "binance") -> dict:
    """Which market segments this exchange offers (from cached load_markets).
    e.g. {"spot": True, "swap": True}. All-False on error."""
    try:
        markets = _load_markets(exchange)
        spot = any(m.get("spot") for m in markets.values())
        swap = any(m.get("swap") for m in markets.values())
        return {"spot": bool(spot), "swap": bool(swap)}
    except Exception:
        return {"spot": False, "swap": False}


def top_tickers(exchange: str = "binance", quote: str = "USDT",
                mode: str = "volume", limit: int = 25,
                market_type: str = "spot") -> list:
    """Top-traded / top-movers view for the asset picker.

    mode: "volume"  -> highest 24h quote volume
          "gainers" -> biggest 24h % gain
          "losers"  -> biggest 24h % loss

    Returns [{"symbol": "BTC_USDT", "price": .., "change_pct": .., "qvol": ..}]
    sorted for the requested mode. [] on any error (never raises) — e.g. when
    ccxt is missing or the exchange doesn't support fetch_tickers.
    """
    import time as _time
    quote = (quote or "USDT").upper()
    market_type = market_type if market_type in ("spot", "swap") else "spot"
    key = (exchange, quote, market_type)
    now = _time.time()
    hit = _TICKERS_CACHE.get(key)
    if hit and now - hit["ts"] < _TICKERS_TTL:
        rows = hit["rows"]
    else:
        rows = _fetch_ticker_rows(exchange, quote, market_type)
        if rows:                                  # keep last good data on failure
            _TICKERS_CACHE[key] = {"rows": rows, "ts": now}
        elif hit:
            rows = hit["rows"]
    if not rows:
        return []
    if mode == "gainers":
        rows = sorted(rows, key=lambda r: r["change_pct"] if r["change_pct"] is not None else -1e9, reverse=True)
    elif mode == "losers":
        rows = sorted(rows, key=lambda r: r["change_pct"] if r["change_pct"] is not None else 1e9)
    else:                                         # volume (default)
        rows = sorted(rows, key=lambda r: r["qvol"] or 0, reverse=True)
    return rows[:max(1, min(limit, 100))]


def _fetch_ticker_rows(exchange: str, quote: str, market_type: str = "spot") -> list:
    try:
        import ccxt
    except ImportError:
        return []
    if not hasattr(ccxt, exchange):
        return []
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        tickers = ex.fetch_tickers()
    except Exception:
        return []
    out = []
    suffix = "/" + quote
    for sym, t in tickers.items():
        try:
            if suffix not in sym:                 # spot "BTC/USDT" or swap "BTC/USDT:USDT"
                continue
            is_swap = ":" in sym
            if market_type == "spot" and is_swap:
                continue
            if market_type == "swap" and not is_swap:
                continue
            base = sym.split("/")[0]
            if not base or ":" in base:
                continue
            last = t.get("last") or t.get("close")
            if last is None:
                continue
            pct = t.get("percentage")
            qvol = t.get("quoteVolume")
            if qvol is None and t.get("baseVolume") is not None:
                qvol = t["baseVolume"] * last
            internal = f"{base.upper()}_{quote}"
            # spot + swap duplicates: keep whichever has the larger volume
            dup = next((r for r in out if r["symbol"] == internal), None)
            row = {"symbol": internal, "price": float(last),
                   "change_pct": round(float(pct), 2) if pct is not None else None,
                   "qvol": float(qvol) if qvol is not None else None}
            if dup:
                if (row["qvol"] or 0) > (dup["qvol"] or 0):
                    out[out.index(dup)] = row
            else:
                out.append(row)
        except Exception:
            continue
    return out


def supported() -> list:
    """Preferred exchanges only (short list for the default picker)."""
    out = ["mexc"]
    try:
        import ccxt
        out += [e for e in PREFERRED if e != "mexc" and e in ccxt.exchanges]
    except ImportError:
        pass
    return out


def all_exchanges() -> list:
    """Full ccxt exchange list, preferred ones first, then the rest alphabetically.
    Returns ['mexc'] if ccxt is not installed."""
    try:
        import ccxt
        preferred_set = set(PREFERRED)
        preferred = [e for e in PREFERRED if e in ccxt.exchanges]
        rest = sorted(e for e in ccxt.exchanges if e not in preferred_set)
        return preferred + rest
    except ImportError:
        return ["mexc"]


def fetch_daily(symbol: str, exchange: str = "mexc", limit: int = 400,
                market_type: str = "spot") -> list:
    """Daily OHLC as [{time(sec),open,high,low,close}], newest last.
    symbol uses BTC_USDT form; converted per-exchange.
    market_type "swap" charts the perpetual (via ccxt, any exchange)."""
    if exchange == "mexc" and market_type == "spot":
        return _mexc_native(symbol, limit)
    return _ccxt(symbol, exchange, limit, market_type)


def fetch_ohlcv_tf(symbol: str, exchange: str = "binance", timeframe: str = "5m",
                   limit: int = 200) -> list:
    """Intraday OHLC for the scalper bot — any ccxt timeframe ('1m','5m','15m',
    '1h'...). Same row shape as fetch_daily. [] on any error (never raises)."""
    try:
        import ccxt
    except ImportError:
        return []
    if not hasattr(ccxt, exchange):
        return []
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        pair = symbol.replace("_", "/")
        rows = ex.fetch_ohlcv(pair, timeframe=timeframe, limit=min(max(limit, 50), 1000))
        return [{"time": int(r[0] / 1000), "open": r[1], "high": r[2],
                 "low": r[3], "close": r[4]} for r in rows if r and r[4] is not None]
    except Exception:
        return []


def list_assets(exchange: str = "mexc", quote: str = "USDT", limit: int = 500,
                market_type: str = "spot") -> list:
    """Sorted list of tradable symbols in BASE_USDT form (e.g. "BTC_USDT")
    that trade against `quote` on `exchange`, for the asset-picker UI.
    market_type: "spot" | "swap" (perps) | "all". [] on any error."""
    try:
        markets = _load_markets(exchange)
        if not markets:
            return []
        quote = (quote or "USDT").upper()
        out = set()
        for m in markets.values():
            try:
                if m.get("quote", "").upper() != quote:
                    continue
                if not m.get("active", True):
                    continue
                if market_type == "spot" and not m.get("spot"):
                    continue
                if market_type == "swap" and not m.get("swap"):
                    continue
                if not (m.get("spot") or m.get("swap")):
                    continue
                base = m.get("base")
                if not base:
                    continue
                out.add(f"{base.upper()}_{quote}")
            except Exception:
                continue
        return sorted(out)[:limit]
    except Exception:
        return []


def _load_markets(exchange: str) -> dict:
    """Lazy-init a ccxt exchange and return its (cached) markets dict.
    Returns {} when ccxt is unavailable or the exchange is unknown."""
    if exchange in _MARKETS_CACHE:
        return _MARKETS_CACHE[exchange]
    try:
        import ccxt
    except ImportError:
        return {}
    if not hasattr(ccxt, exchange):
        return {}
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        markets = ex.load_markets() or {}
    except Exception:
        markets = {}
    _MARKETS_CACHE[exchange] = markets
    return markets


def _mexc_native(symbol, limit):
    try:
        d = requests.get(f"{MEXC}/api/v1/contract/kline/{symbol}",
                         params={"interval": "Day1", "limit": limit}, timeout=15).json().get("data", {})
    except Exception:
        return []
    t, o, h, l, c = (d.get(k, []) for k in ("time", "open", "high", "low", "close"))
    out = []
    for i in range(len(t)):
        try:
            out.append({"time": int(t[i]), "open": float(o[i]), "high": float(h[i]),
                        "low": float(l[i]), "close": float(c[i])})
        except Exception:
            pass
    return out


def _ccxt(symbol, exchange, limit, market_type="spot"):
    try:
        import ccxt
    except ImportError:
        return []
    if not hasattr(ccxt, exchange):
        return []
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        pair = symbol.replace("_", "/")              # BTC_USDT -> BTC/USDT
        if market_type == "swap":                    # perp: BTC/USDT:USDT
            pair = pair + ":" + pair.split("/")[1]
        rows = ex.fetch_ohlcv(pair, timeframe="1d", limit=limit)
        return [{"time": int(r[0] / 1000), "open": float(r[1]), "high": float(r[2]),
                 "low": float(r[3]), "close": float(r[4])} for r in rows]
    except Exception:
        return []
