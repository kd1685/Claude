"""
orderflow.py — live "tape" intelligence from free public exchange data (ccxt).

Four reads, all ADAPTIVE (thresholds derive from the symbol's own recent
activity, so the same code scales from BTC to a microcap) and all LIVE-ONLY:
tick/order-book history isn't freely available, so none of these can be
backtested — they are context for the positioning grid and the AI analyst,
deliberately NOT votes in the indicator panel (which must stay backtestable).

  WHALE FLOW     recent trades ≥ the 95th percentile of trade notional
                 ("big prints") → buy/sell imbalance among them.
  TAKER FLOW     buy vs sell notional across ALL recent trades (CVD-style):
                 is the tape being lifted (market buys) or hit (market sells)?
  BOOK IMBALANCE resting bid vs ask notional within ±2% of mid price.
  WALLS          largest single resting order each side near price; flagged
                 a "wall" when ≥ 8× the median level size in that window.

Honesty: taker side comes from the exchange's own trade feed where provided;
on feeds without side info we fall back to tick-rule classification (uptick =
buy) and say so. Everything is cached ~75s per (exchange, symbol) and fails
soft — the platform never breaks because a tape endpoint hiccuped.
"""

import statistics
import threading
import time

TTL = 75
TRADE_LIMIT = 500              # recent prints to sample
BOOK_LIMIT = 100               # levels per side
BAND_PCT = 0.02                # book imbalance band: ±2% of mid
WHALE_PCTL = 0.95              # adaptive big-print threshold
WALL_X_MEDIAN = 8.0            # a wall is ≥ this × median level notional

_lock = threading.Lock()
_cache: dict = {}


def flow(symbol: str, exchange: str = "binance") -> dict:
    """All four reads for one symbol. Cached; never raises."""
    key = f"{exchange}:{symbol}"
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit["ts"] < TTL:
            return hit["data"]
    data = {"symbol": symbol, "exchange": exchange,
            "note": "live tape — context only, not backtestable, not advice"}
    try:
        ex = _client(exchange)
        market = symbol.replace("_", "/")
        data["trades"] = _trade_flow(ex, market)
    except Exception as e:
        data["trades"] = {"error": _brief(e)}
    try:
        ex = _client(exchange)
        market = symbol.replace("_", "/")
        data["book"] = _book_read(ex, market)
    except Exception as e:
        data["book"] = {"error": _brief(e)}
    with _lock:
        _cache[key] = {"data": data, "ts": now}
        if len(_cache) > 200:                       # bound memory
            oldest = min(_cache, key=lambda k: _cache[k]["ts"])
            _cache.pop(oldest, None)
    return data


# ─── internals ────────────────────────────────────────────────────────────────

_clients: dict = {}


def _client(exchange: str):
    import ccxt
    exid = (exchange or "binance").lower()
    with _lock:
        if exid not in _clients:
            cls = getattr(ccxt, exid)
            _clients[exid] = cls({"enableRateLimit": True})
        return _clients[exid]


def _brief(e) -> str:
    return f"{type(e).__name__}"[:40]


def _trade_flow(ex, market: str) -> dict:
    """Whale flow + taker flow from recent public trades."""
    trades = ex.fetch_trades(market, limit=TRADE_LIMIT) or []
    rows, last_price, sided = [], None, 0
    for t in trades:
        price = t.get("price")
        amount = t.get("amount")
        if not price or not amount:
            continue
        notional = float(price) * float(amount)
        side = t.get("side")
        if side in ("buy", "sell"):
            sided += 1
        else:                                       # tick-rule fallback
            side = ("buy" if last_price is not None and price >= last_price
                    else "sell")
        last_price = price
        rows.append((notional, side, t.get("timestamp") or 0))
    if len(rows) < 30:
        return {"error": "too few trades"}

    notionals = sorted(n for n, _, _ in rows)
    whale_th = notionals[int(len(notionals) * WHALE_PCTL)]
    total_buy = sum(n for n, s, _ in rows if s == "buy")
    total_sell = sum(n for n, s, _ in rows if s == "sell")
    wb = sum(n for n, s, _ in rows if s == "buy" and n >= whale_th)
    ws = sum(n for n, s, _ in rows if s == "sell" and n >= whale_th)
    w_n = sum(1 for n, _, _ in rows if n >= whale_th)

    span_min = max(1, (max(ts for _, _, ts in rows) -
                       min(ts for _, _, ts in rows)) / 60000) if rows[0][2] else None

    def imb(b, s):
        tot = b + s
        return round((b - s) / tot * 100, 1) if tot > 0 else 0.0

    return {
        "sided_pct": round(sided / len(rows) * 100),     # 100 = real sides, else tick-rule
        "window_min": round(span_min, 1) if span_min else None,
        "n_trades": len(rows),
        "whale": {
            "threshold_usd": round(whale_th),            # adaptive (p95 of prints)
            "n_prints": w_n,
            "buy_usd": round(wb), "sell_usd": round(ws),
            "imbalance_pct": imb(wb, ws),                # +100 all-buy … −100 all-sell
            "bias": "BUYERS" if imb(wb, ws) > 15 else
                    "SELLERS" if imb(wb, ws) < -15 else "BALANCED",
        },
        "taker": {
            "buy_usd": round(total_buy), "sell_usd": round(total_sell),
            "imbalance_pct": imb(total_buy, total_sell),
            "bias": "BUY PRESSURE" if imb(total_buy, total_sell) > 10 else
                    "SELL PRESSURE" if imb(total_buy, total_sell) < -10 else "NEUTRAL",
        },
    }


def _book_read(ex, market: str) -> dict:
    """Depth imbalance ±2% + adaptive wall detection."""
    ob = ex.fetch_order_book(market, limit=BOOK_LIMIT)
    bids, asks = ob.get("bids") or [], ob.get("asks") or []
    if not bids or not asks:
        return {"error": "empty book"}
    mid = (bids[0][0] + asks[0][0]) / 2
    lo, hi = mid * (1 - BAND_PCT), mid * (1 + BAND_PCT)

    bid_lv = [(p, p * a) for p, a, *_ in bids if p >= lo]
    ask_lv = [(p, p * a) for p, a, *_ in asks if p <= hi]
    bid_usd = sum(n for _, n in bid_lv)
    ask_usd = sum(n for _, n in ask_lv)
    tot = bid_usd + ask_usd
    imb = round((bid_usd - ask_usd) / tot * 100, 1) if tot > 0 else 0.0

    all_lv = [n for _, n in bid_lv + ask_lv]
    med = statistics.median(all_lv) if all_lv else 0

    def wall(levels):
        if not levels or med <= 0:
            return None
        p, n = max(levels, key=lambda x: x[1])
        if n < WALL_X_MEDIAN * med:
            return None
        return {"price": p, "usd": round(n), "x_median": round(n / med, 1)}

    return {
        "mid": mid,
        "band_pct": BAND_PCT * 100,
        "bid_usd": round(bid_usd), "ask_usd": round(ask_usd),
        "imbalance_pct": imb,                            # + = bid-heavy
        "bias": "BID-HEAVY" if imb > 12 else "ASK-HEAVY" if imb < -12 else "BALANCED",
        "buy_wall": wall(bid_lv),
        "sell_wall": wall(ask_lv),
        "wall_rule": f"wall = level ≥ {WALL_X_MEDIAN:g}× median size in ±{BAND_PCT*100:g}%",
    }
