"""
swing_backtest.py — test a daily TREND-FOLLOWING strategy vs buy-and-hold.

Signal: time-series momentum (12-month rolling return).
  • Long when last month's return > 0  (price above its value 1 month ago)
  • Flat otherwise

Usage:
    python brain/swing_backtest.py --symbol BTC_USDT --days 365
    python brain/swing_backtest.py --symbol ETH_USDT --days 730 --hold 5

Requires: pip install pandas numpy requests
"""

from __future__ import annotations
import argparse, sys, time
from datetime import datetime

import numpy as np
import pandas as pd
import requests

MEXC_BASE = 'https://contract.mexc.com'


def fetch_daily(symbol: str, days: int) -> pd.DataFrame:
    end   = int(time.time())
    start = end - days * 86400
    r = requests.get(
        f'{MEXC_BASE}/api/v1/contract/kline',
        params={'symbol': symbol, 'interval': 'Day1',
                'start': start, 'end': end},
        timeout=20,
    )
    r.raise_for_status()
    raw = r.json()['data']
    df = pd.DataFrame({
        'ts':    raw['time'],
        'close': raw['realClose'],
    }).astype({'ts': int, 'close': float})
    df['dt'] = pd.to_datetime(df['ts'], unit='s', utc=True)
    return df.sort_values('ts').reset_index(drop=True)


def run_backtest(df: pd.DataFrame, lookback: int = 20,
                hold: int = 1) -> pd.DataFrame:
    """
    lookback : bars to look back for momentum signal
    hold     : bars to hold after signal fires
    """
    df = df.copy()
    df['ret_1d']   = df['close'].pct_change()
    df['momentum'] = df['close'].pct_change(lookback)
    df['signal']   = np.where(df['momentum'] > 0, 1, 0)  # 1=long, 0=flat
    df['strat_ret']= df['signal'].shift(hold) * df['ret_1d']
    df['bh_ret']   = df['ret_1d']
    df['strat_eq'] = (1 + df['strat_ret'].fillna(0)).cumprod()
    df['bh_eq']    = (1 + df['bh_ret'].fillna(0)).cumprod()
    return df


def print_stats(df: pd.DataFrame, symbol: str):
    strat = df['strat_ret'].dropna()
    bh    = df['bh_ret'].dropna()

    def sharpe(r):
        return (r.mean() / r.std() * np.sqrt(252)) if r.std() else 0.0

    def max_dd(eq):
        roll_max = eq.cummax()
        dd = (eq - roll_max) / roll_max
        return dd.min()

    print(f'\n  ── Swing Backtest: {symbol} ──')
    print(f'  Bars          : {len(df)}')
    print(f'  Period        : {df["dt"].iloc[0].date()} → {df["dt"].iloc[-1].date()}')
    print()
    print(f'  {"":30s} {"Strategy":>12} {"Buy & Hold":>12}')
    print(f'  {"-"*56}')
    print(f'  {"Total return":30s} {df["strat_eq"].iloc[-1]-1:>11.1%} {df["bh_eq"].iloc[-1]-1:>11.1%}')
    print(f'  {"Sharpe ratio":30s} {sharpe(strat):>12.2f} {sharpe(bh):>12.2f}')
    print(f'  {"Max drawdown":30s} {max_dd(df["strat_eq"]):>11.1%} {max_dd(df["bh_eq"]):>11.1%}')
    print(f'  {"Win rate":30s} {(strat > 0).mean():>11.1%} {(bh > 0).mean():>11.1%}')
    print(f'  {"Days in market":30s} {df["signal"].mean():>11.1%} {1.0:>11.1%}')
    print()


def main():
    ap = argparse.ArgumentParser(description='Ascent Swing Backtest')
    ap.add_argument('--symbol',   default='BTC_USDT')
    ap.add_argument('--days',     type=int, default=365)
    ap.add_argument('--lookback', type=int, default=20,
                    help='Momentum lookback in bars')
    ap.add_argument('--hold',     type=int, default=1,
                    help='Bars to hold after signal')
    args = ap.parse_args()

    print(f'  Fetching {args.days} days of {args.symbol} daily candles ...')
    df = fetch_daily(args.symbol, args.days)
    print(f'  {len(df)} bars fetched.')

    df = run_backtest(df, lookback=args.lookback, hold=args.hold)
    print_stats(df, args.symbol)


if __name__ == '__main__':
    main()
