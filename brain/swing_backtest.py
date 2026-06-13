#!/usr/bin/env python3
"""
Ascent Terminal — Quick Swing Backtest (Sharpe screener)
=========================================================
Runs a fast single-pass backtest on MEXC OHLCV data and
prints a Sharpe / PnL summary.  No walk-forward, no sweep —
just a quick sanity-check before committing to a full edge-lab run.

Usage:
  python swing_backtest.py                        # BTC/USDT 1d
  python swing_backtest.py --symbol ETH/USDT --timeframe 4h
  python swing_backtest.py --bars 500

Requires: ccxt, numpy, python-dotenv
"""

import argparse
import os
import math
import logging
from typing import List

import ccxt
import numpy as np
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("swing_bt")

# ── CLI ───────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Quick swing backtest")
parser.add_argument("--symbol",    default="BTC/USDT")
parser.add_argument("--timeframe", default="1d")
parser.add_argument("--bars",      type=int, default=365)
parser.add_argument("--ema-fast",  type=int, default=9)
parser.add_argument("--ema-slow",  type=int, default=21)
parser.add_argument("--rsi",       type=int, default=14)
parser.add_argument("--atr",       type=int, default=14)
parser.add_argument("--atr-mult",  type=float, default=2.0)
parser.add_argument("--risk",      type=float, default=0.01)
args = parser.parse_args()


# ── Indicators ────────────────────────────────────────────────────────────────
def ema(arr, n):
    k = 2.0 / (n + 1)
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out


def rsi(closes, n):
    d = np.diff(closes.astype(float))
    g = np.where(d > 0, d, 0.); l = np.where(d < 0, -d, 0.)
    ag = np.full(len(closes), np.nan); al = np.full(len(closes), np.nan)
    ag[n] = g[:n].mean(); al[n] = l[:n].mean()
    for i in range(n+1, len(closes)):
        ag[i] = (ag[i-1]*(n-1) + g[i-1]) / n
        al[i] = (al[i-1]*(n-1) + l[i-1]) / n
    rs = np.where(al == 0, 100., ag / al)
    return np.where(np.isnan(ag), np.nan, 100. - 100. / (1 + rs))


def atr(highs, lows, closes, n):
    h,l,c = highs.astype(float), lows.astype(float), closes.astype(float)
    tr = np.maximum(h[1:]-l[1:],
         np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    out = np.full(len(c), np.nan)
    out[n] = tr[:n].mean()
    for i in range(n+1, len(c)):
        out[i] = (out[i-1]*(n-1) + tr[i-1]) / n
    return out


# ── Backtest ──────────────────────────────────────────────────────────────────
def run_backtest(ohlcv: List) -> None:
    arr    = np.array(ohlcv, dtype=float)
    highs  = arr[:, 2]; lows = arr[:, 3]; closes = arr[:, 4]

    fast_v = ema(closes, args.ema_fast)
    slow_v = ema(closes, args.ema_slow)
    rsi_v  = rsi(closes, args.rsi)
    atr_v  = atr(highs, lows, closes, args.atr)

    equity   = 10_000.0
    pos      = None
    trade_pnls: List[float] = []

    for i in range(1, len(closes)):
        if any(np.isnan(x) for x in [fast_v[i], slow_v[i], rsi_v[i], atr_v[i]]):
            continue
        p         = closes[i]
        crossup   = fast_v[i-1] <= slow_v[i-1] and fast_v[i] > slow_v[i]
        crossdown = fast_v[i-1] >= slow_v[i-1] and fast_v[i] < slow_v[i]

        if pos:
            hit  = (pos["s"]=="long" and p<=pos["stop"]) or \
                   (pos["s"]=="short" and p>=pos["stop"])
            xsig = (pos["s"]=="long" and crossdown) or \
                   (pos["s"]=="short" and crossup)
            if hit or xsig:
                pnl = (p - pos["e"]) * pos["q"] if pos["s"]=="long" \
                      else (pos["e"] - p) * pos["q"]
                pnl -= (pos["e"] + p) * pos["q"] * 0.001
                equity += pnl; trade_pnls.append(pnl); pos = None

        if not pos:
            sd  = atr_v[i] * args.atr_mult
            qty = (equity * args.risk) / sd if sd > 0 else 0
            if qty > 0:
                if crossup and rsi_v[i] < 70:
                    pos = {"s":"long",  "e":p, "q":qty, "stop":p-sd}
                elif crossdown and rsi_v[i] > 30:
                    pos = {"s":"short", "e":p, "q":qty, "stop":p+sd}

    if not trade_pnls:
        print("No trades executed.")
        return

    arr2    = np.array(trade_pnls)
    sharpe  = (arr2.mean() / arr2.std() * math.sqrt(252)) if arr2.std() > 0 else 0
    cum     = np.cumsum(arr2)
    peak    = np.maximum.accumulate(cum)
    dd      = ((peak - cum) / (np.abs(peak) + 1e-9)).max()

    print(f"\n{'='*50}")
    print(f"  Symbol    : {args.symbol}  {args.timeframe}")
    print(f"  Bars      : {len(ohlcv)}")
    print(f"  Trades    : {len(trade_pnls)}")
    print(f"  Total PnL : {arr2.sum():+.2f} USDT")
    print(f"  Sharpe    : {sharpe:.3f}")
    print(f"  Max DD    : {dd:.1%}")
    print(f"  Win rate  : {(arr2>0).mean():.1%}")
    print(f"{'='*50}\n")


# ── Fetch + run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    exchange = ccxt.mexc({
        "apiKey": os.getenv("MEXC_API_KEY", ""),
        "secret": os.getenv("MEXC_SECRET_KEY", ""),
        "enableRateLimit": True,
    })
    exchange.load_markets()
    log.info("fetching", symbol=args.symbol, bars=args.bars)
    ohlcv = exchange.fetch_ohlcv(args.symbol, args.timeframe, limit=args.bars)
    log.info("fetched", n=len(ohlcv))
    run_backtest(ohlcv)
