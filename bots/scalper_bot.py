#!/usr/bin/env python3
"""
AscentTerminal Scalper Bot — standalone version
================================================
This is the standalone version of the scalper bot for users who want to run it
outside the AscentTerminal platform. It implements the same indicator-based
scalping strategy as the in-platform ScalperBot.

FEATURES
--------
- 26-indicator panel (same weights/logic as the platform)
- Configurable signal threshold (default: score >= 6.0 to enter)
- Multi-exchange support via ccxt (Binance, Bybit, OKX, MEXC, KuCoin, etc.)
- Paper trading mode (default) and live mode
- Position management: max 1 position per symbol
- Risk management: stop-loss and take-profit
- Detailed logging

USAGE
-----
    python scalper_bot.py                          # paper mode, BTCUSDT on Binance
    python scalper_bot.py --live                   # LIVE — real orders
    python scalper_bot.py --symbol ETHUSDT --exchange bybit
    python scalper_bot.py --config myconfig.json   # load full config from file

CONFIG FILE (optional, JSON)
-----------------------------
    {
      "exchange": "binance",
      "api_key": "...",
      "api_secret": "...",
      "symbol": "BTCUSDT",
      "timeframe": "5m",
      "live": false,
      "log_level": "INFO",
      "risk": {
        "max_position_pct": 0.02,
        "stop_loss_pct": 0.005,
        "take_profit_pct": 0.010
      },
      "signal": {
        "entry_threshold": 6.0,
        "exit_threshold": 4.0
      }
    }

IMPORTANT
---------
- Use TRADE-ONLY API keys with WITHDRAWAL DISABLED.
- This bot implements a research-grade indicator scalping strategy.
  The platform's validated edge is the EMA30 daily TREND, not scalping.
  Scalping indicator signals have NOT been shown to beat fees at scale.
  Use in paper mode first and study the results before going live.
- You are solely responsible for all trading decisions and losses.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

try:
    import ccxt
except ImportError:
    sys.exit("ccxt not installed — run: pip install ccxt")

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

log = logging.getLogger("scalper")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskConfig:
    max_position_pct: float = 0.02      # 2% of balance per trade
    stop_loss_pct: float    = 0.005     # 0.5% stop-loss
    take_profit_pct: float  = 0.010     # 1.0% take-profit


@dataclass
class SignalConfig:
    entry_threshold: float = 6.0   # panel score >= this to go long
    exit_threshold: float  = 4.0   # panel score <= this to exit


@dataclass
class BotConfig:
    exchange: str     = "binance"
    api_key: str      = ""
    api_secret: str   = ""
    symbol: str       = "BTC/USDT"
    timeframe: str    = "5m"
    live: bool        = False
    log_level: str    = "INFO"
    risk: RiskConfig  = field(default_factory=RiskConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    poll_interval: int = 60   # seconds between candle checks

    @classmethod
    def from_dict(cls, d: dict) -> "BotConfig":
        cfg = cls()
        for k in ("exchange", "api_key", "api_secret", "symbol",
                  "timeframe", "live", "log_level", "poll_interval"):
            if k in d:
                setattr(cfg, k, d[k])
        if "risk" in d:
            r = d["risk"]
            cfg.risk = RiskConfig(
                max_position_pct=r.get("max_position_pct", cfg.risk.max_position_pct),
                stop_loss_pct=r.get("stop_loss_pct", cfg.risk.stop_loss_pct),
                take_profit_pct=r.get("take_profit_pct", cfg.risk.take_profit_pct),
            )
        if "signal" in d:
            s = d["signal"]
            cfg.signal = SignalConfig(
                entry_threshold=s.get("entry_threshold", cfg.signal.entry_threshold),
                exit_threshold=s.get("exit_threshold", cfg.signal.exit_threshold),
            )
        # normalise symbol: "BTCUSDT" → "BTC/USDT"
        if "/" not in cfg.symbol and len(cfg.symbol) >= 6:
            cfg.symbol = cfg.symbol[:-4] + "/" + cfg.symbol[-4:]
        return cfg

    @classmethod
    def from_file(cls, path: str) -> "BotConfig":
        with open(path) as f:
            return cls.from_dict(json.load(f))


# ──────────────────────────────────────────────────────────────────────────────
# Indicator maths (pure Python, no external deps beyond ccxt)
# ──────────────────────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    out: list[float | None] = [None] * (period - 1)
    prev = sum(values[:period]) / period
    out.append(prev)
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        out.append(sum(values[i - period + 1:i + 1]) / period)
    return out


def _stdev(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        out.append(math.sqrt(variance))
    return out


def _rsi(closes: list[float], period: int = 14) -> list[float | None]:
    if len(closes) < period + 1:
        return [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    out: list[float | None] = [None] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_val(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - 100 / (1 + rs)

    out.append(_rsi_val(avg_gain, avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(_rsi_val(avg_gain, avg_loss))
    return out


def _macd(closes: list[float],
          fast: int = 12, slow: int = 26, signal: int = 9
          ) -> tuple[list[float | None], list[float | None], list[float | None]]:
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line: list[float | None] = []
    for f, s in zip(ema_fast, ema_slow):
        macd_line.append(f - s if f is not None and s is not None else None)
    valid = [v for v in macd_line if v is not None]
    sig_raw = _ema(valid, signal)
    sig_line: list[float | None] = [None] * (len(macd_line) - len(valid))
    sig_line += [None] * (signal - 1)
    sig_line += sig_raw[signal - 1:]
    hist: list[float | None] = []
    for m, s in zip(macd_line, sig_line):
        hist.append(m - s if m is not None and s is not None else None)
    return macd_line, sig_line, hist


def _bollinger(closes: list[float], period: int = 20,
               std_mult: float = 2.0
               ) -> tuple[list[float | None], list[float | None], list[float | None]]:
    mid = _sma(closes, period)
    std = _stdev(closes, period)
    upper = [m + std_mult * s if m is not None and s is not None else None
             for m, s in zip(mid, std)]
    lower = [m - std_mult * s if m is not None and s is not None else None
             for m, s in zip(mid, std)]
    return upper, mid, lower


def _atr(highs: list[float], lows: list[float], closes: list[float],
         period: int = 14) -> list[float | None]:
    trs: list[float] = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    out: list[float | None] = [None] * period
    prev = sum(trs[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        out.append(prev)
    return out


def _stoch(closes: list[float], highs: list[float], lows: list[float],
           k_period: int = 14, d_period: int = 3
           ) -> tuple[list[float | None], list[float | None]]:
    k: list[float | None] = []
    for i in range(len(closes)):
        if i < k_period - 1:
            k.append(None)
        else:
            lo = min(lows[i - k_period + 1:i + 1])
            hi = max(highs[i - k_period + 1:i + 1])
            if hi == lo:
                k.append(50.0)
            else:
                k.append((closes[i] - lo) / (hi - lo) * 100)
    valid_k = [v for v in k if v is not None]
    d_raw = _sma(valid_k, d_period)
    d: list[float | None] = [None] * (len(k) - len(valid_k))
    d += [None] * (d_period - 1)
    d += d_raw[d_period - 1:]
    return k, d


def _williams_r(closes: list[float], highs: list[float], lows: list[float],
                period: int = 14) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(closes)):
        if i < period - 1:
            out.append(None)
        else:
            lo = min(lows[i - period + 1:i + 1])
            hi = max(highs[i - period + 1:i + 1])
            if hi == lo:
                out.append(-50.0)
            else:
                out.append((hi - closes[i]) / (hi - lo) * -100)
    return out


def _cci(closes: list[float], highs: list[float], lows: list[float],
         period: int = 20) -> list[float | None]:
    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    out: list[float | None] = []
    for i in range(len(typical)):
        if i < period - 1:
            out.append(None)
        else:
            window = typical[i - period + 1:i + 1]
            mean = sum(window) / period
            mad = sum(abs(x - mean) for x in window) / period
            out.append((typical[i] - mean) / (0.015 * mad) if mad else 0.0)
    return out


def _mfi(closes: list[float], highs: list[float], lows: list[float],
         volumes: list[float], period: int = 14) -> list[float | None]:
    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    raw_mf = [t * v for t, v in zip(typical, volumes)]
    out: list[float | None] = [None]
    for i in range(1, len(typical)):
        if i < period:
            out.append(None)
        else:
            pos = sum(raw_mf[j] for j in range(i - period + 1, i + 1)
                      if typical[j] > typical[j - 1])
            neg = sum(raw_mf[j] for j in range(i - period + 1, i + 1)
                      if typical[j] < typical[j - 1])
            if neg == 0:
                out.append(100.0)
            else:
                out.append(100 - 100 / (1 + pos / neg))
    return out


def _adx(closes: list[float], highs: list[float], lows: list[float],
         period: int = 14) -> list[float | None]:
    """Simplified ADX (Wilder's smoothing)."""
    if len(closes) < period * 2:
        return [None] * len(closes)
    trs, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        trs.append(tr)
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)

    def smooth(arr: list[float]) -> list[float]:
        out2 = [sum(arr[:period])]
        for v in arr[period:]:
            out2.append(out2[-1] - out2[-1] / period + v)
        return out2

    str_ = smooth(trs)
    pdm = smooth(plus_dm)
    ndm = smooth(minus_dm)
    di_plus  = [100 * p / t if t else 0 for p, t in zip(pdm, str_)]
    di_minus = [100 * n / t if t else 0 for n, t in zip(ndm, str_)]
    dx = [abs(p - n) / (p + n) * 100 if (p + n) else 0
          for p, n in zip(di_plus, di_minus)]
    adx_vals: list[float] = [sum(dx[:period]) / period]
    for v in dx[period:]:
        adx_vals.append((adx_vals[-1] * (period - 1) + v) / period)
    out: list[float | None] = [None] * (len(closes) - len(adx_vals))
    out += [None] * (period - 1)
    out += adx_vals
    return out


def _obv(closes: list[float], volumes: list[float]) -> list[float]:
    obv_vals = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv_vals.append(obv_vals[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv_vals.append(obv_vals[-1] - volumes[i])
        else:
            obv_vals.append(obv_vals[-1])
    return obv_vals


def _vwap(closes: list[float], highs: list[float], lows: list[float],
          volumes: list[float]) -> list[float]:
    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    cum_tv = cum_v = 0.0
    out = []
    for t, v in zip(typical, volumes):
        cum_tv += t * v
        cum_v += v
        out.append(cum_tv / cum_v if cum_v else t)
    return out


def _psar(highs: list[float], lows: list[float],
          af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2
          ) -> list[float | None]:
    if len(highs) < 2:
        return [None] * len(highs)
    bull = True
    sar = lows[0]
    ep  = highs[0]
    af  = af_start
    out: list[float | None] = [None]
    for i in range(1, len(highs)):
        sar = sar + af * (ep - sar)
        if bull:
            sar = min(sar, lows[i - 1], lows[i - 2] if i >= 2 else lows[i - 1])
            if lows[i] < sar:
                bull = False; sar = ep; ep = lows[i]; af = af_start
            else:
                if highs[i] > ep:
                    ep = highs[i]; af = min(af + af_step, af_max)
        else:
            sar = max(sar, highs[i - 1], highs[i - 2] if i >= 2 else highs[i - 1])
            if highs[i] > sar:
                bull = True; sar = ep; ep = highs[i]; af = af_start
            else:
                if lows[i] < ep:
                    ep = lows[i]; af = min(af + af_step, af_max)
        out.append(sar)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Panel scorer  (same 26-indicator logic as platform/indicators.py)
# ──────────────────────────────────────────────────────────────────────────────

# (name, weight)
_INDICATOR_WEIGHTS: list[tuple[str, float]] = [
    ("ema9",       1.0),
    ("ema21",      1.0),
    ("ema50",      1.5),
    ("ema200",     2.0),
    ("sma20",      1.0),
    ("sma50",      1.5),
    ("sma200",     2.0),
    ("rsi",        1.5),
    ("macd",       1.5),
    ("boll_pct",   1.0),
    ("boll_bw",    0.5),
    ("stoch_k",    1.0),
    ("stoch_kd",   1.0),
    ("williams_r", 1.0),
    ("cci",        1.0),
    ("mfi",        1.0),
    ("adx",        1.0),
    ("psar",       1.5),
    ("obv_trend",  1.0),
    ("vwap",       1.5),
    ("vol_trend",  0.5),
    ("atr_trend",  0.5),
    ("ema9_21",    1.0),
    ("ema21_50",   1.0),
    ("price_ema50",1.5),
    ("price_ema200",2.0),
]


def compute_panel_score(candles: list[dict]) -> float | None:
    """
    Given a list of OHLCV dicts ({open, high, low, close, volume}),
    return a bullish score on a 0–10 scale (>5 = bullish bias).
    Returns None if there's not enough data.
    """
    if len(candles) < 220:
        return None

    closes  = [c["close"]  for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    volumes = [c["volume"] for c in candles]
    price   = closes[-1]

    # ── compute all series ──────────────────────────────────────────────────
    ema9   = _ema(closes, 9)
    ema21  = _ema(closes, 21)
    ema50  = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    sma20  = _sma(closes, 20)
    sma50  = _sma(closes, 50)
    sma200 = _sma(closes, 200)
    rsi14  = _rsi(closes, 14)
    macd_l, macd_sig, macd_hist = _macd(closes)
    bb_up, bb_mid, bb_low = _bollinger(closes, 20)
    stoch_k, stoch_d = _stoch(closes, highs, lows)
    will_r = _williams_r(closes, highs, lows)
    cci14  = _cci(closes, highs, lows, 20)
    mfi14  = _mfi(closes, highs, lows, volumes)
    adx14  = _adx(closes, highs, lows)
    psar   = _psar(highs, lows)
    obv    = _obv(closes, volumes)
    vwap   = _vwap(closes, highs, lows, volumes)
    atr14  = _atr(highs, lows, closes)

    def last(series: list) -> float | None:
        for v in reversed(series):
            if v is not None:
                return v
        return None

    # ── vote for each indicator ─────────────────────────────────────────────
    votes: dict[str, float] = {}

    def _vote(name: str, bull: bool | None) -> None:
        if bull is None:
            votes[name] = 0.5
        else:
            votes[name] = 1.0 if bull else 0.0

    v_ema9   = last(ema9)
    v_ema21  = last(ema21)
    v_ema50  = last(ema50)
    v_ema200 = last(ema200)
    v_sma20  = last(sma20)
    v_sma50  = last(sma50)
    v_sma200 = last(sma200)
    v_rsi    = last(rsi14)
    v_macd_h = last(macd_hist)
    v_macd_l = last(macd_l)
    v_bb_up  = last(bb_up)
    v_bb_low = last(bb_low)
    v_bb_mid = last(bb_mid)
    v_sk     = last(stoch_k)
    v_sd     = last(stoch_d)
    v_wr     = last(will_r)
    v_cci    = last(cci14)
    v_mfi    = last(mfi14)
    v_adx    = last(adx14)
    v_psar   = last(psar)
    v_obv_l  = obv[-1]  if obv else None
    v_obv_p  = obv[-20] if len(obv) >= 20 else None
    v_vwap   = last(vwap)
    v_vol_c  = volumes[-1]
    v_vol_p  = volumes[-20] if len(volumes) >= 20 else None
    v_atr_c  = last(atr14)
    v_atr_p  = atr14[-20] if len(atr14) >= 20 and atr14[-20] is not None else None

    _vote("ema9",    price > v_ema9   if v_ema9   else None)
    _vote("ema21",   price > v_ema21  if v_ema21  else None)
    _vote("ema50",   price > v_ema50  if v_ema50  else None)
    _vote("ema200",  price > v_ema200 if v_ema200 else None)
    _vote("sma20",   price > v_sma20  if v_sma20  else None)
    _vote("sma50",   price > v_sma50  if v_sma50  else None)
    _vote("sma200",  price > v_sma200 if v_sma200 else None)

    if v_rsi is not None:
        _vote("rsi", v_rsi > 50)
    else:
        votes["rsi"] = 0.5

    _vote("macd", v_macd_h > 0 if v_macd_h is not None else None)

    # Bollinger percent-B
    if v_bb_up is not None and v_bb_low is not None and v_bb_up != v_bb_low:
        pct_b = (price - v_bb_low) / (v_bb_up - v_bb_low)
        _vote("boll_pct", pct_b > 0.5)
        bw = (v_bb_up - v_bb_low) / v_bb_mid if v_bb_mid else None
        _vote("boll_bw", bw > 0.05 if bw is not None else None)
    else:
        votes["boll_pct"] = votes["boll_bw"] = 0.5

    _vote("stoch_k",  v_sk > 50  if v_sk  is not None else None)
    _vote("stoch_kd", v_sk > v_sd if (v_sk is not None and v_sd is not None) else None)
    _vote("williams_r", v_wr > -50 if v_wr is not None else None)
    _vote("cci",      v_cci > 0  if v_cci is not None else None)
    _vote("mfi",      v_mfi > 50 if v_mfi is not None else None)
    _vote("adx",      v_adx > 20 if v_adx is not None else None)
    _vote("psar",     price > v_psar if v_psar is not None else None)
    _vote("obv_trend", v_obv_l > v_obv_p if (v_obv_l is not None and v_obv_p is not None) else None)
    _vote("vwap",     price > v_vwap if v_vwap is not None else None)
    _vote("vol_trend", v_vol_c > v_vol_p if v_vol_p is not None else None)
    _vote("atr_trend", v_atr_c > v_atr_p if (v_atr_c is not None and v_atr_p is not None) else None)
    _vote("ema9_21",    v_ema9  > v_ema21  if (v_ema9  and v_ema21)  else None)
    _vote("ema21_50",   v_ema21 > v_ema50  if (v_ema21 and v_ema50)  else None)
    _vote("price_ema50",  price > v_ema50  if v_ema50  else None)
    _vote("price_ema200", price > v_ema200 if v_ema200 else None)

    # Weighted score 0–10
    total_w = sum(w for _, w in _INDICATOR_WEIGHTS)
    score = sum(votes.get(name, 0.5) * w for name, w in _INDICATOR_WEIGHTS)
    return score / total_w * 10


# ──────────────────────────────────────────────────────────────────────────────
# Exchange wrapper
# ──────────────────────────────────────────────────────────────────────────────

class Exchange:
    def __init__(self, cfg: BotConfig) -> None:
        cls = getattr(ccxt, cfg.exchange, None)
        if cls is None:
            raise ValueError(f"Unknown exchange: {cfg.exchange!r}. "
                             f"Supported: {', '.join(ccxt.exchanges)}")
        self._ex: ccxt.Exchange = cls({
            "apiKey": cfg.api_key,
            "secret": cfg.api_secret,
            "enableRateLimit": True,
        })
        self.symbol    = cfg.symbol
        self.timeframe = cfg.timeframe
        self.live      = cfg.live

    def fetch_candles(self, limit: int = 300) -> list[dict]:
        """Return a list of OHLCV dicts, newest last."""
        raw = self._ex.fetch_ohlcv(self.symbol, self.timeframe, limit=limit)
        return [
            {
                "ts":     r[0],
                "open":   float(r[1]),
                "high":   float(r[2]),
                "low":    float(r[3]),
                "close":  float(r[4]),
                "volume": float(r[5]),
            }
            for r in raw
        ]

    def fetch_balance(self) -> float:
        """Return USDT free balance."""
        bal = self._ex.fetch_balance()
        return float(bal.get("USDT", {}).get("free", 0) or 0)

    def place_market_buy(self, usdt_amount: float) -> dict:
        ticker = self._ex.fetch_ticker(self.symbol)
        price  = ticker["ask"]
        qty    = usdt_amount / price
        qty    = self._ex.amount_to_precision(self.symbol, qty)
        if self.live:
            return self._ex.create_market_buy_order(self.symbol, qty)
        return {"id": "paper", "filled": float(qty), "price": price, "side": "buy"}

    def place_market_sell(self, qty: float) -> dict:
        qty_str = self._ex.amount_to_precision(self.symbol, qty)
        if self.live:
            return self._ex.create_market_sell_order(self.symbol, qty_str)
        ticker = self._ex.fetch_ticker(self.symbol)
        return {"id": "paper", "filled": float(qty_str), "price": ticker["bid"], "side": "sell"}


# ──────────────────────────────────────────────────────────────────────────────
# Position tracker
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Position:
    symbol:    str
    qty:       float
    entry:     float
    stop_loss: float
    take_profit: float
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_open(self) -> bool:
        return self.qty > 0


# ──────────────────────────────────────────────────────────────────────────────
# Bot main loop
# ──────────────────────────────────────────────────────────────────────────────

class ScalperBot:
    def __init__(self, cfg: BotConfig) -> None:
        self.cfg      = cfg
        self.exchange = Exchange(cfg)
        self.position: Position | None = None
        self._run     = True
        mode = "LIVE" if cfg.live else "PAPER"
        log.info("ScalperBot starting  exchange=%s  symbol=%s  tf=%s  mode=%s",
                 cfg.exchange, cfg.symbol, cfg.timeframe, mode)
        if cfg.live:
            log.warning("LIVE MODE — real orders will be placed!")

    # ── internal helpers ──────────────────────────────────────────────────────

    def _current_price(self, candles: list[dict]) -> float:
        return candles[-1]["close"]

    def _check_exit_conditions(self, price: float) -> str | None:
        """Return 'TP', 'SL', or None."""
        if self.position is None:
            return None
        if price >= self.position.take_profit:
            return "TP"
        if price <= self.position.stop_loss:
            return "SL"
        return None

    def _open_position(self, price: float) -> None:
        balance = self.exchange.fetch_balance()
        usdt_size = balance * self.cfg.risk.max_position_pct
        if usdt_size < 1:
            log.warning("Insufficient balance for trade (%.4f USDT)", balance)
            return
        sl = price * (1 - self.cfg.risk.stop_loss_pct)
        tp = price * (1 + self.cfg.risk.take_profit_pct)
        order = self.exchange.place_market_buy(usdt_size)
        qty   = float(order.get("filled") or 0)
        if qty <= 0:
            log.error("Buy order returned zero fill — skipping")
            return
        self.position = Position(
            symbol=self.cfg.symbol, qty=qty,
            entry=price, stop_loss=sl, take_profit=tp,
        )
        mode = "LIVE" if self.cfg.live else "paper"
        log.info("[%s] BOUGHT %.6f @ %.4f  SL=%.4f  TP=%.4f",
                 mode, qty, price, sl, tp)

    def _close_position(self, price: float, reason: str) -> None:
        if self.position is None:
            return
        order = self.exchange.place_market_sell(self.position.qty)
        pnl_pct = (price - self.position.entry) / self.position.entry * 100
        mode = "LIVE" if self.cfg.live else "paper"
        log.info("[%s] SOLD %.6f @ %.4f  reason=%s  pnl=%.2f%%",
                 mode, self.position.qty, price, reason, pnl_pct)
        self.position = None

    # ── main loop ─────────────────────────────────────────────────────────────

    def step(self) -> None:
        """Run one iteration: fetch candles, score, act."""
        try:
            candles = self.exchange.fetch_candles(300)
        except Exception as exc:
            log.error("fetch_candles error: %s", exc)
            return

        price = self._current_price(candles)
        score = compute_panel_score(candles)
        if score is None:
            log.debug("Not enough candles for panel score yet")
            return

        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log.info("[%s]  %s  price=%.4f  score=%.2f  pos=%s",
                 ts, self.cfg.symbol, price,
                 score, f"{self.position.qty:.6f}" if self.position else "none")

        # ── exit logic ────────────────────────────────────────────────────────
        if self.position:
            reason = self._check_exit_conditions(price)
            if reason:
                self._close_position(price, reason)
                return
            # score-based exit
            if score <= self.cfg.signal.exit_threshold:
                self._close_position(price, "score_exit")
                return

        # ── entry logic ───────────────────────────────────────────────────────
        if not self.position and score >= self.cfg.signal.entry_threshold:
            self._open_position(price)

    def run(self) -> None:
        log.info("Bot running. Poll interval: %ds. Press Ctrl-C to stop.",
                 self.cfg.poll_interval)
        while self._run:
            self.step()
            try:
                time.sleep(self.cfg.poll_interval)
            except KeyboardInterrupt:
                log.info("Interrupted — shutting down.")
                break
        if self.position:
            log.warning("Bot stopped with open position (qty=%.6f). Close manually.",
                        self.position.qty)


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AscentTerminal Scalper Bot")
    p.add_argument("--config",   help="Path to JSON config file")
    p.add_argument("--exchange", default="binance",    help="Exchange id (ccxt)")
    p.add_argument("--symbol",   default="BTC/USDT",   help="Market symbol")
    p.add_argument("--timeframe",default="5m",          help="Candle timeframe")
    p.add_argument("--live",     action="store_true",   help="Enable live trading")
    p.add_argument("--log",      default="INFO",        help="Log level")
    p.add_argument("--api-key",  default="",            help="Exchange API key")
    p.add_argument("--api-secret", default="",          help="Exchange API secret")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log)

    if args.config:
        cfg = BotConfig.from_file(args.config)
    else:
        cfg = BotConfig(
            exchange=args.exchange,
            api_key=args.api_key or os.environ.get("API_KEY", ""),
            api_secret=args.api_secret or os.environ.get("API_SECRET", ""),
            symbol=args.symbol,
            timeframe=args.timeframe,
            live=args.live,
            log_level=args.log,
        )

    if cfg.live and not cfg.api_key:
        log.error("Live mode requires --api-key (or API_KEY env var).")
        sys.exit(1)

    bot = ScalperBot(cfg)
    bot.run()


if __name__ == "__main__":
    main()
