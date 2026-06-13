"""
liquidations.py — live liquidation feed (Binance USDT-perps force orders).

Binance removed the REST endpoint for liquidation history years ago, so this
runs a single lightweight WEBSOCKET (wss://fstream.binance.com/ws/!forceOrder@arr,
all symbols in one stream) in a daemon thread, with auto-reconnect + backoff.

Semantics worth knowing (and shown in the UI):
  * A force order with side=SELL means a LONG position was liquidated
    (the exchange force-SELLS it) — and vice versa.
  * The feed has NO history: stats warm up from server start. Responses
    carry `uptime_s` so the UI can say "warming up" honestly.
  * Coverage is Binance USDT-perps — the deepest public liq stream and the
    standard proxy for market-wide stress. Not every exchange, and we say so.

Aggregation (thread-safe ring buffer, ~20k events):
  summary(symbol=None) → 5-minute and 1-hour windows of long-liq vs
  short-liq USD, event counts, biggest single print, plus CASCADE detection:
  the current 5-min total vs the median of the trailing twelve 5-min buckets
  (floor $2M) → NONE / ELEVATED (≥3×) / CASCADE (≥6×).

Fails soft everywhere: no websocket-client installed, or the stream down,
just means the endpoint reports {"running": false, "reason": ...}.
Disable entirely with LIQ_FEED=false.
"""

import json
import os
import statistics
import threading
import time
from collections import deque

WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
MAX_EVENTS = 20000
CASCADE_FLOOR_USD = 2_000_000
ELEVATED_X, CASCADE_X = 3.0, 6.0

_lock = threading.Lock()
_events: deque = deque(maxlen=MAX_EVENTS)   # (ts_s, "SYMBOL", long_liq: bool, usd)
_started_at = None
_running = False
_reason = "not started"
_thread = None


# ─── lifecycle ────────────────────────────────────────────────────────────────

def start():
    """Begin the feed (idempotent). Called from app startup."""
    global _thread, _reason, _started_at
    if os.environ.get("LIQ_FEED", "true").strip().lower() in ("false", "0", "off"):
        _reason = "disabled via LIQ_FEED=false"
        return
    try:
        import websocket  # noqa: F401  (websocket-client)
    except ImportError:
        _reason = "websocket-client not installed (pip install websocket-client)"
        return
    with _lock:
        if _thread and _thread.is_alive():
            return
        _started_at = time.time()
        _thread = threading.Thread(target=_ws_loop, daemon=True,
                                   name="apex-liqfeed")
        _thread.start()


def _ws_loop():
    global _running, _reason
    import websocket
    backoff = 2
    while True:
        try:
            ws = websocket.create_connection(WS_URL, timeout=30)
            with _lock:
                _running = True
                _reason = ""
            backoff = 2
            while True:
                msg = ws.recv()
                _ingest(msg)
        except Exception as e:
            with _lock:
                _running = False
                _reason = f"reconnecting ({type(e).__name__})"
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)


def _ingest(msg: str):
    """Parse one force-order message and append to the ring."""
    try:
        d = json.loads(msg)
        o = d.get("o") or {}
        sym = str(o.get("s") or "")
        side = str(o.get("S") or "")
        qty = float(o.get("q") or 0)
        price = float(o.get("ap") or o.get("p") or 0)
        ts = (d.get("E") or o.get("T") or time.time() * 1000) / 1000.0
        if not sym or not price or not qty:
            return
        usd = qty * price
        long_liq = side == "SELL"               # forced sell = long got liquidated
        with _lock:
            _events.append((ts, sym, long_liq, usd))
    except Exception:
        pass                                    # one bad frame never matters


# ─── queries ──────────────────────────────────────────────────────────────────

def _norm(symbol: str) -> str:
    """BTC_USDT / BTC/USDT → BTCUSDT (Binance perp ticker)."""
    return (symbol or "").upper().replace("_", "").replace("/", "")


_sum_cache: dict = {}
SUM_TTL = 5                                  # the grid polls; 5s staleness is free speed
MAX_AGE = 2 * 3600                           # keep 2h of events (we report 1h max)


def summary(symbol: str = "") -> dict:
    now = time.time()
    want = _norm(symbol)
    hit = _sum_cache.get(want)
    if hit and now - hit[0] < SUM_TTL:
        return hit[1]
    with _lock:
        running, reason = _running, _reason
        uptime = round(now - _started_at) if _started_at else 0
        while _events and now - _events[0][0] > MAX_AGE:   # time-prune (oldest left)
            _events.popleft()
        ev = list(_events)

    def window(secs, sym_filter):
        lo = now - secs
        longs = shorts = n = 0.0
        biggest = None
        for ts, s, is_long, usd in ev:
            if ts < lo or (sym_filter and s != sym_filter):
                continue
            n += 1
            if is_long:
                longs += usd
            else:
                shorts += usd
            if biggest is None or usd > biggest[1]:
                biggest = (s, usd, "LONG" if is_long else "SHORT")
        return {"long_usd": round(longs), "short_usd": round(shorts),
                "events": int(n),
                "biggest": ({"symbol": biggest[0], "usd": round(biggest[1]),
                             "side": biggest[2]} if biggest else None)}

    # cascade: current 5-min global total vs trailing 5-min buckets
    buckets = [0.0] * 13                        # [0]=current, 1..12 trailing
    for ts, _, _, usd in ev:
        age = now - ts
        if age < 0 or age >= 13 * 300:
            continue
        buckets[int(age // 300)] += usd
    trailing = [b for b in buckets[1:] if b > 0] or [0.0]
    baseline = max(statistics.median(trailing), CASCADE_FLOOR_USD / 6)
    cur = buckets[0]
    level = ("CASCADE" if cur >= max(CASCADE_FLOOR_USD, baseline * CASCADE_X)
             else "ELEVATED" if cur >= max(CASCADE_FLOOR_USD / 2, baseline * ELEVATED_X)
             else "NONE")

    out = {
        "running": running, "reason": reason, "uptime_s": uptime,
        "source": "binance usdt-perps force orders",
        "global": {"m5": window(300, None), "h1": window(3600, None)},
        "cascade": {"level": level, "total_5m_usd": round(cur),
                    "baseline_5m_usd": round(baseline)},
        "note": "no history before server start — stats warm up over the first hour",
    }
    if want:
        out["symbol"] = want
        out["asset"] = {"m5": window(300, want), "h1": window(3600, want)}
    _sum_cache[want] = (now, out)
    if len(_sum_cache) > 100:
        _sum_cache.pop(min(_sum_cache, key=lambda k: _sum_cache[k][0]), None)
    return out


# test hook — lets the test suite inject events without a socket
def _inject(ts, symbol, long_liq, usd):
    with _lock:
        _events.append((ts, symbol, long_liq, usd))
