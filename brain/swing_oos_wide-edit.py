import argparse, warnings
import numpy as np
import pandas as pd
import requests, time

warnings.filterwarnings("ignore")

# ── CLI ────────────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument("--interval", default="1d")
ap.add_argument("--candles",  type=int, default=1000)
ap.add_argument("--ema",      type=int, default=30)
args = ap.parse_args()

# ── WIDER UNIVERSE (winners + mid-tier + known losers/delisted survivors) ───
SYMBOLS = [
    # Your original 5 winners
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    # Large caps
    "ADAUSDT","DOTUSDT","AVAXUSDT","MATICUSDT","LTCUSDT",
    # Mid-tier / more volatile
    "LINKUSDT","ATOMUSDT","UNIUSDT","AAVEUSDT","FILUSDT",
    "SANDUSDT","MANAUSDT","GALAUSDT","APEUSDT","FTMUSDT",
    # Known weak/choppy coins (high noise, lower trend)
    "DOGEUSDT","SHIBUSDT","TRXUSDT","XMRUSDT","EOSUSDT",
    "DASHUSDT","ZECUSDT","ETCUSDT","BCHUSDT","NEOUSDT",
]

def fetch(symbol, interval, limit):
    url = "https://api.binance.com/api/v3/klines"
    r = requests.get(url, params={"symbol":symbol,"interval":interval,"limit":limit}, timeout=10)
    if r.status_code != 200:
        return None
    d = pd.DataFrame(r.json(), columns=[
        "ts","open","high","low","close","vol",
        "cts","qvol","ntrades","tbbvol","tbqvol","ignore"])
    d["close"] = d["close"].astype(float)
    d["ts"] = pd.to_datetime(d["ts"], unit="ms")
    return d.set_index("ts")["close"]

def backtest_oos(prices, ema_period):
    """Split 50/50, run EMA trend strategy on each half."""
    results = {}
    for label, s in [("IS", prices.iloc[:len(prices)//2]),
                     ("OOS", prices.iloc[len(prices)//2:])]:
        ema = s.ewm(span=ema_period, adjust=False).mean()
        signal = (s > ema).astype(int).shift(1).fillna(0)
        rets = s.pct_change().fillna(0)
        strat = (signal * rets)
        bnh   = rets

        def metrics(r):
            cum = (1 + r).cumprod()
            total = cum.iloc[-1] - 1
            roll_max = cum.cummax()
            dd = (cum - roll_max) / roll_max
            return total * 100, dd.min() * 100

        results[label] = {
            "strat": metrics(strat),
            "bnh":   metrics(bnh),
        }
    return results

# ── RUN ────────────────────────────────────────────────────────────────────────────
print(f"\nWIDER UNIVERSE ROBUSTNESS TEST  (EMA{args.ema}, {args.candles} candles, {args.interval})")
print(f"{'Symbol':<12} {'IS_strat':>9} {'IS_sDD':>7} {'IS_bnh':>7} {'IS_bDD':>7} | "
      f"{'OOS_strat':>9} {'OOS_sDD':>7} {'OOS_bnh':>7} {'OOS_bDD':>7}  EDGE?")
print("-"*100)

passed = failed = no_data = 0

for sym in SYMBOLS:
    try:
        prices = fetch(sym, args.interval, args.candles)
        time.sleep(0.15)  # rate limit
        if prices is None or len(prices) < args.candles * 0.8:
            print(f"  {sym:<10}  NO DATA / DELISTED")
            no_data += 1
            continue

        r = backtest_oos(prices, args.ema)
        is_s,  is_sdd  = r["IS"]["strat"]
        is_b,  is_bdd  = r["IS"]["bnh"]
        oos_s, oos_sdd = r["OOS"]["strat"]
        oos_b, oos_bdd = r["OOS"]["bnh"]

        # Edge criteria: OOS drawdown materially better than B&H
        edge = "EDGE" if (oos_sdd > oos_bdd + 5) else "no edge"
        if "EDGE" in edge: passed += 1
        else: failed += 1

        print(f"  {sym:<10}  {is_s:>+7.0f}%  {is_sdd:>+6.0f}%  {is_b:>+6.0f}%  {is_bdd:>+6.0f}%  | "
              f"  {oos_s:>+7.0f}%  {oos_sdd:>+6.0f}%  {oos_b:>+6.0f}%  {oos_bdd:>+6.0f}%   {edge}")
    except Exception as e:
        print(f"  {sym:<10}  ERROR: {e}")
        no_data += 1

total = passed + failed
print("-"*100)
print(f"\nRESULT: {passed}/{total} coins showed drawdown edge OOS  ({passed/total*100:.0f}% hit rate)")
print(f"  (+ {no_data} symbols with no/insufficient data)")
print()
if passed/total >= 0.60:
    print("ROBUST -- edge holds across a wide, diverse universe. Survivor bias is NOT the explanation.")
elif passed/total >= 0.40:
    print("PARTIAL -- edge works on some coins. Check which types fail (choppy vs trending).")
else:
    print("FRAGILE -- edge is likely survivor-fit. Do NOT deploy.")
