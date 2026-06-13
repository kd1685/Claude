"""
swing_backtest.py — test a daily TREND-FOLLOWING strategy vs buy-and-hold.

Signal: time-series momentum — be LONG while price is above its EMA (uptrend),
flat (or short) while below. Holds for days/weeks. At daily horizons fees are
trivial. The real test isn't out-returning a bull market — it's whether trend-
following gives a BETTER RISK-ADJUSTED result (much lower drawdown for similar
return) and survives bear periods.

  pip install requests
  python swing_backtest.py --interval Day1 --candles 1000 --ema 20
  python swing_backtest.py --ema 30 --short          # also short downtrends
  python swing_backtest.py --ema 20 --leverage 2

Needs engine.py alongside (uses its fetch is not imported — self-contained fetch).
"""

import argparse
import time
import requests

MEXC = "https://contract.mexc.com"
FEE = 0.0010   # 0.10% round trip, charged on each position change


def fetch(symbol, interval, want):
    out = {}
    sec = {"Day1": 86400, "Hour4": 14400}.get(interval, 86400)
    end = int(time.time()); span = sec * 1000; s = end - want*sec - span
    while s < end and len(out) < want + 50:
        e = min(s + span, end)
        try:
            d = requests.get(f"{MEXC}/api/v1/contract/kline/{symbol}",
                             params={"interval": interval, "start": s, "end": e},
                             timeout=15).json().get("data", {})
        except Exception:
            d = {}
        t = d.get("time", [])
        for i in range(len(t)):
            try:
                out[float(t[i])] = float(d["close"][i])
            except Exception:
                pass
        s = e; time.sleep(0.1)
    return [out[k] for k in sorted(out)]


def ema_aligned(closes, period):
    k = 2/(period+1); out = [None]*len(closes)
    if len(closes) < period:
        return out
    sma = sum(closes[:period])/period; out[period-1] = sma; prev = sma
    for i in range(period, len(closes)):
        prev = closes[i]*k + prev*(1-k); out[i] = prev
    return out


def maxdd(curve):
    peak = curve[0]; dd = 0.0
    for v in curve:
        peak = max(peak, v); dd = max(dd, (peak-v)/peak)
    return dd*100


def run(closes, ema_p, allow_short, lev):
    ema = ema_aligned(closes, ema_p)
    eq = 1.0; pos = 0; trades = 0; in_days = 0
    curve = [1.0]
    bh = [1.0]
    for i in range(ema_p, len(closes)):
        ret = (closes[i]-closes[i-1])/closes[i-1]
        eq *= (1 + pos * lev * ret)            # yesterday's position earns today's return
        desired = 1 if closes[i] > ema[i] else (-1 if allow_short else 0)
        if desired != pos:
            eq *= (1 - FEE * lev); trades += 1
            pos = desired
        if pos != 0:
            in_days += 1
        curve.append(eq)
        bh.append(closes[i]/closes[ema_p])
    return {"ret": (eq-1)*100, "dd": maxdd(curve), "trades": trades,
            "exposure": in_days/(len(closes)-ema_p)*100 if len(closes) > ema_p else 0,
            "bh_ret": (bh[-1]-1)*100, "bh_dd": maxdd(bh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="Day1")
    ap.add_argument("--candles", type=int, default=1000)
    ap.add_argument("--symbols", default="BTC_USDT,ETH_USDT,SOL_USDT,BNB_USDT,XRP_USDT")
    ap.add_argument("--ema", type=int, default=20)
    ap.add_argument("--short", action="store_true")
    ap.add_argument("--leverage", type=float, default=1.0)
    a = ap.parse_args()

    print(f"\nTrend filter: price vs EMA{a.ema} on {a.interval} | "
          f"short={a.short} | leverage={a.leverage}x\n")
    print(f"{'symbol':<10} {'STRAT ret%':>10} {'STRAT maxDD':>12} {'exp%':>6} {'trades':>7} "
          f"| {'BUY&HOLD ret%':>13} {'B&H maxDD':>10}")
    print("-"*84)
    agg = []
    for s in [x.strip() for x in a.symbols.split(",") if x.strip()]:
        c = fetch(s, a.interval, a.candles)
        if len(c) < a.ema + 30:
            print(f"{s:<10} only {len(c)} candles — skipped"); continue
        r = run(c, a.ema, a.short, a.leverage)
        agg.append(r)
        print(f"{s:<10} {r['ret']:>+10.1f} {r['dd']:>11.1f}% {r['exposure']:>5.0f}% "
              f"{r['trades']:>7} | {r['bh_ret']:>+13.1f} {r['bh_dd']:>9.1f}%")
    if agg:
        sret = sum(r['ret'] for r in agg)/len(agg)
        sdd = sum(r['dd'] for r in agg)/len(agg)
        bret = sum(r['bh_ret'] for r in agg)/len(agg)
        bdd = sum(r['bh_dd'] for r in agg)/len(agg)
        print("-"*84)
        print(f"{'AVERAGE':<10} {sret:>+10.1f} {sdd:>11.1f}% {'':>6} {'':>7} "
              f"| {bret:>+13.1f} {bdd:>9.1f}%")
        print(f"\nWhat matters: similar/better return at MUCH lower drawdown = real edge")
        print(f"(trend-following earns its keep by sidestepping crashes). If it just")
        print(f"matches buy-&-hold with similar drawdown, it's only beta, not an edge.")


if __name__ == "__main__":
    main()
