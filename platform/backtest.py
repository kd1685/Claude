"""
backtest.py — honest backtest harness for Indicator Lab configs.

Replays the user's exact panel configuration (enabled indicators + weights)
bar-by-bar over daily candles and simulates a simple threshold strategy:

    panel score >= long_th  -> LONG
    panel score <= short_th -> SHORT if allow_short else FLAT
    otherwise               -> keep the previous position

Honesty rules (non-negotiable — they're the product's whole credibility):
  * Calls the SAME indicators.compute_panel the live Signal Panel uses
    (volumes=None, identical code path), on data up to each bar only —
    no lookahead: the signal at bar t earns the t -> t+1 return.
  * Fees charged on every position change (default 0.10% per side).
  * Always benchmarked against the validated EMA30 daily-trend baseline
    AND buy & hold on the same window.
  * Results carry the guardrail note: the 40-coin out-of-sample study found
    indicator scalping has NO fee-beating edge. This tool exists so users can
    verify that for themselves — never to promise profits.
"""

import math

import indicators

FEE_DEFAULT = 0.0010          # 0.10% per side — matches app.py FEE
MIN_HISTORY = 120             # warm-up bars before the first signal
MAX_BARS = 365
MIN_BARS = 60


def run(candles: list, enabled=None, weights=None, long_th: float = 6.0,
        short_th: float = 4.0, bars: int = 250, allow_short: bool = False,
        fee: float = FEE_DEFAULT) -> dict:
    """Backtest one config on one symbol's daily candles. Returns a dict with
    equity curves + stats, or {"error": ...} when there isn't enough data."""
    bars = max(MIN_BARS, min(int(bars or 250), MAX_BARS))
    long_th = _clamp(long_th, 5.0, 10.0, 6.0)
    short_th = _clamp(short_th, 0.0, 5.0, 4.0)

    candles = candles or []
    if len(candles) < MIN_HISTORY + MIN_BARS:
        return {"error": f"Need at least {MIN_HISTORY + MIN_BARS} daily candles "
                         f"({len(candles)} available)."}
    window = min(bars, len(candles) - MIN_HISTORY)
    start = len(candles) - window                 # first signal bar index

    closes = [c["close"] for c in candles]

    # ── Panel score at every bar (same code path as the live panel) ──────────
    scores = []
    for t in range(start, len(candles)):
        try:
            p = indicators.compute_panel(candles[:t + 1], volumes=None,
                                         enabled=enabled, weights=weights)
            scores.append(p["score"])
        except Exception:
            scores.append(5.0)                    # neutral on any failure

    # ── EMA30 baseline positions on the same window (long above, flat below) ─
    ema30 = _ema(closes, 30)
    off = len(closes) - len(ema30)                # ema30[i] pairs with closes[off+i]

    # ── Simulate ──────────────────────────────────────────────────────────────
    strat = _simulate(candles, start, lambda i: _panel_pos(scores[i], long_th, short_th, allow_short), fee)
    base = _simulate(candles, start, lambda i: 1 if closes[start + i] > ema30[start + i - off] else 0, fee)
    bh = _simulate(candles, start, lambda i: 1, fee=0.0)

    return {
        "bars": window,
        "from": candles[start]["time"], "to": candles[-1]["time"],
        "config": {"long_th": long_th, "short_th": short_th,
                   "allow_short": bool(allow_short), "fee_pct": fee * 100,
                   "indicators": len([k for k in (enabled or []) ])},
        "strategy": strat, "baseline": base, "buyhold": bh,
        "note": ("Honest numbers: fees included, no lookahead, same panel code as the live UI. "
                 "Reminder — our 40-coin out-of-sample study found indicator scalping has NO "
                 "fee-beating edge; the validated edge is the EMA30 daily trend (baseline). "
                 "Past results are not future returns."),
    }


# ─── Internals ─────────────────────────────────────────────────────────────────

def _panel_pos(score, long_th, short_th, allow_short):
    if score >= long_th:
        return 1
    if score <= short_th:
        return -1 if allow_short else 0
    return None                                   # carry previous position


def _simulate(candles, start, pos_fn, fee):
    """pos_fn(i) -> 1 / 0 / -1 / None(carry) for window index i.
    Signal at bar (start+i) earns the (start+i) -> (start+i+1) return."""
    closes = [c["close"] for c in candles]
    equity = 1.0
    curve = [{"time": candles[start]["time"], "value": 1.0}]
    pos = 0
    fees_paid = 0.0
    trades = 0
    wins = 0
    entry_equity = None
    peak = 1.0
    maxdd = 0.0

    n = len(closes) - 1
    for t in range(start, n):
        i = t - start
        want = pos_fn(i)
        if want is None:
            want = pos
        if want != pos:
            cost = abs(want - pos) * fee          # 0→1 one side; 1→-1 two sides
            equity *= (1 - cost)
            fees_paid += cost
            if pos != 0:                          # closing a trade
                trades += 1
                if entry_equity and equity > entry_equity:
                    wins += 1
            entry_equity = equity if want != 0 else None
            pos = want
        r = closes[t + 1] / closes[t] - 1.0
        equity *= (1 + pos * r)
        peak = max(peak, equity)
        maxdd = max(maxdd, 1 - equity / peak)
        curve.append({"time": candles[t + 1]["time"], "value": round(equity, 6)})

    if pos != 0:                                  # close the final open trade
        trades += 1
        if entry_equity and equity > entry_equity:
            wins += 1

    days = max(1, n - start)
    cagr = (equity ** (365.0 / days) - 1) * 100 if equity > 0 else -100.0
    return {
        "equity": curve,
        "stats": {
            "final_x": round(equity, 3),
            "cagr": round(cagr, 1),
            "maxdd": round(maxdd * 100, 1),
            "trades": trades,
            "win_rate": round(wins / trades * 100, 1) if trades else None,
            "fees_pct": round(fees_paid * 100, 2),
        },
    }


def _ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v)) if math.isfinite(v) else default
