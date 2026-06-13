import argparse, warnings
import numpy as np
import pandas as pd
import requests, time

warnings.filterwarnings("ignore")

# ── CLI ────────────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument("--interval", default="Day1")   # MEXC futures: Min1 Min5 Min15 Min30 Min60 Hour4 Day1
ap.add_argument("--candles",  type=int, default=1000)
ap.add_argument("--ema",      type=int, default=30)
args = ap.parse_args()

MEXC_REST = "https://contract.mexc.com"

# ── SYMBOL LIST ────────────────────────────────────────────────────────────────────────────────
SYMBOLS = [
    # ── Original winners
    "BTC_USDT","ETH_USDT","SOL_USDT","BNB_USDT","XRP_USDT",
    # ── From your image
    "DOGE_USDT","PEPE_USDT","SUI_USDT",
    # ── Large caps
    "ADA_USDT","DOT_USDT","AVAX_USDT","MATIC_USDT","LTC_USDT",
    # ── Mid-tier
    "LINK_USDT","ATOM_USDT","UNI_USDT","AAVE_USDT","FTM_USDT",
    "SAND_USDT","MANA_USDT","GALA_USDT","APE_USDT","INJ_USDT",
    "ARB_USDT","OP_USDT","TIA_USDT","SEI_USDT","WLD_USDT",
    "NEAR_USDT","APT_USDT","STX_USDT","BLUR_USDT","JTO_USDT",
    # ── Choppy / weak stress tests
    "SHIB_USDT","TRX_USDT","EOS_USDT","DASH_USDT","ZEC_USDT",
    "ETC_USDT","BCH_USDT","NEO_USDT","XMR_USDT",
]

# ── FETCH (MEXC Futures — same endpoint as your bot) ─────────────────────────────────────
def fetch(symbol: str, interval: str, limit: int):
    """Uses contract.mexc.com/api/v1/contract/kline — identical to your bot."""
    try:
        url  = f"{MEXC_REST}/api/v1/contract/kline/{symbol}"
        r    = requests.get(url, params={"interval": interval, "limit": limit}, timeout=10)
        data = r.json()
        if "data" not in data:
            return None
        raw    = data["data"]
        times  = raw.get("time",  [])
        closes = raw.get("close", [])
        if not times or not closes:
            return None
        s = pd.Series(
            [float(c) for c in closes],
            index=pd.to_datetime([float(t) for t in times], unit="s")
        ).sort_index()
        return s if len(s) >= 50 else None
    except Exception:
        return None

# ── BACKTEST (50/50 IS / OOS split) ─────────────────────────────────────────────────────────────
def backtest_oos(prices: pd.Series, ema_period: int) -> dict:
    results = {}
    mid = len(prices) // 2
    for label, s in [("IS", prices.iloc[:mid]), ("OOS", prices.iloc[mid:])]:
        s      = s.copy()
        ema    = s.ewm(span=ema_period, adjust=False).mean()
        signal = (s > ema).astype(int).shift(1).fillna(0)
        rets   = s.pct_change().fillna(0)
        def metrics(r):
            cum = (1 + r).cumprod()
            dd  = ((cum - cum.cummax()) / cum.cummax()).min() * 100
            return (cum.iloc[-1] - 1) * 100, dd
        results[label] = {
            "strat": metrics(signal * rets),
            "bnh":   metrics(rets),
        }
    return results

# ── RUN ──────────────────────────────────────────────────────────────────────────────────
HDR = (f"  {'Symbol':<14} {'IS_str':>7} {'IS_sDD':>7} {'IS_bnh':>7} {'IS_bDD':>7}  |"
       f"  {'OOS_str':>7} {'OOS_sDD':>7} {'OOS_bnh':>7} {'OOS_bDD':>7}  EDGE?")

print(f"\n{'='*100}")
print(f"  MEXC FUTURES ROBUSTNESS TEST  |  EMA{args.ema}  |  {args.candles} candles  |  interval={args.interval}")
print(f"{'='*100}")
print(HDR)
print(f"  {'-'*96}")

passed = failed = skipped = 0

for sym in SYMBOLS:
    prices = fetch(sym, args.interval, args.candles)
    time.sleep(0.12)
    if prices is None:
        print(f"  {sym:<14}  -- no data --")
        skipped += 1
        continue
    try:
        r      = backtest_oos(prices, args.ema)
        is_s,  is_sdd  = r["IS"]["strat"]
        is_b,  is_bdd  = r["IS"]["bnh"]
        oos_s, oos_sdd = r["OOS"]["strat"]
        oos_b, oos_bdd = r["OOS"]["bnh"]
        edge = "EDGE" if (oos_sdd > oos_bdd + 5) else "no edge"
        if edge == "EDGE": passed += 1
        else:              failed += 1
        print(f"  {sym:<14}  {is_s:>+6.0f}%  {is_sdd:>+6.0f}%  {is_b:>+6.0f}%  {is_bdd:>+6.0f}%  |"
              f"  {oos_s:>+6.0f}%  {oos_sdd:>+6.0f}%  {oos_b:>+6.0f}%  {oos_bdd:>+6.0f}%   {edge}")
    except Exception as e:
        print(f"  {sym:<14}  ERROR: {e}")
        skipped += 1

total = passed + failed
if total == 0:
    print("\n  No results — check your internet connection or symbol names.")
else:
    print(f"\n{'='*100}")
    print(f"  RESULT: {passed}/{total} assets showed OOS drawdown edge  ({passed/total*100:.0f}% hit rate)")
    print(f"  ({skipped} symbols skipped — no data)")
    print()
    if   passed/total >= 0.60:
        print("  ROBUST  -- EMA trend edge holds broadly. NOT just survivor bias.")
    elif passed/total >= 0.40:
        print("  PARTIAL -- Edge works on trending assets; weaker on choppy ones.")
    else:
        print("  FRAGILE -- Edge does not generalise. Re-examine before deploying.")
    print(f"{'='*100}\n")
