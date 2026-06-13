"""
webhook_store.py — in-memory store for TradingView webhook alerts.

Keeps the last MAX_ALERTS alerts per symbol (newest-first) and surfaces
them to the chart UI as TP/SL price levels + an alert log panel.

Persistence: write-through to SQLite via store_db (platform/data/ascent.db) —
alerts survive restarts. Reads stay in-memory (fast); if the DB is
unavailable the store silently degrades to memory-only.

Alert JSON shape (what TradingView sends in the webhook body):
  {
    "symbol":    "BTC_USDT",          # required — must match Ascent symbol format
    "action":    "BUY" | "SELL" | "TP" | "SL" | "ALERT",
    "price":     65432.10,            # entry / signal price (optional)
    "tp":        68000,               # take-profit level (optional)
    "sl":        63000,               # stop-loss level (optional)
    "message":   "EMA breakout",      # freeform note (optional)
    "timeframe": "1D"                 # timeframe tag (optional)
  }

All fields except `symbol` are optional so simple pine-script alerts
(just a plain text body containing the symbol) also work — the receiver
will parse best-effort.
"""

import time
import threading
from collections import deque, defaultdict

import store_db

MAX_ALERTS = 100       # per symbol
MAX_GLOBAL = 500       # total ring-buffer (newest first)

_lock = threading.Lock()

# symbol → deque of alert dicts (newest first, capped at MAX_ALERTS)
_by_symbol: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_ALERTS))

# flat global ring-buffer for the "all alerts" feed
_global: deque = deque(maxlen=MAX_GLOBAL)


def ingest(raw: dict) -> dict:
    """Normalise and store one incoming webhook payload. Returns the stored alert."""
    alert = {
        "id":        int(time.time() * 1000),    # ms timestamp as id
        "ts":        time.time(),
        "symbol":    str(raw.get("symbol", "UNKNOWN")).upper().replace("/", "_"),
        "action":    str(raw.get("action", "ALERT")).upper(),
        "price":     _float(raw.get("price")),
        "tp":        _float(raw.get("tp")),
        "sl":        _float(raw.get("sl")),
        "message":   str(raw.get("message", ""))[:200],
        "timeframe": str(raw.get("timeframe", ""))[:10],
    }
    with _lock:
        _by_symbol[alert["symbol"]].appendleft(alert)
        _global.appendleft(alert)
    store_db.save_alert(alert)
    return alert


def get_for_symbol(symbol: str, limit: int = 20) -> list:
    """Most recent alerts for a symbol, newest first."""
    sym = symbol.upper().replace("/", "_")
    with _lock:
        items = list(_by_symbol.get(sym, []))
    return items[:limit]


def get_levels(symbol: str) -> dict:
    """Latest TP and SL levels for a symbol (from the most recent alert that
    has them). Returns {"tp": float|None, "sl": float|None}."""
    for alert in get_for_symbol(symbol, limit=MAX_ALERTS):
        if alert["tp"] is not None or alert["sl"] is not None:
            return {"tp": alert["tp"], "sl": alert["sl"],
                    "price": alert["price"], "action": alert["action"],
                    "ts": alert["ts"]}
    return {"tp": None, "sl": None, "price": None, "action": None, "ts": None}


def get_recent(limit: int = 50) -> list:
    """Global alert feed, newest first."""
    with _lock:
        return list(_global)[:limit]


def clear_symbol(symbol: str):
    sym = symbol.upper().replace("/", "_")
    with _lock:
        if sym in _by_symbol:
            _by_symbol[sym].clear()
        # also drop from the global feed so a restart doesn't resurrect them
        kept = [a for a in _global if a["symbol"] != sym]
        _global.clear()
        _global.extend(kept)
    store_db.delete_alerts(sym)


def _rebuild_from_disk():
    """Startup: reload the most recent alerts so restarts don't lose history."""
    rows = store_db.load_alerts(MAX_GLOBAL)      # newest first
    if not rows:
        return
    with _lock:
        for a in rows:                            # deques are newest-first; append keeps order
            _global.append(a)
            _by_symbol[a["symbol"]].append(a)


_rebuild_from_disk()


def _float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
