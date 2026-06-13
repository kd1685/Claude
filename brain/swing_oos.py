"""
swing_oos.py — the integrity test. Does the trend edge survive OUT-OF-SAMPLE?

Splits each coin's history in half. Reports the trend strategy on the FIRST half
(in-sample) and the SECOND half (out-of-sample) separately, for several EMA
lengths. A real edge beats buy-&-hold (especially on drawdown) in BOTH halves.
If it only works in the first half, it was curve-fit to that period.

  python swing_oos.py --interval Day1 --candles 1000
  python swing_oos.py --interval Day1 --candles 1000 --symbols BTC_USDT,ETH_USDT,SOL_USDT

Needs engine.py + swing_backtest.py alongside.
"""

import argparse
from swing_backtest import fetch, run


def avg(rs, k):
    return sum(r[k] for r in rs) / len(rs) if rs else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", default="Day1")
    ap.add_argument("--candles", type=int, default=1000)
    ap.add_argument("--symbols", default="BTC_USDT,ETH_USDT,SOL_USDT,BNB_USDT,XRP_USDT")
    ap.add_argument("--emas", default="10,20,30,50")
    a = ap.parse_args()
    syms = [s.strip() for s in a.symbols.split(",") if s.strip()]
    emas = [int(x) for x in a.emas.split(",")]

    closes = {}
    for s in syms:
        c = fetch(s, a.interval, a.candles)
        if len(c) < 200:
            print(f"  {s}: {len(c)} candles — skipped"); continue
        closes[s] = c
        print(f"  {s}: {len(c)} candles")
    if not closes:
        print("No data."); return

    print(f"\n{'':6} | {'IN-SAMPLE (1st half)':^34} | {'OUT-OF-SAMPLE (2nd half)':^34}")
    print(f"{'EMA':<6} | {'strat%':>9} {'sDD%':>6} {'B&H%':>9} {'bDD%':>6} | "
          f"{'strat%':>9} {'sDD%':>6} {'B&H%':>9} {'bDD%':>6}")
    print("-"*82)
    for ema in emas:
        h1, h2 = [], []
        for s, c in closes.items():
            half = len(c)//2
            if half < ema + 30:
                continue
            h1.append(run(c[:half], ema, False, 1.0))
            h2.append(run(c[half:], ema, False, 1.0))
        if not h1:
            continue
        print(f"{ema:<6} | {avg(h1,'ret'):>+9.0f} {avg(h1,'dd'):>5.0f}% "
              f"{avg(h1,'bh_ret'):>+9.0f} {avg(h1,'bh_dd'):>5.0f}% | "
              f"{avg(h2,'ret'):>+9.0f} {avg(h2,'dd'):>5.0f}% "
              f"{avg(h2,'bh_ret'):>+9.0f} {avg(h2,'bh_dd'):>5.0f}%")

    print("\nVERDICT GUIDE:")
    print("  • Edge is REAL if, out-of-sample, strat drawdown stays well below B&H")
    print("    drawdown AND return is competitive — in BOTH halves, across EMAs.")
    print("  • Edge was CURVE-FIT if it shines in-sample but collapses out-of-sample.")
    print("  • Returns differ between halves (different market regimes) — that's fine;")
    print("    what must persist is the DRAWDOWN-control advantage vs buy-&-hold.")


if __name__ == "__main__":
    main()
