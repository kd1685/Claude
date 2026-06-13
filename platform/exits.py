"""
exits.py — protective TP/SL exits, server-watched (roadmap item 12, half a).

Makes the TP/SL lines REAL on every exchange ccxt supports: an "exit plan"
arms a watcher that polls the live price and, the moment TP or SL is touched,
fires a market SELL for the recorded position size through the SAME execution
bridge as everything else — every gate intact (EXECUTE_KEY · EXEC_LIVE master
switch · per-order cap · credentials). Long positions, spot, v1.

Honest mechanics (also shown in the UI):
  * This is a SERVER-WATCHED exit, not an order resting on the exchange.
    If this server is down when price crosses, nothing fires. Native
    exchange-held TP/SL (OCO) remains the follow-up — it needs per-exchange
    live verification with real keys (owner task, post-launch).
  * Trigger = last traded price crossing the level (TP: last ≥ tp,
    SL: last ≤ sl), checked every POLL_SEC. Fills are market orders, so
    slippage applies, exactly like a stop-market.
  * Plans PERSIST and re-arm after a server restart (deliberately the
    opposite of the bots: a protective stop should not silently vanish
    because the server rebooted). If the bridge is disarmed (no
    EXECUTE_KEY), plans show SUSPENDED and the UI says why.
  * One armed plan per symbol; dragging the chart TP/SL lines moves the
    armed plan's triggers too (the drag warning says so).
  * After a trigger attempt fails (exchange error), the plan flips to
    ERROR and stops retrying — no order-spam loops; re-arm manually.
"""

import json
import os
import threading
import time

import execution
import store_db

POLL_SEC = 10
MAX_PLANS = 50

_lock = threading.Lock()
_plans: dict = {}            # id -> plan dict
_thread = None


def _exec_cfg(owner: str = ""):
    from app import cfg_for                      # late import (env may change in tests)
    return cfg_for(owner)


# ─── lifecycle ────────────────────────────────────────────────────────────────

def start():
    """Load persisted plans and start the watcher thread (idempotent)."""
    global _thread
    _load()
    with _lock:
        if _thread and _thread.is_alive():
            return
        _thread = threading.Thread(target=_loop, daemon=True, name="apex-exitwatch")
        _thread.start()


def _loop():
    while True:
        try:
            _cycle()
        except Exception:
            pass                                  # the watcher must never die
        time.sleep(POLL_SEC)


def _cycle():
    with _lock:
        armed = [dict(p) for p in _plans.values() if p["status"] == "armed"]
    if not armed:
        return
    cfg = _exec_cfg()
    if not cfg.get("execute_key"):                # bridge disarmed → suspend, don't fire
        with _lock:
            for p in _plans.values():
                if p["status"] == "armed":
                    p["status"] = "suspended"
                    p["note"] = "bridge disarmed (EXECUTE_KEY empty) — re-arms automatically when set"
            _save()
        return

    prices = {}
    for p in armed:
        key = (p["exchange"], p["symbol"])
        if key not in prices:
            prices[key] = _last_price(*key)
        last = prices[key]
        if last is None:
            continue
        hit = ("TP" if last >= p["tp"] else "SL" if last <= p["sl"] else None) \
            if (p.get("tp") and p.get("sl")) else \
            ("TP" if p.get("tp") and last >= p["tp"] else
             "SL" if p.get("sl") and last <= p["sl"] else None)
        if not hit:
            continue
        _fire(p["id"], hit, last, _exec_cfg(p.get("owner", "")))


def _fire(plan_id: str, which: str, last: float, cfg: dict):
    with _lock:
        p = _plans.get(plan_id)
        if not p or p["status"] != "armed":
            return
        p["status"] = "firing"                    # re-entry guard
    live = bool(p["live"]) and cfg.get("live_enabled")
    res = execution.execute({
        "symbol": p["symbol"], "side": "SELL",
        "amount": p["qty"], "price": last,
        "exchange": p["exchange"],
        "dry_run": not live,
        "execute_key": cfg["execute_key"],
        "source": "exitwatch",
        "tp": p.get("tp"), "sl": p.get("sl"),
    }, cfg)
    with _lock:
        p = _plans.get(plan_id)
        if not p:
            return
        if res.get("status") == "ok":
            p["status"] = "done"
            p["note"] = f"{which} hit @ {last} → {res['mode']} SELL filled ({res['detail'][:60]})"
        else:
            p["status"] = "error"
            p["note"] = f"{which} hit @ {last} but SELL failed: {res.get('detail','')[:90]}"
        p["closed_ts"] = time.time()
        _save()


def _last_price(exchange: str, symbol: str):
    try:
        import ccxt
        cls = getattr(ccxt, exchange)
        ex = _clients.setdefault(exchange, cls({"enableRateLimit": True}))
        t = ex.fetch_ticker(symbol.replace("_", "/"))
        return float(t.get("last") or t.get("close"))
    except Exception:
        return None


_clients: dict = {}


# ─── public API (called from app.py) ─────────────────────────────────────────

def upsert(symbol: str, qty: float, tp, sl, live: bool, exchange: str, source="manual", owner: str = "") -> dict:
    """One armed plan per symbol — creating again replaces it."""
    symbol = symbol.upper().replace("/", "_")
    if not (qty and qty > 0):
        return {"ok": False, "error": "qty must be a positive base amount."}
    if tp is None and sl is None:
        return {"ok": False, "error": "Provide tp and/or sl."}
    with _lock:
        for p in list(_plans.values()):           # replace existing armed plan
            if p["symbol"] == symbol and p["status"] in ("armed", "suspended"):
                del _plans[p["id"]]
        if len(_plans) >= MAX_PLANS:
            done = [k for k, p in _plans.items() if p["status"] in ("done", "cancelled", "error")]
            for k in done[:len(_plans) - MAX_PLANS + 1]:
                del _plans[k]
            if len(_plans) >= MAX_PLANS:
                return {"ok": False, "error": f"Plan limit reached ({MAX_PLANS})."}
        plan = {
            "id": f"x{int(time.time()*1000)}",
            "owner": owner,
            "symbol": symbol, "qty": float(qty),
            "tp": float(tp) if tp else None, "sl": float(sl) if sl else None,
            "live": bool(live),
            "exchange": (exchange or "binance").lower(),
            "source": source, "status": "armed", "note": "",
            "created": time.time(),
        }
        _plans[plan["id"]] = plan
        _save()
        return {"ok": True, "plan": dict(plan)}


def cancel(plan_id: str) -> dict:
    with _lock:
        p = _plans.get(plan_id)
        if not p:
            return {"ok": False, "error": "Unknown plan."}
        if p["status"] in ("armed", "suspended", "error"):
            p["status"] = "cancelled"
            p["closed_ts"] = time.time()
            _save()
        return {"ok": True}


def update_levels(symbol: str, tp, sl):
    """Called when chart TP/SL lines are dragged — move the armed triggers."""
    symbol = symbol.upper().replace("/", "_")
    with _lock:
        for p in _plans.values():
            if p["symbol"] == symbol and p["status"] in ("armed", "suspended"):
                if tp is not None:
                    p["tp"] = float(tp)
                if sl is not None:
                    p["sl"] = float(sl)
                _save()
                return True
    return False


def status() -> dict:
    with _lock:
        plans = sorted((dict(p) for p in _plans.values()),
                       key=lambda p: -p["created"])
        # un-suspend automatically once the bridge is armed again
        return {"plans": plans[:60], "poll_sec": POLL_SEC,
                "watching": sum(1 for p in plans if p["status"] == "armed")}


def rearm_suspended(cfg_armed: bool):
    if not cfg_armed:
        return
    with _lock:
        changed = False
        for p in _plans.values():
            if p["status"] == "suspended":
                p["status"] = "armed"
                p["note"] = ""
                changed = True
        if changed:
            _save()


# ─── persistence ──────────────────────────────────────────────────────────────

def _save():
    try:
        store_db.save_kv("exit_plans", json.dumps(list(_plans.values())))
    except Exception:
        pass


def _load():
    try:
        raw = store_db.load_kv("exit_plans")
        if not raw:
            return
        with _lock:
            for p in json.loads(raw):
                if isinstance(p, dict) and p.get("id"):
                    _plans[p["id"]] = p
    except Exception:
        pass
