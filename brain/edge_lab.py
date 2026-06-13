"""
edge_lab.py — OWNER'S RESEARCH TOOL (lives in brain/, never deployed:
the Docker build context is platform/, so nothing here reaches the server).

Mass-sweeps indicator combinations to hunt for an edge — every indicator,
weight mix, threshold pair, long-only or long/short — across a basket of
symbols, on daily or intraday candles, with honest accounting throughout.

WHY THIS IS FAST
  An indicator's vote (BULL/NEUTRAL/BEAR) at a bar doesn't depend on which
  other indicators are enabled or on any weights. So the lab computes the
  full VOTE MATRIX (every indicator at every bar, same compute_panel code
  path as the live platform) ONCE per symbol and caches it. After that,
  scoring any combination is pure arithmetic:
      score = Σ(w_k · v_k) / Σ(w_k) × 10      (v: BULL=1, NEUTRAL=.5, BEAR=0)
  → identical to indicators.compute_panel, but ~1000× faster per config.
  Practical throughput after the one-time build: ~30–80k configs/minute
  per symbol on a normal PC.

WHY YOU CAN'T JUST "PICK THE BEST ROW" (read once, please)
  Testing thousands of combinations GUARANTEES some look brilliant by pure
  luck — that's multiple testing, and it's how fake edges are born. The lab
  defends you three ways, none of which you should disable:
    1. TRAIN/TEST SPLIT — configs are RANKED on the first 70% of history
       and you judge them on the untouched last 30% (columns prefixed t_).
       A real edge survives the part of history it never saw.
    2. BASKET MEDIAN — every config is scored across ALL symbols; the
       leaderboard uses the MEDIAN, so one lucky coin can't carry a config.
    3. LUCK ESTIMATE — the report prints the best train-Sharpe you'd expect
       from pure noise given how many configs you tested. If your winner
       isn't clearly above that line, you found luck, not edge.
  And the final referee is never a backtest: whatever survives here goes to
  the BOTS tab in PAPER for weeks before a penny touches it.

USAGE (from the brain/ folder; needs ccxt installed)
  python edge_lab.py build  --symbols BTC_USDT,ETH_USDT,SOL_USDT --tf 1d --bars 900
  python edge_lab.py single                       # each indicator alone
  python edge_lab.py pairs                        # all pairs × weight ratios
  python edge_lab.py random --trials 50000        # random subset/weight/threshold search
  python edge_lab.py greedy                       # forward selection on TRAIN only
  python edge_lab.py full --trials 50000          # all of the above, in order
  python edge_lab.py top                          # leaderboard from edge_results.csv
  Common flags: --symbols … --tf 1d|1h|15m|5m --bars N --shorts --fee 0.001
  (build is implicit: any mode builds missing caches first)

OUTPUT
  brain/edge_results.csv — one row per config: indicators, weights,
  thresholds, and per-split stats (Sharpe, CAGR, MaxDD, trades, win rate,
  fees) as the basket median, plus per-split EMA30-baseline and buy&hold
  context. The `top` command prints the leaderboard with the luck line.
"""

import argparse
import csv
import itertools
import json
import math
import os
import random
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "platform"))

import indicators                                            # noqa: E402

class InsufficientData(Exception):
    pass


CACHE_DIR = os.path.join(HERE, "edge_cache")
RESULTS = os.path.join(HERE, "edge_results.csv")
ALL_KEYS = list(indicators.REGISTRY.keys())
WARMUP = 120                       # bars of history before the first signal
VOTE_VAL = {"BULL": 1.0, "NEUTRAL": 0.5, "BEAR": 0.0}
TRAIN_FRAC = 0.70
BARS_PER_YEAR = {"1d": 365, "4h": 365 * 6, "1h": 365 * 24, "15m": 365 * 96,
                 "5m": 365 * 288, "3d": 365 / 3, "1w": 52}


# ═══════════════════════════════════════════════════════════════════════════
#  Data + vote-matrix build (cached)
# ═══════════════════════════════════════════════════════════════════════════

def _fetch(symbol, tf, bars, exchange):
    import exchanges
    if tf == "1d":
        return exchanges.fetch_daily(symbol, exchange, bars + WARMUP)
    return exchanges.fetch_ohlcv_tf(symbol, exchange, tf, bars + WARMUP)


def build_cache(symbol, tf, bars, exchange, force=False):
    """Fetch candles and precompute the per-bar vote matrix. Cached on disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{symbol}_{tf}.json")
    if not force and os.path.exists(path):
        d = json.load(open(path))
        if len(d["closes"]) >= min(bars, 200):
            return d
    print(f"  [{symbol} {tf}] fetching candles…", flush=True)
    candles = _fetch(symbol, tf, bars, exchange)
    if len(candles) < WARMUP + 100:
        raise InsufficientData(f"{symbol}: only {len(candles)} candles — need {WARMUP + 100}+ "
                               f"(newer coin or unsupported tf on this exchange).")
    n = len(candles)
    print(f"  [{symbol} {tf}] building vote matrix on {n - WARMUP} bars "
          f"(one-time, ~{(n - WARMUP) / 400:.0f}s)…", flush=True)
    t0 = time.time()
    votes = []                                   # votes[i][k_idx] ∈ {1, .5, 0}
    for t in range(WARMUP, n):
        p = indicators.compute_panel(candles[:t + 1], volumes=None,
                                     enabled=ALL_KEYS, weights=None)
        sig = p["signals"]
        votes.append([VOTE_VAL.get((sig.get(k) or {}).get("vote"), 0.5)
                      for k in ALL_KEYS])
    d = {"symbol": symbol, "tf": tf, "keys": ALL_KEYS,
         "times": [c["time"] for c in candles[WARMUP:]],
         "closes": [c["close"] for c in candles[WARMUP:]],
         "votes": votes}
    json.dump(d, open(path, "w"))
    print(f"  [{symbol} {tf}] cached ({time.time() - t0:.0f}s).", flush=True)
    return d


# ═══════════════════════════════════════════════════════════════════════════
#  Config evaluation on the cached matrix (the fast path)
# ═══════════════════════════════════════════════════════════════════════════

def _scores_for(data, idxs, ws):
    """Panel score at every bar for one config — identical formula to
    indicators.compute_panel: (Σ w·v)/Σw × 10."""
    tot = sum(ws)
    votes = data["votes"]
    return [sum(votes[i][j] * w for j, w in zip(idxs, ws)) / tot * 10.0
            for i in range(len(votes))]


def _simulate(closes, scores, lo, hi, long_th, short_th, allow_short, fee, tf):
    """Mirror of platform/backtest.py::_simulate on a [lo, hi) slice:
    signal at t earns t→t+1; fee per side on every position change."""
    equity, pos, fees, trades, wins = 1.0, 0, 0.0, 0, 0
    entry, peak, maxdd = None, 1.0, 0.0
    rets = []
    for t in range(lo, hi - 1):
        s = scores[t]
        want = (1 if s >= long_th else
                (-1 if allow_short else 0) if s <= short_th else pos)
        if want != pos:
            cost = abs(want - pos) * fee
            equity *= (1 - cost)
            fees += cost
            if pos != 0:
                trades += 1
                if entry and equity > entry:
                    wins += 1
            entry = equity if want != 0 else None
            pos = want
        r = closes[t + 1] / closes[t] - 1.0
        step = pos * r
        equity *= (1 + step)
        rets.append(step)
        peak = max(peak, equity)
        maxdd = max(maxdd, 1 - equity / peak)
    if pos != 0:
        trades += 1
        if entry and equity > entry:
            wins += 1
    nbars = max(1, hi - 1 - lo)
    per_year = BARS_PER_YEAR.get(tf, 365)
    years = nbars / per_year
    cagr = (equity ** (1 / years) - 1) * 100 if equity > 0 and years > 0 else -100.0
    mu = statistics.fmean(rets) if rets else 0.0
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (mu / sd) * math.sqrt(per_year) if sd > 1e-12 else 0.0
    return {"sharpe": round(sharpe, 2), "final_x": round(equity, 3),
            "cagr": round(cagr, 1), "maxdd": round(maxdd * 100, 1),
            "trades": trades,
            "win": round(wins / trades * 100, 1) if trades else None,
            "fees": round(fees * 100, 2)}


def evaluate(datas, idxs, ws, long_th, short_th, allow_short, fee, tf):
    """One config across the whole basket → median train/test stats."""
    tr, te = [], []
    for d in datas:
        n = len(d["closes"])
        split = int(n * TRAIN_FRAC)
        sc = _scores_for(d, idxs, ws)
        tr.append(_simulate(d["closes"], sc, 0, split, long_th, short_th, allow_short, fee, tf))
        te.append(_simulate(d["closes"], sc, split, n, long_th, short_th, allow_short, fee, tf))

    def med(rows, k):
        vals = [r[k] for r in rows if r[k] is not None]
        return round(statistics.median(vals), 2) if vals else None
    keys = ("sharpe", "final_x", "cagr", "maxdd", "trades", "win", "fees")
    return ({k: med(tr, k) for k in keys}, {k: med(te, k) for k in keys})


def baselines(datas, fee, tf):
    """EMA30 long/flat + buy&hold, same splits, for context."""
    out = {}
    for name in ("ema30", "buyhold"):
        tr, te = [], []
        for d in datas:
            closes = d["closes"]
            n = len(closes)
            split = int(n * TRAIN_FRAC)
            if name == "buyhold":
                sc = [10.0] * n
                f = 0.0
            else:
                e = _ema_series(closes, 30)
                sc = [10.0 if closes[i] > e[i] else 0.0 for i in range(n)]
                f = fee
            tr.append(_simulate(closes, sc, 0, split, 6, 4, False, f, tf))
            te.append(_simulate(closes, sc, split, n, 6, 4, False, f, tf))
        out[name] = (
            {k: round(statistics.median([r[k] for r in tr]), 2) for k in ("sharpe", "cagr", "maxdd")},
            {k: round(statistics.median([r[k] for r in te]), 2) for k in ("sharpe", "cagr", "maxdd")})
    return out


def _ema_series(closes, period):
    """EMA aligned to closes (first `period` bars hold the seed value)."""
    k = 2 / (period + 1)
    seed = sum(closes[:period]) / max(1, len(closes[:period]))
    out, e = [], seed
    for i, v in enumerate(closes):
        if i < period:
            out.append(seed)
            continue
        e = v * k + e * (1 - k)
        out.append(e)
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Search modes
# ═══════════════════════════════════════════════════════════════════════════

def _row(mode, keys_w, long_th, short_th, shorts, train, test, meta):
    return {
        "mode": mode,
        "indicators": "+".join(f"{k}:{w:g}" for k, w in keys_w),
        "n_ind": len(keys_w),
        "long_th": long_th, "short_th": short_th, "shorts": int(shorts),
        **{f"tr_{k}": v for k, v in train.items()},
        **{f"t_{k}": v for k, v in test.items()},
        **meta,
    }


def mode_single(datas, args, meta):
    rows = []
    for j, key in enumerate(ALL_KEYS):
        tr, te = evaluate(datas, [j], [1.0], 6.0, 4.0, args.shorts, args.fee, args.tf)
        rows.append(_row("single", [(key, 1.0)], 6.0, 4.0, args.shorts, tr, te, meta))
    return rows


def mode_pairs(datas, args, meta):
    rows = []
    ratios = [(1, 1), (2, 1), (1, 2)]
    combos = list(itertools.combinations(range(len(ALL_KEYS)), 2))
    print(f"  pairs: {len(combos) * len(ratios)} configs…")
    for (a, b) in combos:
        for (wa, wb) in ratios:
            tr, te = evaluate(datas, [a, b], [float(wa), float(wb)],
                              6.0, 4.0, args.shorts, args.fee, args.tf)
            rows.append(_row("pairs", [(ALL_KEYS[a], wa), (ALL_KEYS[b], wb)],
                             6.0, 4.0, args.shorts, tr, te, meta))
    return rows


def mode_random(datas, args, meta):
    rng = random.Random(args.seed)
    rows = []
    t0 = time.time()
    for i in range(args.trials):
        k = rng.randint(2, min(10, len(ALL_KEYS)))
        idxs = rng.sample(range(len(ALL_KEYS)), k)
        ws = [rng.choice((0.5, 1.0, 1.0, 1.5, 2.0, 3.0)) for _ in idxs]
        long_th = round(rng.uniform(5.5, 8.0), 1)
        short_th = round(rng.uniform(2.0, 4.5), 1)
        shorts = args.shorts and rng.random() < 0.5
        tr, te = evaluate(datas, idxs, ws, long_th, short_th, shorts, args.fee, args.tf)
        rows.append(_row("random", list(zip([ALL_KEYS[j] for j in idxs], ws)),
                         long_th, short_th, shorts, tr, te, meta))
        if (i + 1) % 1000 == 0:
            rate = (i + 1) / (time.time() - t0)
            print(f"  random: {i + 1}/{args.trials}  ({rate:.0f} cfg/s, "
                  f"~{(args.trials - i - 1) / rate / 60:.0f} min left)", flush=True)
    return rows


def mode_greedy(datas, args, meta):
    """Forward selection — ranked on TRAIN ONLY (test never touches choice)."""
    chosen, best_tr = [], -1e9
    rows = []
    while len(chosen) < 10:
        cand = None
        for j in range(len(ALL_KEYS)):
            if j in chosen:
                continue
            trial = chosen + [j]
            tr, te = evaluate(datas, trial, [1.0] * len(trial),
                              6.0, 4.0, args.shorts, args.fee, args.tf)
            if tr["sharpe"] is not None and tr["sharpe"] > best_tr + 0.01:
                cand, best_tr, cand_stats = j, tr["sharpe"], (tr, te)
        if cand is None:
            break
        chosen.append(cand)
        tr, te = cand_stats
        rows.append(_row("greedy", [(ALL_KEYS[j], 1.0) for j in chosen],
                         6.0, 4.0, args.shorts, tr, te, meta))
        print(f"  greedy +{ALL_KEYS[cand]:<14} train Sharpe {tr['sharpe']:>5}  "
              f"TEST Sharpe {te['sharpe']}")
    return rows


# ═══════════════════════════════════════════════════════════════════════════
#  Results + report
# ═══════════════════════════════════════════════════════════════════════════

def save_rows(rows):
    if not rows:
        return
    exists = os.path.exists(RESULTS)
    with open(RESULTS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if not exists:
            w.writeheader()
        w.writerows(rows)
    print(f"  saved {len(rows)} rows → {RESULTS}")


def luck_line(n_configs, bars, tf):
    """Best train-Sharpe expected from PURE NOISE after n_configs tries:
    max of n_configs ~Normal(0, 1/sqrt(years)) draws ≈ sqrt(2·ln n)/sqrt(years)."""
    years = max(0.25, bars / BARS_PER_YEAR.get(tf, 365))
    return math.sqrt(2 * math.log(max(2, n_configs))) / math.sqrt(years)


def report(args):
    if not os.path.exists(RESULTS):
        print("No results yet — run a sweep first.")
        return
    rows = list(csv.DictReader(open(RESULTS)))
    for r in rows:
        for k in ("tr_sharpe", "t_sharpe", "tr_cagr", "t_cagr", "tr_maxdd", "t_maxdd"):
            try:
                r[k] = float(r[k])
            except (ValueError, KeyError, TypeError):
                r[k] = float("-inf")
    bars = int(rows[0].get("bars", 700) or 700)
    tf = rows[0].get("tf", "1d")
    lucky = luck_line(len(rows), int(bars * TRAIN_FRAC), tf)

    print(f"\n═══ EDGE LAB LEADERBOARD — {len(rows)} configs tested ═══")
    print(f"⚠ LUCK LINE: with {len(rows)} tries on this much history, pure noise is "
          f"expected to produce a best TRAIN Sharpe of ≈ {lucky:.2f}.")
    print(f"  A candidate must beat that on TRAIN *and* hold up in the t_ (test) "
          f"columns *and* survive weeks of paper trading to mean anything.\n")
    hdr = f"{'mode':7} {'trainShp':>8} {'TESTShp':>8} {'tCAGR%':>7} {'tMaxDD%':>8}  indicators"
    print("— ranked by TRAIN Sharpe (selection view) —")
    print(hdr)
    for r in sorted(rows, key=lambda x: -x["tr_sharpe"])[:15]:
        print(f"{r['mode']:7} {r['tr_sharpe']:>8.2f} {r['t_sharpe']:>8.2f} "
              f"{r['t_cagr']:>7.1f} {r['t_maxdd']:>8.1f}  {r['indicators'][:70]}")
    print("\n— ranked by TEST Sharpe (peeking! for curiosity only — selecting on "
          "this column is self-deception) —")
    print(hdr)
    for r in sorted(rows, key=lambda x: -x["t_sharpe"])[:10]:
        print(f"{r['mode']:7} {r['tr_sharpe']:>8.2f} {r['t_sharpe']:>8.2f} "
              f"{r['t_cagr']:>7.1f} {r['t_maxdd']:>8.1f}  {r['indicators'][:70]}")
    print("\nNext step for any survivor: BOTS tab → PAPER for several weeks. "
          "No exceptions — that's the rule that keeps you honest.")


# ═══════════════════════════════════════════════════════════════════════════

STABLE_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "EUR", "USDE", "BUSD"}


def _resolve_symbols(arg: str, exchange: str) -> list:
    """'BTC_USDT,ETH_USDT' passes through; 'top10' fetches the 10 largest
    USDT spot pairs by 24h quote volume from the exchange (stables excluded)."""
    arg = arg.strip()
    import re as _re
    m = _re.fullmatch(r"top(\d{1,3})", arg, _re.I)
    if not m:
        return [x.strip().upper() for x in arg.split(",") if x.strip()]
    n = max(1, int(m.group(1)))
    try:
        import ccxt
        ex = getattr(ccxt, exchange)({"enableRateLimit": True})
        tickers = ex.fetch_tickers()
    except Exception as e:
        raise SystemExit(f"Could not fetch top symbols from {exchange}: {e}\n"
                         f"Pass an explicit list instead, e.g. --symbols BTC_USDT,ETH_USDT")
    rows = []
    for sym, t in tickers.items():
        if "/" not in sym or ":" in sym:                 # spot only
            continue
        base, quote = sym.split("/")
        if quote != "USDT" or base in STABLE_BASES:
            continue
        rows.append((float(t.get("quoteVolume") or 0), base))
    rows.sort(reverse=True)
    picks = [f"{b}_USDT" for _, b in rows[:n]]
    if not picks:
        raise SystemExit(f"No USDT spot pairs found on {exchange}.")
    print(f"  top{n} on {exchange}: {', '.join(picks)}")
    return picks


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("build", "single", "pairs", "random",
                                     "greedy", "full", "top"))
    ap.add_argument("--symbols", default="BTC_USDT,ETH_USDT,SOL_USDT,BNB_USDT,XRP_USDT")
    ap.add_argument("--tf", default="1d", choices=tuple(BARS_PER_YEAR))
    ap.add_argument("--bars", type=int, default=900)
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--fee", type=float, default=0.0010)
    ap.add_argument("--shorts", action="store_true")
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rebuild", action="store_true", help="force-refresh the candle/vote cache")
    args = ap.parse_args()

    if args.mode == "top":
        report(args)
        return

    symbols = _resolve_symbols(args.symbols, args.exchange)
    datas, skipped = [], []
    for sym in symbols:
        try:
            datas.append(build_cache(sym, args.tf, args.bars, args.exchange, args.rebuild))
        except InsufficientData as e:
            skipped.append(sym)
            print(f"  ⚠ skipping {e}")
    if skipped:
        print(f"  basket continues with {len(datas)}/{len(symbols)} symbols "
              f"(skipped: {', '.join(skipped)})")
    if not datas:
        raise SystemExit("No symbol had enough history — try fewer --bars, a higher tf, "
                         "or another --exchange.")
    if args.mode == "build":
        print("Caches ready.")
        return

    meta = {"symbols": ",".join(symbols), "tf": args.tf,
            "bars": len(datas[0]["closes"]), "fee": args.fee,
            "ts": int(time.time())}
    base = baselines(datas, args.fee, args.tf)
    print(f"\nBaselines (basket median)  —  EMA30: train Sharpe "
          f"{base['ema30'][0]['sharpe']}, TEST Sharpe {base['ema30'][1]['sharpe']} "
          f"(TEST CAGR {base['ema30'][1]['cagr']}%, DD {base['ema30'][1]['maxdd']}%)"
          f"  ·  Buy&hold TEST Sharpe {base['buyhold'][1]['sharpe']}\n"
          f"Anything that can't beat BOTH of those out-of-sample is not an edge.\n")

    modes = [args.mode] if args.mode != "full" else ["single", "pairs", "random", "greedy"]
    for m in modes:
        print(f"── {m} ──")
        rows = {"single": mode_single, "pairs": mode_pairs,
                "random": mode_random, "greedy": mode_greedy}[m](datas, args, meta)
        save_rows(rows)
    report(args)


if __name__ == "__main__":
    main()
