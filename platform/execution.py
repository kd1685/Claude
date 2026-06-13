"""
execution.py — non-custodial TV → exchange execution bridge for Ascent Terminal.

Turns a TradingView alert (or a manual click in the Alerts tab) into an order
on the USER'S OWN exchange account via ccxt. Non-custodial by design:

  * API keys are NEVER stored server-side. They are passed per-request from
    the user's browser, or read from env vars on the user's OWN machine.
  * Everything defaults to PAPER (simulated fill at live price, logged only).

Safety model — ALL of these must pass before a LIVE order is placed:
  1. Valid subscriber access key      (X-Access-Key, checked in app.py)
  2. EXECUTE_KEY env set AND matching (X-Execute-Key header / request field)
  3. EXEC_LIVE=true env               (master live switch; otherwise paper-only)
  4. The request says dry_run=false   (explicit, never implied)
  5. Order notional <= EXEC_MAX_USD   (hard cap, default 1000)

The execution log is an in-memory ring buffer mirrored to SQLite via
store_db (write-through; rebuilt on startup, survives restarts).
TP/SL from the alert are logged for reference but NOT auto-placed on the
exchange in v1 — placing native TP/SL orders is exchange-specific.
"""

import time
import threading
from collections import deque

import store_db

MAX_LOG = 200

_lock = threading.Lock()
_log: deque = deque(maxlen=MAX_LOG)               # newest first


# ─── Public API ────────────────────────────────────────────────────────────────

def execute(req: dict, cfg: dict) -> dict:
    """Validate + run one order request. Never raises — returns a result dict
    that is also appended to the execution log.

    req keys (from the UI or the auto-exec hook):
      symbol        "BTC_USDT" (required)
      side          "BUY" | "SELL" (required)
      quote_amount  order size in quote currency (USDT) — OR
      amount        order size in base units
      order_type    "market" (default) | "limit"
      price         limit price (required for limit; optional ref for paper)
      exchange      ccxt id (default cfg["default_exchange"])
      api_key / api_secret / api_password   per-request credentials (optional)
      dry_run       bool (default True — paper)
      execute_key   must match cfg["execute_key"] for ANY order
      source        "manual" | "auto" (log tag)

    cfg keys (from env, assembled in app.py):
      execute_key, live_enabled, max_usd, default_exchange,
      env_api_key, env_api_secret, env_api_password
    """
    entry = {
        "id": int(time.time() * 1000),
        "ts": time.time(),
        "source": str(req.get("source", "manual"))[:10],
        "symbol": str(req.get("symbol", "")).upper().replace("/", "_"),
        "side": str(req.get("side", "")).upper(),
        "exchange": (req.get("exchange") or cfg.get("default_exchange") or "binance").lower(),
        "order_type": (req.get("order_type") or "market").lower(),
        "mode": "PAPER",
        "status": "error",
        "detail": "",
        "price": None, "amount": None, "notional": None,
        "tp": _f(req.get("tp")), "sl": _f(req.get("sl")),
    }

    try:
        # ── Gate 2: execute key (required even for paper — it arms the bridge)
        if not cfg.get("execute_key"):
            return _fail(entry, "Execution disabled: set EXECUTE_KEY env var on the server to arm the bridge.")
        if str(req.get("execute_key", "")) != cfg["execute_key"]:
            return _fail(entry, "Invalid execute key.")

        if entry["side"] not in ("BUY", "SELL"):
            return _fail(entry, "side must be BUY or SELL.")
        if not entry["symbol"] or "_" not in entry["symbol"]:
            return _fail(entry, "symbol must look like BTC_USDT.")
        if entry["order_type"] not in ("market", "limit"):
            return _fail(entry, "order_type must be market or limit.")

        dry_run = req.get("dry_run")
        dry_run = True if dry_run is None else bool(dry_run)

        # ── Gates 3+4: live needs the master switch AND an explicit request
        if not dry_run and not cfg.get("live_enabled"):
            return _fail(entry, "LIVE execution is off on this server (set EXEC_LIVE=true to enable). "
                                "Order was NOT placed — re-send as paper or enable live.")
        entry["mode"] = "PAPER" if dry_run else "LIVE"

        # ── Price discovery (paper fill / sizing / cap check)
        limit_price = _f(req.get("price"))
        if entry["order_type"] == "limit" and limit_price is None:
            return _fail(entry, "limit orders need a price.")
        ref_price = limit_price or _live_price(entry["exchange"], entry["symbol"])
        if ref_price is None:
            ref_price = _f(req.get("price"))
        if ref_price is None:
            return _fail(entry, f"Could not get a price for {entry['symbol']} on {entry['exchange']}.")

        # ── Sizing
        amount = _f(req.get("amount"))
        quote_amount = _f(req.get("quote_amount"))
        if amount is None and quote_amount is None:
            return _fail(entry, "Provide quote_amount (USDT size) or amount (base units).")
        if amount is None:
            amount = quote_amount / ref_price
        notional = amount * ref_price
        entry["price"] = round(ref_price, 8)
        entry["amount"] = round(amount, 8)
        entry["notional"] = round(notional, 2)

        # ── Gate 5: notional cap
        max_usd = float(cfg.get("max_usd") or 0)
        if max_usd > 0 and notional > max_usd:
            return _fail(entry, f"Order notional ${notional:,.2f} exceeds EXEC_MAX_USD cap of ${max_usd:,.0f}.")

        # ── PAPER: simulated fill, log only
        if dry_run:
            entry["status"] = "ok"
            entry["detail"] = "Paper fill (simulated — no exchange order placed)."
            return _store(entry)

        # ── LIVE: per-request creds, falling back to env creds on this machine
        api_key = req.get("api_key") or cfg.get("env_api_key") or ""
        api_secret = req.get("api_secret") or cfg.get("env_api_secret") or ""
        api_password = req.get("api_password") or cfg.get("env_api_password") or ""
        if not api_key or not api_secret:
            return _fail(entry, "LIVE order needs exchange API credentials (per-request, or "
                                "EXEC_API_KEY/EXEC_API_SECRET env vars on your machine). Keys are never stored.")

        result = _place_live(entry, api_key, api_secret, api_password, limit_price)
        if result.get("error"):
            return _fail(entry, result["error"])
        entry["status"] = "ok"
        entry["detail"] = f"LIVE order placed · exchange id {result.get('order_id', '?')}"
        return _store(entry)

    except Exception as e:                        # belt & braces — never raise
        return _fail(entry, f"Unexpected error: {e}")


def log_recent(limit: int = 50) -> list:
    with _lock:
        return list(_log)[:max(1, min(limit, MAX_LOG))]


# ─── Internals ─────────────────────────────────────────────────────────────────

def _place_live(entry, api_key, api_secret, api_password, limit_price):
    try:
        import ccxt
    except ImportError:
        return {"error": "ccxt not installed on the server — pip install ccxt."}
    if not hasattr(ccxt, entry["exchange"]):
        return {"error": f"Unknown exchange {entry['exchange']!r}."}
    try:
        params = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
        if api_password:
            params["password"] = api_password
        ex = getattr(ccxt, entry["exchange"])(params)
        pair = entry["symbol"].replace("_", "/")
        side = entry["side"].lower()
        if entry["order_type"] == "limit":
            order = ex.create_order(pair, "limit", side, entry["amount"], limit_price)
        else:
            order = ex.create_order(pair, "market", side, entry["amount"])
        return {"order_id": order.get("id")}
    except Exception as e:
        return {"error": f"Exchange rejected the order: {e}"}


def _live_price(exchange: str, symbol: str):
    """Best-effort last price via ccxt fetch_ticker. None on any failure."""
    try:
        import ccxt
    except ImportError:
        return None
    if not hasattr(ccxt, exchange):
        return None
    try:
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        t = ex.fetch_ticker(symbol.replace("_", "/"))
        p = t.get("last") or t.get("close")
        return float(p) if p is not None else None
    except Exception:
        return None


def _store(entry: dict) -> dict:
    with _lock:
        _log.appendleft(entry)
    store_db.save_exec(entry)
    return entry


def _rebuild_from_disk():
    rows = store_db.load_exec(MAX_LOG)            # newest first
    if rows:
        with _lock:
            _log.extend(rows)


_rebuild_from_disk()


def _fail(entry: dict, msg: str) -> dict:
    entry["status"] = "error"
    entry["detail"] = msg
    return _store(entry)


def _f(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None
