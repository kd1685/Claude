"""swing_backtest.py — Simple swing strategy backtest.

Long when RSI(14) crosses above 40 from below and price is above SMA(50).
Exit when RSI > 60 or price closes below SMA(50).
"""

import pandas as pd
import numpy as np
import ccxt
import time
from datetime import datetime, timedelta, timezone


def fetch(symbol="BTC/USDT", days=365, tf="1d"):
    exchange = ccxt.mexc({"enableRateLimit": True})
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    rows = []
    while True:
        batch = exchange.fetch_ohlcv(symbol, tf, since=since, limit=500)
        if not batch:
            break
        rows.extend(batch)
        since = batch[-1][0] + 1
        if len(batch) < 500:
            break
        time.sleep(0.2)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def run(df):
    df = df.copy()
    df["rsi"] = rsi(df["close"])
    df["sma50"] = df["close"].rolling(50).mean()

    position = None
    trades = []

    for i in range(51, len(df)):
        r = df["rsi"].iloc[i]
        r_prev = df["rsi"].iloc[i - 1]
        price = df["close"].iloc[i]
        sma = df["sma50"].iloc[i]

        if position is None:
            if r_prev < 40 <= r and price > sma:
                position = {"entry": price, "dt": df["dt"].iloc[i]}
        else:
            if r > 60 or price < sma:
                pnl = (price - position["entry"]) / position["entry"]
                trades.append({"entry_dt": position["dt"], "exit_dt": df["dt"].iloc[i],
                                "entry": position["entry"], "exit": price, "pnl": pnl})
                position = None

    if not trades:
        print("No trades.")
        return

    tdf = pd.DataFrame(trades)
    wins = tdf[tdf["pnl"] > 0]
    print(f"Trades: {len(tdf)}  Wins: {len(wins)}  Win rate: {len(wins)/len(tdf):.1%}")
    print(f"Avg win: {wins['pnl'].mean():.2%}  Avg loss: {tdf[tdf['pnl']<=0]['pnl'].mean():.2%}")
    print(f"Total return: {tdf['pnl'].sum():.2%}")
    print(tdf.tail(10).to_string(index=False))


if __name__ == "__main__":
    print("Fetching BTC/USDT daily data (365 days)...")
    df = fetch()
    run(df)
