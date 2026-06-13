#!/usr/bin/env python3
"""
Ascent Terminal — Production Scalper Bot
========================================
Exchange : MEXC (via ccxt)
Strategy : EMA cross + RSI filter + ATR-adaptive sizing
Features :
  • ATR-based position sizing (risk % of equity per trade)
  • Taker-fee-aware PnL accounting
  • Redis heartbeat (key: ascent:scalper:heartbeat, TTL 60 s)
  • Prometheus metrics on :8001/metrics
  • Graceful shutdown on SIGINT / SIGTERM
  • Structured JSON logging via structlog
  • Exponential back-off on exchange errors

Required env vars (in .env or system environment):
  MEXC_API_KEY, MEXC_SECRET_KEY
  REDIS_URL            (default: redis://localhost:6379/0)
  SCALPER_SYMBOL       (default: BTC/USDT)
  SCALPER_TIMEFRAME    (default: 1m)
  SCALPER_RISK_PCT     (default: 0.01  → 1 % of equity per trade)
  SCALPER_ATR_PERIOD   (default: 14)
  SCALPER_ATR_MULT     (default: 1.5   → stop = ATR × mult)
  SCALPER_EMA_FAST     (default: 9)
  SCALPER_EMA_SLOW     (default: 21)
  SCALPER_RSI_PERIOD   (default: 14)
  SCALPER_RSI_OB       (default: 70)
  SCALPER_RSI_OS       (default: 30)
  SCALPER_TAKER_FEE    (default: 0.001 → 0.10 %)
  METRICS_PORT         (default: 8001)
"""

import os
import sys
import time
import signal
import logging
import threading
from decimal import Decimal, ROUND_DOWN
from typing import Optional

import ccxt
import numpy as np
import redis
from dotenv import load_dotenv
from prometheus_client import Counter, Gauge, Histogram, start_http_server

try:
    import structlog
    _structlog_available = True
except ImportError:
    _structlog_available = False

load_dotenv()

# ── Logging ─────────────────────────────────────────────────────────────────
if _structlog_available:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    log = structlog.get_logger()
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("scalper")

# ── Config ───────────────────────────────────────────────────────────────────
SYMBOL        = os.getenv("SCALPER_SYMBOL",    "BTC/USDT")
TIMEFRAME     = os.getenv("SCALPER_TIMEFRAME", "1m")
RISK_PCT      = float(os.getenv("SCALPER_RISK_PCT",   "0.01"))
ATR_PERIOD    = int(os.getenv("SCALPER_ATR_PERIOD",   "14"))
ATR_MULT      = float(os.getenv("SCALPER_ATR_MULT",   "1.5"))
EMA_FAST      = int(os.getenv("SCALPER_EMA_FAST",     "9"))
EMA_SLOW      = int(os.getenv("SCALPER_EMA_SLOW",     "21"))
RSI_PERIOD    = int(os.getenv("SCALPER_RSI_PERIOD",   "14"))
RSI_OB        = float(os.getenv("SCALPER_RSI_OB",     "70"))
RSI_OS        = float(os.getenv("SCALPER_RSI_OS",     "30"))
TAKER_FEE     = float(os.getenv("SCALPER_TAKER_FEE",  "0.001"))
METRICS_PORT  = int(os.getenv("METRICS_PORT",          "8001"))
REDIS_URL     = os.getenv("REDIS_URL", "redis://localhost:6379/0")
HEARTBEAT_KEY = "ascent:scalper:heartbeat"
HEARTBEAT_TTL = 60  # seconds

MIN_CANDLES = max(EMA_SLOW, RSI_PERIOD, ATR_PERIOD) + 5

# ── Prometheus metrics ───────────────────────────────────────────────────────
trades_total   = Counter("scalper_trades_total",   "Total trades executed", ["side"])
pnl_gauge      = Gauge(  "scalper_pnl_usdt",       "Cumulative PnL in USDT")
equity_gauge   = Gauge(  "scalper_equity_usdt",    "Current equity in USDT")
latency_hist   = Histogram("scalper_loop_seconds", "Main loop latency")
errors_total   = Counter("scalper_errors_total",   "Exchange/runtime errors")

# ── Helpers ──────────────────────────────────────────────────────────────────
def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    k = 2.0 / (period + 1)
    result = np.empty_like(values)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def rsi(closes: np.ndarray, period: int) -> float:
    """RSI of the last `period` closes."""
    deltas = np.diff(closes[-(period + 1):])
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains.mean()
    avg_loss = losses.mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1 + rs)


def atr(highs: np.ndarray, lows: np.ndarray,
        closes: np.ndarray, period: int) -> float:
    """Average True Range."""
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:]  - closes[:-1]),
        ),
    )
    return float(tr[-period:].mean())


def size_from_atr(equity: float, atr_val: float,
                  atr_mult: float, risk_pct: float,
                  price: float) -> float:
    """
    Position size such that a stop of `atr_mult * atr` away from entry
    risks exactly `risk_pct` of equity.
    """
    stop_distance = atr_val * atr_mult
    if stop_distance <= 0 or price <= 0:
        return 0.0
    risk_usdt = equity * risk_pct
    qty = risk_usdt / stop_distance
    return qty


def fee_adjusted_pnl(entry: float, exit_price: float,
                     qty: float, fee: float) -> float:
    """Net PnL after taker fees on both legs."""
    gross = (exit_price - entry) * qty
    fees  = (entry + exit_price) * qty * fee
    return gross - fees


# ── Redis heartbeat ──────────────────────────────────────────────────────────
class Heartbeat:
    def __init__(self, url: str, key: str, ttl: int):
        try:
            self._r   = redis.from_url(url, socket_connect_timeout=3)
            self._key = key
            self._ttl = ttl
            self._ok  = True
        except Exception as exc:  # noqa: BLE001
            log.warning("heartbeat_redis_unavailable", error=str(exc))
            self._ok = False

    def ping(self):
        if not self._ok:
            return
        try:
            self._r.setex(self._key, self._ttl, "ok")
        except Exception:  # noqa: BLE001
            pass


# ── Main bot class ───────────────────────────────────────────────────────────
class ScalperBot:
    def __init__(self):
        self.exchange = ccxt.mexc({
            "apiKey":    os.environ["MEXC_API_KEY"],
            "secret":    os.environ["MEXC_SECRET_KEY"],
            "enableRateLimit": True,
        })
        self.exchange.load_markets()

        self.heartbeat   = Heartbeat(REDIS_URL, HEARTBEAT_KEY, HEARTBEAT_TTL)
        self.position    = None   # {"side": "long"|"short", "entry": float, "qty": float, "stop": float}
        self.cumulative_pnl = 0.0
        self._stop_event = threading.Event()

        # Register graceful shutdown
        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        log.info("scalper_init", symbol=SYMBOL, timeframe=TIMEFRAME)

    # ── Lifecycle ──────────────────────────────────────────────────────────
    def _shutdown(self, signum, frame):  # noqa: ARG002
        log.info("shutdown_signal_received", signum=signum)
        self._stop_event.set()

    def run(self):
        start_http_server(METRICS_PORT)
        log.info("metrics_server_started", port=METRICS_PORT)

        retry_delay = 5
        while not self._stop_event.is_set():
            try:
                with latency_hist.time():
                    self._tick()
                retry_delay = 5  # reset on success
            except ccxt.NetworkError as exc:
                errors_total.inc()
                log.warning("network_error", error=str(exc), retry_in=retry_delay)
                self._stop_event.wait(retry_delay)
                retry_delay = min(retry_delay * 2, 120)
            except ccxt.ExchangeError as exc:
                errors_total.inc()
                log.error("exchange_error", error=str(exc))
                self._stop_event.wait(retry_delay)
                retry_delay = min(retry_delay * 2, 120)
            except Exception as exc:  # noqa: BLE001
                errors_total.inc()
                log.error("unexpected_error", error=str(exc), exc_info=True)
                self._stop_event.wait(retry_delay)
                retry_delay = min(retry_delay * 2, 120)

        self._close_on_exit()
        log.info("bot_stopped")

    # ── Core tick ─────────────────────────────────────────────────────────
    def _tick(self):
        ohlcv = self.exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=MIN_CANDLES + 10)
        if len(ohlcv) < MIN_CANDLES:
            log.info("waiting_for_candles", have=len(ohlcv), need=MIN_CANDLES)
            time.sleep(10)
            return

        arr    = np.array(ohlcv, dtype=float)
        opens  = arr[:, 1]
        highs  = arr[:, 2]
        lows   = arr[:, 3]
        closes = arr[:, 4]

        fast = ema(closes, EMA_FAST)
        slow = ema(closes, EMA_SLOW)
        rsi_val = rsi(closes, RSI_PERIOD)
        atr_val = atr(highs, lows, closes, ATR_PERIOD)

        price    = closes[-1]
        crossup   = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        crossdown = fast[-2] >= slow[-2] and fast[-1] < slow[-1]

        equity = self._get_equity()
        equity_gauge.set(equity)
        self.heartbeat.ping()

        # ── Exit logic ────────────────────────────────────────────────
        if self.position:
            pos = self.position
            hit_stop = (
                (pos["side"] == "long"  and price <= pos["stop"]) or
                (pos["side"] == "short" and price >= pos["stop"])
            )
            exit_signal = (
                (pos["side"] == "long"  and crossdown) or
                (pos["side"] == "short" and crossup)
            )
            if hit_stop or exit_signal:
                reason = "stop" if hit_stop else "signal"
                self._close_position(price, reason)

        # ── Entry logic ───────────────────────────────────────────────
        if not self.position:
            qty = size_from_atr(equity, atr_val, ATR_MULT, RISK_PCT, price)
            if qty <= 0:
                return
            if crossup and rsi_val < RSI_OB:
                stop = price - atr_val * ATR_MULT
                self._open_position("long", price, qty, stop)
            elif crossdown and rsi_val > RSI_OS:
                stop = price + atr_val * ATR_MULT
                self._open_position("short", price, qty, stop)

        # Sleep until next candle open (approximate)
        self._sleep_until_next_candle()

    # ── Order helpers ──────────────────────────────────────────────────
    def _open_position(self, side: str, price: float,
                        qty: float, stop: float):
        order_side = "buy" if side == "long" else "sell"
        try:
            order = self.exchange.create_market_order(SYMBOL, order_side, qty)
            self.position = {
                "side":  side,
                "entry": float(order.get("average") or price),
                "qty":   qty,
                "stop":  stop,
            }
            trades_total.labels(side=side).inc()
            log.info("position_opened", **self.position)
        except Exception as exc:  # noqa: BLE001
            log.error("open_order_failed", error=str(exc))
            raise

    def _close_position(self, price: float, reason: str):
        if not self.position:
            return
        pos = self.position
        close_side = "sell" if pos["side"] == "long" else "buy"
        try:
            order = self.exchange.create_market_order(
                SYMBOL, close_side, pos["qty"]
            )
            exit_price = float(order.get("average") or price)
            pnl = fee_adjusted_pnl(
                pos["entry"], exit_price, pos["qty"], TAKER_FEE
            )
            self.cumulative_pnl += pnl
            pnl_gauge.set(self.cumulative_pnl)
            log.info(
                "position_closed",
                reason=reason,
                entry=pos["entry"],
                exit=exit_price,
                pnl=round(pnl, 4),
                cumulative_pnl=round(self.cumulative_pnl, 4),
            )
            self.position = None
        except Exception as exc:  # noqa: BLE001
            log.error("close_order_failed", error=str(exc))
            raise

    def _close_on_exit(self):
        """Best-effort close on shutdown."""
        if self.position:
            try:
                ticker = self.exchange.fetch_ticker(SYMBOL)
                price  = ticker["last"]
                self._close_position(price, "shutdown")
            except Exception as exc:  # noqa: BLE001
                log.error("shutdown_close_failed", error=str(exc))

    def _get_equity(self) -> float:
        balance = self.exchange.fetch_balance()
        return float(balance.get("USDT", {}).get("free", 0.0))

    def _sleep_until_next_candle(self):
        """Sleep until (roughly) the next candle opens."""
        tf_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
        }.get(TIMEFRAME, 60)
        now  = time.time()
        wait = tf_seconds - (now % tf_seconds)
        self._stop_event.wait(max(1, wait - 1))  # wake 1 s early


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot = ScalperBot()
    bot.run()
