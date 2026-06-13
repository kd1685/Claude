#!/usr/bin/env python3
"""
Ascent Terminal — Edge Lab (walk-forward backtester)
=====================================================
Runs a parallel walk-forward backtest on MEXC OHLCV data.
Outputs:
  brain/edge_results.csv  — per-fold metrics
  brain/edge_report.html  — summary HTML report

Usage:
  python edge_lab.py                  # full backtest
  python edge_lab.py --dry-run        # fetch data + compute signals, no HTML
  python edge_lab.py --symbol ETH/USDT --timeframe 4h

Required env vars (loaded from ../.env or system):
  MEXC_API_KEY, MEXC_SECRET_KEY

Optional env / CLI overrides (see argparse below):
  EDGELAB_SYMBOL, EDGELAB_TIMEFRAME, EDGELAB_FOLDS,
  EDGELAB_TRAIN_BARS, EDGELAB_TEST_BARS,
  EDGELAB_EMA_FAST, EDGELAB_EMA_SLOW,
  EDGELAB_RSI_PERIOD, EDGELAB_ATR_PERIOD,
  EDGELAB_RISK_PCT, EDGELAB_ATR_MULT,
  EDGELAB_ADX_PERIOD, EDGELAB_ADX_THRESHOLD,
  EDGELAB_SWEEP           (1/0 — run ±20 % param sweep)
"""

import argparse
import os
import sys
import math
import json
import time
import logging
import itertools
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import ccxt
import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("edge_lab")

# ── CLI / env config ─────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Ascent Edge Lab")
parser.add_argument("--dry-run",   action="store_true")
parser.add_argument("--symbol",    default=os.getenv("EDGELAB_SYMBOL",    "BTC/USDT"))
parser.add_argument("--timeframe", default=os.getenv("EDGELAB_TIMEFRAME", "1d"))
parser.add_argument("--folds",     type=int, default=int(os.getenv("EDGELAB_FOLDS",      "5")))
parser.add_argument("--train",     type=int, default=int(os.getenv("EDGELAB_TRAIN_BARS", "200")))
parser.add_argument("--test",      type=int, default=int(os.getenv("EDGELAB_TEST_BARS",  "50")))
args, _ = parser.parse_known_args()

BASE_PARAMS = {
    "ema_fast":      int(os.getenv("EDGELAB_EMA_FAST",      "9")),
    "ema_slow":      int(os.getenv("EDGELAB_EMA_SLOW",      "21")),
    "rsi_period":    int(os.getenv("EDGELAB_RSI_PERIOD",    "14")),
    "atr_period":    int(os.getenv("EDGELAB_ATR_PERIOD",    "14")),
    "risk_pct":    float(os.getenv("EDGELAB_RISK_PCT",    "0.01")),
    "atr_mult":    float(os.getenv("EDGELAB_ATR_MULT",    "1.5")),
    "adx_period":    int(os.getenv("EDGELAB_ADX_PERIOD",    "14")),
    "adx_threshold":float(os.getenv("EDGELAB_ADX_THRESHOLD","20.0")),
}
RUN_SWEEP = os.getenv("EDGELAB_SWEEP", "0") == "1"


# ── Indicators ───────────────────────────────────────────────────────────────
def _ema(arr: np.ndarray, n: int) -> np.ndarray:
    k = 2.0 / (n + 1)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def _rsi(closes: np.ndarray, n: int) -> np.ndarray:
    delta = np.diff(closes)
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_g = np.full(len(closes), np.nan)
    avg_l = np.full(len(closes), np.nan)
    avg_g[n] = gain[:n].mean()
    avg_l[n] = loss[:n].mean()
    for i in range(n + 1, len(closes)):
        avg_g[i] = (avg_g[i-1] * (n-1) + gain[i-1]) / n
        avg_l[i] = (avg_l[i-1] * (n-1) + loss[i-1]) / n
    rs = np.where(avg_l == 0, 100.0, avg_g / avg_l)
    return np.where(np.isnan(avg_g), np.nan, 100.0 - 100.0 / (1 + rs))


def _atr(highs: np.ndarray, lows: np.ndarray,
         closes: np.ndarray, n: int) -> np.ndarray:
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]),
                   np.abs(lows[1:]  - closes[:-1])),
    )
    atr_arr = np.full(len(closes), np.nan)
    atr_arr[n] = tr[:n].mean()
    for i in range(n + 1, len(closes)):
        atr_arr[i] = (atr_arr[i-1] * (n-1) + tr[i-1]) / n
    return atr_arr


def _adx(highs: np.ndarray, lows: np.ndarray,
         closes: np.ndarray, n: int) -> np.ndarray:
    """Wilder ADX."""
    dm_pos = np.maximum(np.diff(highs), 0.0)
    dm_neg = np.maximum(np.diff(-lows), 0.0)
    # zero where the other is larger
    mask = dm_pos > dm_neg
    dm_pos = np.where(mask, dm_pos, 0.0)
    dm_neg = np.where(~mask, dm_neg, 0.0)

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]),
                   np.abs(lows[1:]  - closes[:-1])),
    )
    length = len(highs)
    atr14  = np.full(length, np.nan)
    pdi14  = np.full(length, np.nan)
    mdi14  = np.full(length, np.nan)
    adx    = np.full(length, np.nan)

    atr14[n] = tr[:n].mean()
    pdi14[n] = dm_pos[:n].mean()
    mdi14[n] = dm_neg[:n].mean()

    for i in range(n + 1, length):
        atr14[i] = (atr14[i-1] * (n-1) + tr[i-1])     / n
        pdi14[i] = (pdi14[i-1] * (n-1) + dm_pos[i-1]) / n
        mdi14[i] = (mdi14[i-1] * (n-1) + dm_neg[i-1]) / n

    with np.errstate(invalid="ignore", divide="ignore"):
        di_pos = 100 * pdi14 / atr14
        di_neg = 100 * mdi14 / atr14
        dx     = 100 * np.abs(di_pos - di_neg) / (di_pos + di_neg)

    adx[2*n] = np.nanmean(dx[n:2*n])
    for i in range(2*n + 1, length):
        adx[i] = (adx[i-1] * (n-1) + dx[i]) / n

    return adx


# ── Back-test engine ─────────────────────────────────────────────────────────
@dataclass
class FoldResult:
    fold:       int
    params:     dict
    n_trades:   int     = 0
    total_pnl:  float   = 0.0
    sharpe:     float   = 0.0
    max_dd:     float   = 0.0
    win_rate:   float   = 0.0
    trade_pnls: list    = field(default_factory=list)


def _run_fold(payload: dict) -> FoldResult:
    """
    Runs one walk-forward fold.  Called in a subprocess.
    payload keys: fold, ohlcv_slice (list), params (dict)
    """
    fold   = payload["fold"]
    ohlcv  = np.array(payload["ohlcv"], dtype=float)
    p      = payload["params"]

    highs  = ohlcv[:, 2]
    lows   = ohlcv[:, 3]
    closes = ohlcv[:, 4]

    fast   = _ema(closes, p["ema_fast"])
    slow   = _ema(closes, p["ema_slow"])
    rsi_v  = _rsi(closes, p["rsi_period"])
    atr_v  = _atr(highs, lows, closes, p["atr_period"])
    adx_v  = _adx(highs, lows, closes, p["adx_period"])

    equity = 10_000.0
    pos    = None
    trade_pnls: List[float] = []

    for i in range(1, len(closes)):
        if any(np.isnan(x) for x in [fast[i], slow[i], rsi_v[i], atr_v[i], adx_v[i]]):
            continue

        price     = closes[i]
        crossup   = fast[i-1] <= slow[i-1] and fast[i] > slow[i]
        crossdown = fast[i-1] >= slow[i-1] and fast[i] < slow[i]
        in_trend  = adx_v[i] >= p["adx_threshold"]

        # Exit
        if pos:
            hit_stop = (
                (pos["side"] == "long"  and price <= pos["stop"]) or
                (pos["side"] == "short" and price >= pos["stop"])
            )
            exit_sig  = (
                (pos["side"] == "long"  and crossdown) or
                (pos["side"] == "short" and crossup)
            )
            if hit_stop or exit_sig:
                if pos["side"] == "long":
                    pnl = (price - pos["entry"]) * pos["qty"]
                else:
                    pnl = (pos["entry"] - price) * pos["qty"]
                pnl -= (pos["entry"] + price) * pos["qty"] * 0.001
                equity += pnl
                trade_pnls.append(pnl)
                pos = None

        # Entry
        if not pos and in_trend:
            stop_dist = atr_v[i] * p["atr_mult"]
            qty       = (equity * p["risk_pct"]) / stop_dist if stop_dist > 0 else 0
            if qty > 0:
                if crossup and rsi_v[i] < 70:
                    pos = {"side": "long",  "entry": price,
                           "qty": qty, "stop": price - stop_dist}
                elif crossdown and rsi_v[i] > 30:
                    pos = {"side": "short", "entry": price,
                           "qty": qty, "stop": price + stop_dist}

    # Compute fold stats
    result = FoldResult(fold=fold, params=p)
    if trade_pnls:
        arr        = np.array(trade_pnls)
        result.n_trades  = len(arr)
        result.total_pnl = float(arr.sum())
        result.win_rate  = float((arr > 0).mean())
        std = arr.std()
        result.sharpe    = float(arr.mean() / std * math.sqrt(252)) if std > 0 else 0.0
        cumulative = np.cumsum(arr)
        peak       = np.maximum.accumulate(cumulative)
        dd         = (peak - cumulative) / (np.abs(peak) + 1e-9)
        result.max_dd    = float(dd.max())
        result.trade_pnls = arr.tolist()

    return result


# ── Data fetcher ─────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, timeframe: str,
                needed: int) -> List[List[float]]:
    exchange = ccxt.mexc({
        "apiKey": os.getenv("MEXC_API_KEY", ""),
        "secret": os.getenv("MEXC_SECRET_KEY", ""),
        "enableRateLimit": True,
    })
    exchange.load_markets()

    all_ohlcv: List[List[float]] = []
    since = None
    batch = 1000

    while len(all_ohlcv) < needed:
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=batch)
        if not candles:
            break
        if all_ohlcv and candles[0][0] <= all_ohlcv[-1][0]:
            candles = [c for c in candles if c[0] > all_ohlcv[-1][0]]
        all_ohlcv.extend(candles)
        since = all_ohlcv[-1][0] + 1
        if len(candles) < batch:
            break
        time.sleep(exchange.rateLimit / 1000)

    log.info("fetched_candles", symbol=symbol, timeframe=timeframe, n=len(all_ohlcv))
    return all_ohlcv


# ── Param sweep ───────────────────────────────────────────────────────────────
def build_sweep_params(base: dict) -> List[dict]:
    """±20 % sweep on integer and float knobs."""
    sweep_keys = ["ema_fast", "ema_slow", "rsi_period",
                  "atr_period", "atr_mult", "adx_threshold"]
    variants: Dict[str, list] = {}
    for k in sweep_keys:
        v = base[k]
        if isinstance(v, int):
            lo = max(2, int(v * 0.8))
            hi = int(v * 1.2) + 1
            variants[k] = list(range(lo, hi + 1, max(1, (hi - lo) // 3)))
        else:
            variants[k] = [round(v * f, 4) for f in (0.8, 1.0, 1.2)]

    combos = list(itertools.product(*variants.values()))
    result = []
    for combo in combos:
        p = dict(base)
        for k, val in zip(variants.keys(), combo):
            p[k] = val
        # sanity: ema_fast < ema_slow
        if p["ema_fast"] < p["ema_slow"]:
            result.append(p)
    return result


# ── HTML report ───────────────────────────────────────────────────────────────
def write_html_report(results: List[FoldResult], symbol: str,
                       timeframe: str, out_path: Path):
    rows = "".join(
        f"<tr><td>{r.fold}</td><td>{r.n_trades}</td>"
        f"<td>{r.total_pnl:+.2f}</td><td>{r.sharpe:.3f}</td>"
        f"<td>{r.max_dd:.1%}</td><td>{r.win_rate:.1%}</td></tr>"
        for r in results
    )
    avg_sharpe = np.mean([r.sharpe for r in results]) if results else 0
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Edge Lab Report — {symbol} {timeframe}</title>
<style>
  body{{font-family:sans-serif;padding:2em}}
  h1{{color:#1a1a2e}}table{{border-collapse:collapse;width:100%}}
  th,td{{border:1px solid #ccc;padding:.5em 1em;text-align:right}}
  th{{background:#1a1a2e;color:#fff}}
  .good{{color:green}}.bad{{color:red}}
</style></head><body>
<h1>Edge Lab — {symbol} {timeframe}</h1>
<p>Average Sharpe across folds: <strong class="{'good' if avg_sharpe > 1 else 'bad'}">{avg_sharpe:.3f}</strong></p>
<table><thead><tr>
  <th>Fold</th><th>Trades</th><th>PnL (USDT)</th>
  <th>Sharpe</th><th>Max DD</th><th>Win Rate</th>
</tr></thead><tbody>{rows}</tbody></table>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
    log.info("html_report_written", path=str(out_path))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    needed = args.folds * (args.train + args.test) + max(BASE_PARAMS.values()) + 10
    log.info("fetching_data", symbol=args.symbol, timeframe=args.timeframe,
             needed=needed)

    ohlcv = fetch_ohlcv(args.symbol, args.timeframe, needed)
    if len(ohlcv) < needed:
        log.error("not_enough_data", have=len(ohlcv), need=needed)
        sys.exit(1)

    if args.dry_run:
        log.info("dry_run_complete", candles=len(ohlcv))
        sys.exit(0)

    # Build folds
    fold_size = args.train + args.test
    folds_data = []
    for fold_idx in range(args.folds):
        start = fold_idx * args.test
        end   = start + fold_size
        if end > len(ohlcv):
            break
        # train on first `train` bars, test on last `test` bars of slice
        test_slice = ohlcv[start + args.train : end]
        # we need the full slice for indicator warm-up
        full_slice = ohlcv[start : end]
        folds_data.append({"fold": fold_idx, "ohlcv": full_slice,
                            "params": BASE_PARAMS})

    # Optionally add sweep variants on fold 0
    if RUN_SWEEP:
        for p in build_sweep_params(BASE_PARAMS):
            folds_data.append({"fold": 0, "ohlcv": folds_data[0]["ohlcv"],
                                "params": p})

    log.info("running_folds", total=len(folds_data))
    results: List[FoldResult] = []

    with ProcessPoolExecutor() as pool:
        futures = {pool.submit(_run_fold, fd): fd["fold"] for fd in folds_data}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                results.append(res)
                log.info("fold_done", fold=res.fold,
                          n_trades=res.n_trades,
                          sharpe=round(res.sharpe, 3),
                          pnl=round(res.total_pnl, 2))
            except Exception as exc:  # noqa: BLE001
                log.error("fold_error", fold=futures[fut], error=str(exc))

    # Write CSV
    out_dir = Path(__file__).parent
    csv_path = out_dir / "edge_results.csv"
    df = pd.DataFrame([asdict(r) for r in results])
    df.drop(columns=["trade_pnls"], errors="ignore").to_csv(csv_path, index=False)
    log.info("csv_written", path=str(csv_path))

    # Write HTML
    html_path = out_dir / "edge_report.html"
    write_html_report(
        [r for r in results if r.params == BASE_PARAMS],
        args.symbol, args.timeframe, html_path
    )

    avg_sharpe = np.mean([r.sharpe for r in results if r.params == BASE_PARAMS])
    log.info("backtest_complete",
             avg_sharpe=round(float(avg_sharpe), 3),
             total_folds=len(results))

    if avg_sharpe < 1.0:
        log.warning("sharpe_below_1", sharpe=round(float(avg_sharpe), 3))


if __name__ == "__main__":
    main()
