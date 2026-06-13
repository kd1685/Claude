#!/usr/bin/env python3
"""
Ascent Terminal — MEXC Trend / Swing Bot
=========================================
Strategy  : EMA cross + RSI filter + ADX regime gate
Sizing     : Kelly Criterion (half-Kelly by default)
Risk mgmt :
  • Per-trade stop = ATR × multiplier
  • Drawdown circuit-breaker (halts new entries if DD > threshold)
  • Position reconciliation on startup (reads live open orders)
Exchange  : MEXC via ccxt
Monitoring: Redis heartbeat + Prometheus metrics

Required env vars:
  MEXC_API_KEY, MEXC_SECRET_KEY
  REDIS_URL            (default: redis://localhost:6379/0)

Optional env vars (all have defaults):
  TREND_SYMBOL          BTC/USDT
  TREND_TIMEFRAME       4h
  TREND_EMA_FAST        9
  TREND_EMA_SLOW        21
  TREND_RSI_PERIOD      14
  TREND_ATR_PERIOD      14
  TREND_ADX_PERIOD      14
  TREND_ADX_MIN         20        (ADX threshold for regime filter)
  TREND_ATR_MULT        2.0       (stop distance in ATR units)
  TREND_KELLY_FRAC      0.5       (half-Kelly by default)
  TREND_MAX_KELLY       0.20      (cap Kelly at 20 % of equity)
  TREND_DD_HALT         0.10      (halt if drawdown > 10 %)
  TREND_TAKER_FEE       0.001
  METRICS_PORT          8002
"""

import os
import sys
import time
import math
import signal
import logging
import threading
from typing import Optional, Dict, List

import ccxt
import numpy as np
import redis
from dotenv import load_dotenv
from prometheus_client import Counter, Gauge, Histogram, start_http_server

try:
    import structlog
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
except ImportError:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("trend_bot")

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL      = os.getenv("TREND_SYMBOL",     "BTC/USDT")
TIMEFRAME   = os.getenv("TREND_TIMEFRAME",  "4h")
EMA_FAST    = int(os.getenv("TREND_EMA_FAST",    "9"))
EMA_SLOW    = int(os.getenv("TREND_EMA_SLOW",    "21"))
RSI_PERIOD  = int(os.getenv("TREND_RSI_PERIOD",  "14"))
ATR_PERIOD  = int(os.getenv("TREND_ATR_PERIOD",  "14"))
ADX_PERIOD  = int(os.getenv("TREND_ADX_PERIOD",  "14"))
ADX_MIN     = float(os.getenv("TREND_ADX_MIN",   "20.0"))
ATR_MULT    = float(os.getenv("TREND_ATR_MULT",  "2.0"))
KELLY_FRAC  = float(os.getenv("TREND_KELLY_FRAC","0.5"))
MAX_KELLY   = float(os.getenv("TREND_MAX_KELLY", "0.20"))
DD_HALT     = float(os.getenv("TREND_DD_HALT",   "0.10"))
TAKER_FEE   = float(os.getenv("TREND_TAKER_FEE", "0.001"))
METRICS_PORT= int(os.getenv("METRICS_PORT",       "8002"))
REDIS_URL   = os.getenv("REDIS_URL", "redis://localhost:6379/0")

HEARTBEAT_KEY = "ascent:trend:heartbeat"
HEARTBEAT_TTL = 300
MIN_CANDLES   = max(EMA_SLOW, RSI_PERIOD, ATR_PERIOD, ADX_PERIOD * 2) + 10

# ── Prometheus ────────────────────────────────────────────────────────────────
trades_ctr  = Counter(  "trend_trades_total",  "Total trend-bot trades", ["side"])
pnl_gauge   = Gauge(    "trend_pnl_usdt",      "Cumulative PnL")
equity_g    = Gauge(    "trend_equity_usdt",   "Current equity")
dd_gauge    = Gauge(    "trend_drawdown",      "Current drawdown fraction")
latency_h   = Histogram("trend_loop_seconds",  "Loop latency")
errors_ctr  = Counter(  "trend_errors_total",  "Errors")


# ── Indicators ────────────────────────────────────────────────────────────────
def _ema(arr: np.ndarray, n: int) -> np.ndarray:
    k = 2.0 / (n + 1)
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out


def _rsi(closes: np.ndarray, n: int) -> np.ndarray:
    delta = np.diff(closes.astype(float))
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_g = np.full(len(closes), np.nan)
    avg_l = np.full(len(closes), np.nan)
    if n < len(gain):
        avg_g[n] = gain[:n].mean()
        avg_l[n] = loss[:n].mean()
        for i in range(n + 1, len(closes)):
            avg_g[i] = (avg_g[i-1] * (n-1) + gain[i-1]) / n
            avg_l[i] = (avg_l[i-1] * (n-1) + loss[i-1]) / n
    rs = np.where(avg_l == 0, 100.0, avg_g / avg_l)
    return np.where(np.isnan(avg_g), np.nan, 100.0 - 100.0 / (1 + rs))


def _atr(highs: np.ndarray, lows: np.ndarray,
         closes: np.ndarray, n: int) -> np.ndarray:
    h, l, c = highs.astype(float), lows.astype(float), closes.astype(float)
    tr = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    out = np.full(len(c), np.nan)
    if n <= len(tr):
        out[n] = tr[:n].mean()
        for i in range(n + 1, len(c)):
            out[i] = (out[i-1] * (n-1) + tr[i-1]) / n
    return out


def _adx(highs: np.ndarray, lows: np.ndarray,
         closes: np.ndarray, n: int) -> np.ndarray:
    h, l, c = highs.astype(float), lows.astype(float), closes.astype(float)
    up   = np.diff(h);  down = -np.diff(l)
    dm_p = np.where((up > down) & (up > 0), up,   0.0)
    dm_n = np.where((down > up) & (down > 0), down, 0.0)
    tr   = np.maximum(
        h[1:] - l[1:],
        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])),
    )
    length = len(h)
    atr_s  = np.full(length, np.nan)
    dmp_s  = np.full(length, np.nan)
    dmn_s  = np.full(length, np.nan)
    adx_v  = np.full(length, np.nan)

    if n < len(tr):
        atr_s[n] = tr[:n].mean()
        dmp_s[n] = dm_p[:n].mean()
        dmn_s[n] = dm_n[:n].mean()
        for i in range(n + 1, length):
            atr_s[i] = (atr_s[i-1]*(n-1) + tr[i-1])    / n
            dmp_s[i] = (dmp_s[i-1]*(n-1) + dm_p[i-1])  / n
            dmn_s[i] = (dmn_s[i-1]*(n-1) + dm_n[i-1])  / n

    with np.errstate(invalid="ignore", divide="ignore"):
        di_p = 100 * dmp_s / atr_s
        di_n = 100 * dmn_s / atr_s
        dx   = 100 * np.abs(di_p - di_n) / (di_p + di_n)

    start2 = 2 * n
    if start2 < length:
        adx_v[start2] = np.nanmean(dx[n:start2])
        for i in range(start2 + 1, length):
            adx_v[i] = (adx_v[i-1] * (n-1) + dx[i]) / n
    return adx_v


# ── Kelly sizing ──────────────────────────────────────────────────────────────
def kelly_size(equity: float, win_rate: float, avg_win: float,
               avg_loss: float, frac: float, cap: float) -> float:
    """
    Half-Kelly position size as fraction of equity.
    Returns USDT amount to risk.
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return equity * 0.01  # fallback: 1 %
    b    = avg_win / avg_loss
    q    = 1 - win_rate
    k    = (b * win_rate - q) / b          # full Kelly fraction
    k    = max(0.0, k * frac)             # half-Kelly, floor at 0
    k    = min(k, cap)                    # cap
    return equity * k


# ── Heartbeat ─────────────────────────────────────────────────────────────────
class Heartbeat:
    def __init__(self, url: str, key: str, ttl: int):
        try:
            self._r  = redis.from_url(url, socket_connect_timeout=3)
            self._k  = key
            self._t  = ttl
            self._ok = True
        except Exception as exc:
            log.warning("redis_unavailable", error=str(exc))
            self._ok = False

    def ping(self):
        if self._ok:
            try: self._r.setex(self._k, self._t, "ok")
            except Exception: pass


# ── Bot ───────────────────────────────────────────────────────────────────────
class TrendBot:
    def __init__(self):
        self.exchange = ccxt.mexc({
            "apiKey": os.environ["MEXC_API_KEY"],
            "secret": os.environ["MEXC_SECRET_KEY"],
            "enableRateLimit": True,
        })
        self.exchange.load_markets()

        self.hb            = Heartbeat(REDIS_URL, HEARTBEAT_KEY, HEARTBEAT_TTL)
        self.position: Optional[Dict] = None
        self.cum_pnl       = 0.0
        self.peak_equity   = None
        self.trade_history: List[float] = []   # list of trade PnLs for Kelly
        self._stop         = threading.Event()

        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        self._reconcile_position()
        log.info("trend_bot_init", symbol=SYMBOL, timeframe=TIMEFRAME)

    # ── Shutdown ───────────────────────────────────────────────────────────
    def _shutdown(self, signum, frame):
        log.info("shutdown", signum=signum)
        self._stop.set()

    # ── Position reconciliation ────────────────────────────────────────────
    def _reconcile_position(self):
        """
        On startup, check the exchange for any open position/orders
        for SYMBOL and set self.position accordingly so we don't
        double-up or ignore an existing trade.
        """
        try:
            balance = self.exchange.fetch_balance()
            base    = SYMBOL.split("/")[0]   # e.g. "BTC"
            held    = float(balance.get(base, {}).get("total", 0.0))
            if held > 0:
                # We have a long position; estimate entry from open orders
                # or use last ticker as a proxy.
                ticker = self.exchange.fetch_ticker(SYMBOL)
                price  = ticker["last"]
                atr_proxy = price * 0.015   # ~1.5 % proxy stop until real ATR
                self.position = {
                    "side":  "long",
                    "entry": price,
                    "qty":   held,
                    "stop":  price - atr_proxy,
                    "reconciled": True,
                }
                log.info("reconciled_long", qty=held, proxy_entry=price)
        except Exception as exc:
            log.warning("reconcile_failed", error=str(exc))

    # ── Drawdown check ─────────────────────────────────────────────────────
    def _check_drawdown(self, equity: float) -> bool:
        """Returns True if trading is halted due to drawdown."""
        if self.peak_equity is None:
            self.peak_equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        dd = (self.peak_equity - equity) / self.peak_equity
        dd_gauge.set(dd)
        if dd >= DD_HALT:
            log.warning("drawdown_halt", drawdown=round(dd, 4))
            return True
        return False

    # ── Kelly helper ───────────────────────────────────────────────────────
    def _kelly_usdt(self, equity: float) -> float:
        if len(self.trade_history) < 10:
            return equity * 0.01    # not enough data; use 1 %
        arr      = np.array(self.trade_history[-50:])   # recent 50 trades
        wins     = arr[arr > 0]
        losses   = np.abs(arr[arr < 0])
        win_rate = len(wins) / len(arr)
        avg_win  = wins.mean()   if len(wins)   > 0 else 0.0
        avg_loss = losses.mean() if len(losses) > 0 else 1.0
        return kelly_size(equity, win_rate, avg_win, avg_loss,
                          KELLY_FRAC, MAX_KELLY)

    # ── Main loop ──────────────────────────────────────────────────────────
    def run(self):
        start_http_server(METRICS_PORT)
        log.info("metrics_server_started", port=METRICS_PORT)

        retry = 5
        while not self._stop.is_set():
            try:
                with latency_h.time():
                    self._tick()
                retry = 5
            except ccxt.NetworkError as e:
                errors_ctr.inc()
                log.warning("network_error", err=str(e), retry=retry)
                self._stop.wait(retry); retry = min(retry*2, 300)
            except ccxt.ExchangeError as e:
                errors_ctr.inc()
                log.error("exchange_error", err=str(e))
                self._stop.wait(retry); retry = min(retry*2, 300)
            except Exception as e:
                errors_ctr.inc()
                log.error("unexpected", err=str(e), exc_info=True)
                self._stop.wait(retry); retry = min(retry*2, 300)

        self._emergency_close()
        log.info("bot_stopped")

    # ── Tick ───────────────────────────────────────────────────────────────
    def _tick(self):
        ohlcv = self.exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=MIN_CANDLES + 20)
        if len(ohlcv) < MIN_CANDLES:
            log.info("insufficient_candles", have=len(ohlcv))
            self._stop.wait(60)
            return

        arr    = np.array(ohlcv, dtype=float)
        highs  = arr[:, 2]; lows = arr[:, 3]; closes = arr[:, 4]

        fast   = _ema(closes, EMA_FAST)
        slow   = _ema(closes, EMA_SLOW)
        rsi_v  = _rsi(closes, RSI_PERIOD)
        atr_v  = _atr(highs, lows, closes, ATR_PERIOD)
        adx_v  = _adx(highs, lows, closes, ADX_PERIOD)

        price     = closes[-1]
        crossup   = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        crossdown = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
        in_trend  = not np.isnan(adx_v[-1]) and adx_v[-1] >= ADX_MIN

        equity = self._get_equity()
        equity_g.set(equity)
        self.hb.ping()

        if self._check_drawdown(equity):
            # Still manage existing position but don't open new ones
            if self.position:
                self._check_exit(price, crossdown, crossup)
            self._sleep_candle()
            return

        # ── Exit ──────────────────────────────────────────────────────
        if self.position:
            self._check_exit(price, crossdown, crossup)

        # ── Entry ─────────────────────────────────────────────────────
        if not self.position and in_trend:
            risk_usdt = self._kelly_usdt(equity)
            stop_dist = float(atr_v[-1]) * ATR_MULT if not np.isnan(atr_v[-1]) else 0
            if stop_dist <= 0:
                self._sleep_candle(); return
            qty = risk_usdt / stop_dist
            if qty <= 0:
                self._sleep_candle(); return

            if crossup and not np.isnan(rsi_v[-1]) and rsi_v[-1] < 70:
                self._open("long",  price, qty, price - stop_dist)
            elif crossdown and not np.isnan(rsi_v[-1]) and rsi_v[-1] > 30:
                self._open("short", price, qty, price + stop_dist)

        self._sleep_candle()

    def _check_exit(self, price: float, crossdown: bool, crossup: bool):
        pos = self.position
        hit = (
            (pos["side"] == "long"  and price <= pos["stop"]) or
            (pos["side"] == "short" and price >= pos["stop"])
        )
        sig = (
            (pos["side"] == "long"  and crossdown) or
            (pos["side"] == "short" and crossup)
        )
        if hit or sig:
            self._close(price, "stop" if hit else "signal")

    # ── Orders ────────────────────────────────────────────────────────────
    def _open(self, side: str, price: float, qty: float, stop: float):
        order_side = "buy" if side == "long" else "sell"
        try:
            order = self.exchange.create_market_order(SYMBOL, order_side, qty)
            self.position = {
                "side":  side,
                "entry": float(order.get("average") or price),
                "qty":   qty,
                "stop":  stop,
            }
            trades_ctr.labels(side=side).inc()
            log.info("opened", **self.position)
        except Exception as exc:
            log.error("open_failed", error=str(exc)); raise

    def _close(self, price: float, reason: str):
        pos = self.position
        side = "sell" if pos["side"] == "long" else "buy"
        try:
            order      = self.exchange.create_market_order(SYMBOL, side, pos["qty"])
            exit_price = float(order.get("average") or price)
            gross      = (exit_price - pos["entry"]) * pos["qty"] \
                         if pos["side"] == "long" \
                         else (pos["entry"] - exit_price) * pos["qty"]
            fees  = (pos["entry"] + exit_price) * pos["qty"] * TAKER_FEE
            pnl   = gross - fees
            self.cum_pnl += pnl
            self.trade_history.append(pnl)
            pnl_gauge.set(self.cum_pnl)
            log.info("closed", reason=reason, pnl=round(pnl, 4),
                     cum=round(self.cum_pnl, 4))
            self.position = None
        except Exception as exc:
            log.error("close_failed", error=str(exc)); raise

    def _emergency_close(self):
        if self.position:
            try:
                t = self.exchange.fetch_ticker(SYMBOL)
                self._close(t["last"], "shutdown")
            except Exception as exc:
                log.error("emergency_close_failed", error=str(exc))

    def _get_equity(self) -> float:
        b = self.exchange.fetch_balance()
        return float(b.get("USDT", {}).get("free", 0.0))

    def _sleep_candle(self):
        tf_sec = {
            "1m":60,"3m":180,"5m":300,"15m":900,
            "30m":1800,"1h":3600,"4h":14400,"1d":86400,
        }.get(TIMEFRAME, 3600)
        now  = time.time()
        wait = tf_sec - (now % tf_sec)
        self._stop.wait(max(1, wait - 2))


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TrendBot().run()
