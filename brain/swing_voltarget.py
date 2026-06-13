"""
swing_voltarget.py — the deployable version: trend filter + VOLATILITY TARGETING
across a diversified PORTFOLIO.

Instead of going all-in (which gave 60% drawdowns), each coin is sized so its
risk contribution targets a set volatility — calm coins get more size, wild coins
less — and the coins are combined into one portfolio (diversification cuts
drawdown further). The result is a CONTROLLED-drawdown equity curve, which is the
only kind you can safely leverage.

  python swing_voltarget.py --target_vol 0.20 --ema 30
  python swing_voltarget.py --target_vol 0.40 --ema 30 --max_lev 3   # more aggressive

--target_vol is the dial: higher = more return AND more drawdown. Find the
setting whose drawdown you can actually live with.
Needs engine.py + swing_backtest.py alongside.
"""

import argparse
import math
from swing_backtest import fetch, ema_aligned, maxdd, FEE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="Day1")
    ap.add_argument("--candles", type=int, default=1000)
    ap.add_argument("--symbols", default="BTC_USDT,ETH_USDT,SOL_USDT,BNB_USDT,XRP_USDT")
    ap.add_argument("--ema", type=int, default=30)
    ap.add_argument("--target_vol", type=float, default=0.20)   # annualised, e.g. 0.20 = 20%
    ap.add_argument("--max_lev", type=float, default=3.0)       # per-coin size cap
    ap.add_argument("--vol_win", type=int, default=20)
    a = ap.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]

    data = {}
    for s in syms:
        c = fetch(s, a.interval, a.candles)
        if len(c) > a.ema + a.vol_win + 30:
            data[s] = c
            print(f"  {s}: {len(c)} candles")
    if not data:
        print("No data."); return
    minlen = min(len(c) for c in data.values())
    coins = list(data.keys())
    N = len(coins)

    # align to common length + precompute per coin
    rets, ema, vol = {}, {}, {}
    for s in coins:
        c = data[s][-minlen:]
        data[s] = c
        rets[s] = [0.0] + [(c[t]-c[t-1])/c[t-1] for t in range(1, minlen)]
        ema[s] = ema_aligned(c, a.ema)
        v = [None]*minlen
        for t in range(minlen):
            w = rets[s][max(0, t-a.vol_win):t]
            if len(w) >= 5:
                m = sum(w)/len(w); var = sum((x-m)**2 for x in w)/len(w)
                v[t] = math.sqrt(var)*math.sqrt(365)
            else:
                v[t] = None
        vol[s] = v

    start = a.ema + a.vol_win + 1
    eq = 1.0; curve = [1.0]; sizes = {s: 0.0 for s in coins}
    bh = 1.0; bh_curve = [1.0]
    for t in range(start, minlen):
        # earn yesterday's positions
        port = sum((1.0/N) * sizes[s] * rets[s][t] for s in coins)
        eq *= (1 + port); curve.append(eq)
        bh *= (1 + sum((1.0/N) * rets[s][t] for s in coins)); bh_curve.append(bh)
        # rebalance for next day
        for s in coins:
            up = data[s][t] > (ema[s][t] or 1e18)
            v = vol[s][t]
            desired = min(a.max_lev, a.target_vol / v) if (up and v and v > 0) else 0.0
            if abs(desired - sizes[s]) > 0.05:
                eq *= (1 - FEE * (1.0/N) * abs(desired - sizes[s]))
                sizes[s] = desired

    years = minlen/365 if a.interval == "Day1" else minlen/(6*365)
    cagr = ((eq)**(1/years) - 1)*100 if years > 0 and eq > 0 else 0
    bh_cagr = ((bh)**(1/years) - 1)*100 if years > 0 and bh > 0 else 0
    print(f"\n──── VOL-TARGETED TREND PORTFOLIO ({N} coins) ────")
    print(f"  EMA{a.ema} trend filter | target vol {a.target_vol*100:.0f}% | "
          f"max size {a.max_lev}x | ~{years:.1f}y")
    print(f"  Strategy : {(eq-1)*100:>+9.1f}%   CAGR {cagr:>+6.1f}%   maxDD {maxdd(curve):>5.1f}%")
    print(f"  Buy&hold : {(bh-1)*100:>+9.1f}%   CAGR {bh_cagr:>+6.1f}%   maxDD {maxdd(bh_curve):>5.1f}%")
    print("─"*50)
    print("  Goal: a drawdown you can live with (~15-25%) at a CAGR that beats")
    print("  buy&hold risk-adjusted. Raise --target_vol for more return + more DD.")


if __name__ == "__main__":
    main()
