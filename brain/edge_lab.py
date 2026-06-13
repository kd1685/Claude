"""
edge_lab.py — OWNER'S RESEARCH TOOL (lives in brain/, never deployed:
the Docker build context intentionally excludes this folder).

What it does
────────────
Scans every MEXC USDT-M futures symbol and back-tests a configurable
set of simple indicators over the last N days of 1-h candles.  For
each symbol + indicator combo it computes:

  • Win-rate        (fraction of signals that were profitable)
  • Avg gain        (mean return on winning trades, %)
  • Avg loss        (mean return on losing trades, %)
  • Expectancy      (win_rate * avg_gain - loss_rate * avg_loss)
  • # signals       (sample size)

Results are written to edge_results.csv and also shown ranked by
expectancy in the terminal.

Usage
─────
    python brain/edge_lab.py                  # all symbols, default config
    python brain/edge_lab.py --symbols BTC ETH # specific symbols
    python brain/edge_lab.py --days 60 --tf 4h # 60 days of 4-h candles
    python brain/edge_lab.py --indicator ema_cross rsi_ob

Requires:  pip install pandas numpy requests tqdm
"""

from __future__ import annotations
import argparse, csv, os, sys, time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests
from tqdm import tqdm

# ── CONFIG ───────────────────────────────────────────────────────────────────

DEFAULT_DAYS      = 30
DEFAULT_TF        = '1h'
DEFAULT_HOLD_BARS = 4          # how many bars to hold after signal
MIN_SIGNALS       = 10         # skip combos with too few trades
OUTPUT_CSV        = os.path.join(os.path.dirname(__file__), 'edge_results.csv')

MEXC_BASE     = 'https://contract.mexc.com'
MEXC_KLINE    = '/api/v1/contract/kline'
MEXC_SYMBOLS  = '/api/v1/contract/detail'

TF_TO_MINUTES = {
    '1m': 1, '5m': 5, '15m': 15, '30m': 30,
    '1h': 60, '4h': 240, '1d': 1440,
}

# ── MEXC DATA ────────────────────────────────────────────────────────────────

def get_all_symbols() -> list[str]:
    r = requests.get(f'{MEXC_BASE}{MEXC_SYMBOLS}', timeout=15)
    r.raise_for_status()
    data = r.json().get('data', [])
    return [d['symbol'] for d in data if d.get('quoteCoin') == 'USDT' and d.get('state') == 0]


def fetch_klines(symbol: str, tf: str, days: int) -> pd.DataFrame | None:
    minutes  = TF_TO_MINUTES.get(tf, 60)
    limit    = min(2000, int(days * 24 * 60 / minutes))
    end_ts   = int(time.time())
    start_ts = end_ts - days * 86400

    try:
        r = requests.get(
            f'{MEXC_BASE}{MEXC_KLINE}',
            params={'symbol': symbol, 'interval': tf,
                    'start': start_ts, 'end': end_ts},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json().get('data', {})
    except Exception:
        return None

    # MEXC returns arrays keyed by field name
    try:
        df = pd.DataFrame({
            'ts':     raw['time'],
            'open':   raw['realOpen'],
            'high':   raw['high'],
            'low':    raw['low'],
            'close':  raw['realClose'],
            'volume': raw['vol'],
        })
    except (KeyError, TypeError):
        return None

    if df.empty:
        return None

    df = df.astype({'ts': int, 'open': float, 'high': float,
                    'low': float, 'close': float, 'volume': float})
    df['dt'] = pd.to_datetime(df['ts'], unit='s', utc=True)
    df.sort_values('ts', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ── INDICATORS ───────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def signals_ema_cross(df: pd.DataFrame,
                      fast: int = 9, slow: int = 21) -> pd.Series:
    """1 = long signal, -1 = short signal, 0 = nothing."""
    f = ema(df['close'], fast)
    s = ema(df['close'], slow)
    prev_f = f.shift(1)
    prev_s = s.shift(1)
    long_  = (prev_f <= prev_s) & (f > s)
    short_ = (prev_f >= prev_s) & (f < s)
    sig = pd.Series(0, index=df.index)
    sig[long_]  =  1
    sig[short_] = -1
    return sig


def signals_rsi_ob(df: pd.DataFrame,
                   period: int = 14, ob: int = 70, os_: int = 30) -> pd.Series:
    """Overbought/oversold mean-reversion."""
    r = rsi(df['close'], period)
    sig = pd.Series(0, index=df.index)
    sig[r < os_] =  1   # oversold → long
    sig[r > ob]  = -1   # overbought → short
    return sig


def signals_bb_bounce(df: pd.DataFrame,
                      period: int = 20, std: float = 2.0) -> pd.Series:
    """Bollinger-band bounce."""
    mid   = df['close'].rolling(period).mean()
    band  = df['close'].rolling(period).std() * std
    upper = mid + band
    lower = mid - band
    sig = pd.Series(0, index=df.index)
    sig[df['close'] < lower] =  1
    sig[df['close'] > upper] = -1
    return sig


def signals_vwap_dev(df: pd.DataFrame, threshold: float = 0.5) -> pd.Series:
    """Price deviation from VWAP (uses cumulative intraday approx)."""
    typical = (df['high'] + df['low'] + df['close']) / 3
    cumvol  = df['volume'].cumsum()
    cum_tp_vol = (typical * df['volume']).cumsum()
    vwap    = cum_tp_vol / cumvol
    dev     = (df['close'] - vwap) / vwap * 100
    sig = pd.Series(0, index=df.index)
    sig[dev < -threshold] =  1
    sig[dev >  threshold] = -1
    return sig


INDICATORS: dict[str, Any] = {
    'ema_cross':  signals_ema_cross,
    'rsi_ob':     signals_rsi_ob,
    'bb_bounce':  signals_bb_bounce,
    'vwap_dev':   signals_vwap_dev,
}


# ── BACK-TEST ────────────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, signals: pd.Series,
             hold_bars: int = DEFAULT_HOLD_BARS) -> dict | None:
    """Simulate fixed-hold-period exits and return stats."""
    results = []
    closes  = df['close'].values
    n       = len(closes)

    for i in signals[signals != 0].index:
        entry_idx = i + 1          # fill at next open (approx close)
        exit_idx  = entry_idx + hold_bars
        if exit_idx >= n:
            continue
        entry = closes[entry_idx]
        exit_ = closes[exit_idx]
        if entry == 0:
            continue
        raw_ret = (exit_ - entry) / entry * 100
        ret = raw_ret if signals[i] == 1 else -raw_ret
        results.append(ret)

    if len(results) < MIN_SIGNALS:
        return None

    arr       = np.array(results)
    wins      = arr[arr > 0]
    losses    = arr[arr <= 0]
    win_rate  = len(wins) / len(arr)
    avg_gain  = float(wins.mean())  if len(wins)   else 0.0
    avg_loss  = float(losses.mean()) if len(losses) else 0.0
    expectancy= win_rate * avg_gain + (1 - win_rate) * avg_loss

    return {
        'n':          len(arr),
        'win_rate':   round(win_rate, 4),
        'avg_gain':   round(avg_gain,  4),
        'avg_loss':   round(avg_loss,  4),
        'expectancy': round(expectancy, 4),
    }


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Ascent Edge Lab')
    ap.add_argument('--symbols',    nargs='*', help='Symbols to test (default: all USDT-M)')
    ap.add_argument('--days',       type=int,   default=DEFAULT_DAYS)
    ap.add_argument('--tf',         default=DEFAULT_TF,
                    choices=list(TF_TO_MINUTES))
    ap.add_argument('--hold',       type=int,   default=DEFAULT_HOLD_BARS)
    ap.add_argument('--indicator',  nargs='*',  choices=list(INDICATORS),
                    default=list(INDICATORS))
    ap.add_argument('--top',        type=int,   default=20,
                    help='Show top N results')
    args = ap.parse_args()

    print('\n  Ascent Edge Lab')
    print(f'  Timeframe: {args.tf}  Days: {args.days}  Hold: {args.hold} bars')
    print(f'  Indicators: {", ".join(args.indicator)}\n')

    # Resolve symbols
    if args.symbols:
        symbols = [s.upper() + ('_USDT' if not s.endswith('_USDT') else '')
                   for s in args.symbols]
    else:
        print('  Fetching symbol list from MEXC ...')
        symbols = get_all_symbols()
        print(f'  {len(symbols)} USDT-M symbols found\n')

    rows: list[dict] = []

    for sym in tqdm(symbols, unit='sym', desc='Scanning'):
        df = fetch_klines(sym, args.tf, args.days)
        if df is None or len(df) < 50:
            continue
        for ind_name in args.indicator:
            fn  = INDICATORS[ind_name]
            sig = fn(df)
            if sig.abs().sum() == 0:
                continue
            stats = backtest(df, sig, hold_bars=args.hold)
            if stats is None:
                continue
            rows.append({'symbol': sym, 'indicator': ind_name, **stats})

    if not rows:
        print('No results.  Try --days 60 or fewer symbols.')
        return

    result_df = pd.DataFrame(rows).sort_values('expectancy', ascending=False)

    # Save CSV
    result_df.to_csv(OUTPUT_CSV, index=False)
    print(f'\n  Results saved → {OUTPUT_CSV}')

    # Print top N
    print(f'\n  TOP {args.top} by expectancy:\n')
    top = result_df.head(args.top)
    col_w = {'symbol': 14, 'indicator': 12, 'n': 6, 'win_rate': 10,
              'avg_gain': 10, 'avg_loss': 10, 'expectancy': 12}
    header = ''.join(c.ljust(col_w[c]) for c in col_w)
    print('  ' + header)
    print('  ' + '-' * len(header))
    for _, row in top.iterrows():
        line = (
            str(row['symbol']).ljust(col_w['symbol']) +
            str(row['indicator']).ljust(col_w['indicator']) +
            str(row['n']).ljust(col_w['n']) +
            f"{row['win_rate']:.1%}".ljust(col_w['win_rate']) +
            f"{row['avg_gain']:.2f}%".ljust(col_w['avg_gain']) +
            f"{row['avg_loss']:.2f}%".ljust(col_w['avg_loss']) +
            f"{row['expectancy']:.2f}%".ljust(col_w['expectancy'])
        )
        print('  ' + line)
    print()


if __name__ == '__main__':
    main()
