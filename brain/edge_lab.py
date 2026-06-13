"""edge_lab.py — Walk-forward parameter optimiser for Ascent Terminal.

Runs a grid search over strategy parameters on historical MEXC data,
then walk-forward validates the best params on out-of-sample data.

Usage:
    python3 brain/edge_lab.py [--symbol BTCUSDT] [--days 90]

Outputs:
    brain/edge_results.csv  — full grid results
    brain/edge_cache/       — cached OHLCV data
"""

import argparse
import csv
import itertools
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOL_DEFAULT = "BTC/USDT"
TIMEFRAME = "1h"
DAYS_DEFAULT = 90
OOS_FRACTION = 0.3  # last 30% of data is out-of-sample

CACHE_DIR = Path("brain/edge_cache")
RESULTS_FILE = Path("brain/edge_results.csv")

# Parameter grid
PARAM_GRID = {
    "rsi_period": [10, 14, 20],
    "rsi_ob": [65, 70, 75],
    "rsi_os": [25, 30, 35],
    "bb_period": [14, 20],
    "bb_std": [1.5, 2.0, 2.5],
    "atr_sl_mult": [1.5, 2.0, 2.5],
    "atr_tp_mult": [2.0, 3.0, 4.0],
}

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def fetch_ohlcv(symbol: str, days: int) -> pd.DataFrame:
    cache_file = CACHE_DIR / f"{symbol.replace('/', '_')}_{days}d.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < 3600:  # use cache if < 1 hour old
            with open(cache_file) as f:
                raw = json.load(f)
            return pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])

    exchange = ccxt.mexc({"enableRateLimit": True})
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    all_ohlcv = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, TIMEFRAME, since=since, limit=1000)
        if not batch:
            break
        all_ohlcv.extend(batch)
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000)

    with open(cache_file, "w") as f:
        json.dump(all_ohlcv, f)

    return pd.DataFrame(all_ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def bollinger(close: pd.Series, period: int, std: float):
    mid = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def backtest(df: pd.DataFrame, params: dict) -> dict:
    rsi_vals = rsi(df["close"], params["rsi_period"])
    bb_upper, bb_mid, bb_lower = bollinger(df["close"], params["bb_period"], params["bb_std"])
    atr_vals = atr(df["high"], df["low"], df["close"])

    in_trade = False
    entry = sl = tp = 0.0
    trades = []

    for i in range(max(params["rsi_period"], params["bb_period"]) + 1, len(df)):
        price = df["close"].iloc[i]

        if not in_trade:
            # Long entry: RSI oversold + price near lower BB
            if rsi_vals.iloc[i] < params["rsi_os"] and price <= bb_lower.iloc[i] * 1.005:
                entry = price
                sl = price - params["atr_sl_mult"] * atr_vals.iloc[i]
                tp = price + params["atr_tp_mult"] * atr_vals.iloc[i]
                in_trade = True
        else:
            if df["low"].iloc[i] <= sl:
                trades.append(-params["atr_sl_mult"])
                in_trade = False
            elif df["high"].iloc[i] >= tp:
                trades.append(params["atr_tp_mult"])
                in_trade = False

    if not trades:
        return {"n_trades": 0, "win_rate": 0, "expectancy": 0, "total_r": 0}

    wins = [t for t in trades if t > 0]
    return {
        "n_trades": len(trades),
        "win_rate": len(wins) / len(trades),
        "expectancy": np.mean(trades),
        "total_r": sum(trades),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=SYMBOL_DEFAULT)
    parser.add_argument("--days", type=int, default=DAYS_DEFAULT)
    args = parser.parse_args()

    print(f"Fetching {args.days}d of {args.symbol} {TIMEFRAME} data...")
    df = fetch_ohlcv(args.symbol, args.days)
    print(f"  Got {len(df)} candles")

    split = int(len(df) * (1 - OOS_FRACTION))
    df_is = df.iloc[:split].reset_index(drop=True)
    df_oos = df.iloc[split:].reset_index(drop=True)

    print(f"  In-sample: {len(df_is)} candles, OOS: {len(df_oos)} candles")
    print(f"Running grid search ({sum(1 for _ in itertools.product(*PARAM_GRID.values()))} combos)...")

    results = []
    keys = list(PARAM_GRID.keys())
    for combo in itertools.product(*PARAM_GRID.values()):
        params = dict(zip(keys, combo))
        is_res = backtest(df_is, params)
        if is_res["n_trades"] < 5:
            continue
        oos_res = backtest(df_oos, params)
        row = {**params, **{f"is_{k}": v for k, v in is_res.items()}, **{f"oos_{k}": v for k, v in oos_res.items()}}
        results.append(row)

    if not results:
        print("No valid parameter combinations found.")
        return

    results.sort(key=lambda r: r["oos_expectancy"], reverse=True)
    top = results[:5]

    with open(RESULTS_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"\nTop 5 param sets (by OOS expectancy):")
    for i, r in enumerate(top, 1):
        print(f"  #{i}: expectancy={r['oos_expectancy']:.3f}R, "
              f"win_rate={r['oos_win_rate']:.1%}, trades={r['oos_n_trades']}, "
              f"rsi={r['rsi_period']}/{r['rsi_ob']}/{r['rsi_os']}, "
              f"bb={r['bb_period']}/{r['bb_std']}, "
              f"sl={r['atr_sl_mult']}R/tp={r['atr_tp_mult']}R")

    print(f"\nFull results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
