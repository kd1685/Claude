"""
bots.py — the platform's two automated bots, each running as a background loop
inside the web server and routing orders through the execution bridge.

  TREND BOT (the validated edge)
    EMA30 on daily candles: LONG above, FLAT below (spot — no shorting).
    This is the same strategy as brain/mexc_trend_bot.py and the proof panel.
    Can run PAPER or LIVE — live inherits every gate of the execution bridge
    (EXECUTE_KEY + EXEC_LIVE=true + notional cap + credentials).

  SCALPER (the strategy lab)
    Drives entries from the user's 26-indicator panel config on intraday
    candles (1m/5m/15m). PAPER by default. LIVE is available but sits behind
    every execution-bridge gate (EXECUTE_KEY + EXEC_LIVE=true + notional cap
    + credentials) AND an explicit per-start opt-in — because this engine has
    NOT been backtested/validated. The honest workflow remains: backtest the
    config (Signals tab) -> forward paper-test -> only then consider live.

Shared mechanics:
  * Orders go through execution.execute() — same log, same safety model.
  * Positions + config persist via store_db (kv table) and survive restarts.
  * Loops are daemon threads; every cycle records last_run / last_error and
    keeps going (a feed outage must not kill the bot silently).
  * Starting/stopping/config changes require the EXECUTE_KEY — the bots place
    orders, so they're armed by the same key as the bridge.
"""

import json
import threading
import time
from collections import deque

import exchanges
import indicators
import execution
import store_db

MAX_SYMBOLS = 10
EVENT_LOG = 40                # per-bot in-memory event ring


class _Bot:
    """Common loop/state machinery. Subclasses implement _cycle()."""

    name = "bot"
    source = "bot"
    default_config: dict = {}

    def __init__(self, bot_id: str = "", label: str = ""):
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self.bot_id = bot_id or self.name
        self.label = label or self.name.capitalize()
        self.owner = ""                # key hash16 of the creator ("" = server/owner)
        self.running = False
        self.config = dict(self.default_config)
        self.positions = {}            # symbol -> {side, entry, qty, ts, mode}
        self.events = deque(maxlen=EVENT_LOG)
        self.last_run = None
        self.last_error = None
        self._load()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self, config: dict):
        with self._lock:
            cfg = dict(self.default_config)
            cfg.update({k: v for k, v in (config or {}).items() if k in self.default_config})
            cfg["symbols"] = self._clean_symbols(cfg.get("symbols"))
            if not cfg["symbols"]:
                return {"ok": False, "error": "No valid symbols (use BTC_USDT form, max %d)." % MAX_SYMBOLS}
            self.config = cfg
            if self.running:
                self._log("config updated while running")
                self._save()
                return {"ok": True, "status": self.status_unlocked()}
            self._stop.clear()
            self.running = True
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name=f"apex-{self.bot_id}")
            self._thread.start()
            self._log("started")
            self._save()
            return {"ok": True, "status": self.status_unlocked()}

    def stop(self):
        with self._lock:
            self._stop.set()
            self.running = False
            self._log("stopped")
            self._save()
            return {"ok": True, "status": self.status_unlocked()}

    def status(self):
        with self._lock:
            return self.status_unlocked()

    def status_unlocked(self):
        return {
            "id": self.bot_id,
            "kind": self.name,
            "label": self.label,
            "owner": self.owner,
            "name": self.name,
            "running": self.running,
            "config": dict(self.config),
            "positions": {k: dict(v) for k, v in self.positions.items()},
            "open_positions": len(self.positions),
            "last_run": self.last_run,
            "last_error": self.last_error,
            "events": list(self.events),
        }

    # ── loop ───────────────────────────────────────────────────────────────
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._cycle()
                with self._lock:
                    self.last_run = time.time()
                    self.last_error = None
            except Exception as e:                # never die silently
                with self._lock:
                    self.last_error = str(e)[:200]
                    self._log(f"cycle error: {e}")
            interval = max(15, int(self.config.get("interval_sec", 60)))
            self._stop.wait(interval)

    def _cycle(self):                             # subclass responsibility
        raise NotImplementedError

    # ── orders / positions ─────────────────────────────────────────────────
    def _order(self, symbol, side, price, dry_run, exec_cfg):
        req = {
            "symbol": symbol, "side": side,
            "quote_amount": float(self.config.get("quote_amount", 50)),
            "price": price,                        # paper-fill / sizing reference
            "dry_run": dry_run,
            "execute_key": exec_cfg.get("execute_key", ""),
            "source": self.source,
        }
        return execution.execute(req, exec_cfg)

    def _enter(self, symbol, price, dry_run, exec_cfg):
        res = self._order(symbol, "BUY", price, dry_run, exec_cfg)
        if res["status"] == "ok":
            self.positions[symbol] = {"side": "LONG", "entry": price,
                                      "qty": res["amount"], "ts": time.time(),
                                      "mode": res["mode"]}
            self._log(f"ENTER LONG {symbol} @ {price} ({res['mode']})")
            self._save()
        else:
            self._log(f"enter {symbol} failed: {res['detail'][:80]}")
        return res

    def _exit(self, symbol, price, dry_run, exec_cfg, reason=""):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        res = self._order(symbol, "SELL", price, dry_run, exec_cfg)
        if res["status"] == "ok":
            pnl = (price / pos["entry"] - 1) * 100 if pos["entry"] else 0
            self._log(f"EXIT {symbol} @ {price} ({pnl:+.2f}%) {reason}")
            del self.positions[symbol]
            self._save()
        else:
            self._log(f"exit {symbol} failed: {res['detail'][:80]}")
        return res

    # ── persistence / misc ─────────────────────────────────────────────────
    def _save(self):
        try:
            store_db.save_kv(f"bot_{self.bot_id}", json.dumps({
                "running": self.running, "config": self.config,
                "label": self.label, "owner": self.owner,
                "positions": self.positions}))
        except Exception:
            pass

    def _load(self):
        try:
            raw = store_db.load_kv(f"bot_{self.bot_id}")
            if not raw:
                return
            d = json.loads(raw)
            self.config = {**self.default_config, **(d.get("config") or {})}
            self.positions = d.get("positions") or {}
            if d.get("label"):
                self.label = d["label"]
            self.owner = d.get("owner", "")
            # Bots never auto-restart after a server restart — the owner
            # re-arms them deliberately (positions are preserved for review).
            if d.get("running"):
                self._log("server restarted — bot is stopped; positions preserved, press START to resume")
        except Exception:
            pass

    def _log(self, msg):
        self.events.appendleft({"ts": time.time(), "msg": str(msg)[:160]})

    @staticmethod
    def _clean_symbols(raw):
        if isinstance(raw, str):
            raw = raw.split(",")
        out = []
        for s in raw or []:
            s = str(s).strip().upper().replace("/", "_")
            if s and "_" in s and s not in out:
                out.append(s)
        return out[:MAX_SYMBOLS]


# ─── TREND BOT — EMA30 daily, long/flat ───────────────────────────────────────

class TrendBot(_Bot):
    name = "trend"
    source = "trendbot"
    default_config = {
        "symbols": ["BTC_USDT"],
        "exchange": "",                # falls back to bridge default
        "quote_amount": 50,
        "interval_sec": 900,           # daily signal — 15 min checks are plenty
        "live": False,                 # live still needs every bridge gate
    }

    def _cycle(self):
        from app import cfg_for       # late import (env may change in tests)
        exec_cfg = cfg_for(self.owner)
        exchange = (self.config.get("exchange") or exec_cfg["default_exchange"]).lower()
        exec_cfg["default_exchange"] = exchange
        live = bool(self.config.get("live")) and exec_cfg["live_enabled"]
        dry_run = not live

        for symbol in list(self.config.get("symbols", [])):
            candles = exchanges.fetch_daily(symbol, exchange, 120)
            if len(candles) < 40:
                self._log(f"{symbol}: no daily data from {exchange}")
                continue
            closes = [c["close"] for c in candles]
            ema = _ema_last(closes, 30)
            price = closes[-1]
            want_long = price > ema
            held = symbol in self.positions
            if want_long and not held:
                self._enter(symbol, price, dry_run, exec_cfg)
            elif not held and not want_long:
                pass                                    # flat below EMA — correct
            elif held and not want_long:
                self._exit(symbol, price, dry_run, exec_cfg, "EMA30 flip")


# ─── SCALPER — Indicator Lab config on intraday candles, PAPER ONLY ──────────

class ScalperBot(_Bot):
    name = "scalper"
    source = "scalper"
    default_config = {
        "symbols": ["BTC_USDT"],
        "exchange": "binance",         # needs ccxt intraday OHLCV
        "timeframe": "5m",
        "quote_amount": 50,
        "interval_sec": 60,
        "long_th": 6.5,                # panel score to enter
        "exit_th": 5.0,                # panel score to exit
        "max_positions": 3,
        "enabled": [],                 # indicator keys ([] = panel defaults)
        "weights": {},
        "live": False,                 # UNVALIDATED engine — live is opt-in
    }

    def _cycle(self):
        from app import cfg_for
        exec_cfg = cfg_for(self.owner)
        exchange = (self.config.get("exchange") or "binance").lower()
        exec_cfg["default_exchange"] = exchange
        tf = self.config.get("timeframe") or "5m"
        if tf not in ("1m", "5m", "15m", "1h"):
            tf = "5m"
        long_th = float(self.config.get("long_th", 6.5))
        exit_th = float(self.config.get("exit_th", 5.0))
        max_pos = int(self.config.get("max_positions", 3))
        enabled = self.config.get("enabled") or None
        weights = self.config.get("weights") or None
        live = bool(self.config.get("live")) and exec_cfg["live_enabled"]
        dry_run = not live

        for symbol in list(self.config.get("symbols", [])):
            candles = exchanges.fetch_ohlcv_tf(symbol, exchange, tf, 200)
            if len(candles) < 60:
                self._log(f"{symbol}: no {tf} data from {exchange} (ccxt installed?)")
                continue
            panel = indicators.compute_panel(candles, volumes=None,
                                             enabled=enabled, weights=weights)
            score = panel["score"]
            price = candles[-1]["close"]
            held = symbol in self.positions
            if held and score <= exit_th:
                self._exit(symbol, price, dry_run, exec_cfg, f"score {score:.1f} ≤ {exit_th}")
            elif (not held and score >= long_th
                  and len(self.positions) < max_pos):
                self._enter(symbol, price, dry_run, exec_cfg)


def _ema_last(values, period):
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


# ─── Instance registry — run as many bots as you like (capped) ───────────────
#
# Each instance has an id like "trend-7f3a" with its own config, positions,
# event log and kv persistence. The index of instances survives restarts
# (instances come back STOPPED with positions preserved — the owner re-arms
# deliberately). Legacy single-bot state (kv keys bot_trend / bot_scalper)
# migrates automatically into a default instance of each kind.

import uuid

MAX_INSTANCES = 8
TYPES = {"trend": TrendBot, "scalper": ScalperBot}

REGISTRY: "dict[str, _Bot]" = {}
_reg_lock = threading.Lock()


def _save_index():
    try:
        store_db.save_kv("bot_index", json.dumps(
            [{"id": b.bot_id, "kind": b.name, "label": b.label}
             for b in REGISTRY.values()]))
    except Exception:
        pass


def create(kind: str, label: str = "", owner: str = ""):
    kind = (kind or "").strip().lower()
    cls = TYPES.get(kind)
    if not cls:
        return {"ok": False, "error": f"Unknown bot kind {kind!r} (trend | scalper)."}
    with _reg_lock:
        if len(REGISTRY) >= MAX_INSTANCES:
            return {"ok": False, "error": f"Instance limit reached ({MAX_INSTANCES})."}
        bot_id = f"{kind}-{uuid.uuid4().hex[:6]}"
        n = sum(1 for b in REGISTRY.values() if b.name == kind) + 1
        bot = cls(bot_id, label or f"{kind.capitalize()} bot {n}")
        bot.owner = owner or ""
        REGISTRY[bot_id] = bot
        bot._save()
        _save_index()
        return {"ok": True, "bot": bot.status()}


def delete(bot_id: str):
    with _reg_lock:
        bot = REGISTRY.get(bot_id)
        if not bot:
            return {"ok": False, "error": "Unknown bot id."}
        if bot.running:
            bot.stop()
        del REGISTRY[bot_id]
        try:
            store_db.delete_kv(f"bot_{bot_id}")
        except Exception:
            pass
        _save_index()
        return {"ok": True}


def get(bot_id: str):
    return REGISTRY.get(bot_id)


def all_status():
    return [b.status() for b in REGISTRY.values()]


def _boot():
    """Rebuild instances from the saved index; migrate legacy singletons."""
    loaded = []
    try:
        raw = store_db.load_kv("bot_index")
        loaded = json.loads(raw) if raw else []
    except Exception:
        loaded = []
    with _reg_lock:
        for rec in loaded:
            kind, bot_id = rec.get("kind"), rec.get("id")
            cls = TYPES.get(kind)
            if cls and bot_id and bot_id not in REGISTRY:
                REGISTRY[bot_id] = cls(bot_id, rec.get("label") or "")
        if not REGISTRY:                      # fresh DB or legacy install
            for kind, cls in TYPES.items():
                # legacy kv key "bot_trend"/"bot_scalper" loads transparently
                # because the default instance id == the kind name
                REGISTRY[kind] = cls(kind, f"{kind.capitalize()} bot 1")
        _save_index()


_boot()

# Back-compat aliases (older code/tests referenced these)
TREND = next((b for b in REGISTRY.values() if b.name == "trend"), None)
SCALPER = next((b for b in REGISTRY.values() if b.name == "scalper"), None)
BOTS = REGISTRY
