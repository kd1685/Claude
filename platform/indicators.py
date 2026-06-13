"""
indicators.py — self-contained technical-indicator library for AscentTerminal.

- Pure python stdlib (math, random for the self-test). NO third-party imports.
- All functions take plain python lists.  Candles are dicts shaped:
      {"time": ..., "open": float, "high": float, "low": float, "close": float}
  Volume is passed as a separate `volumes` list where needed and may be
  missing/empty — volume indicators then return a neutral result.
- Series-returning functions (ema, sma) return a list aligned to the input,
  head-padded with None.  Everything else returns a latest-value float/dict,
  or None / a neutral dict when there is not enough data.
- Every public function tolerates short/empty input without raising.
"""

import math

# ============================================================================
# Internal helpers
# ============================================================================


def _closes(candles):
    return [c["close"] for c in candles]


def _highs(candles):
    return [c["high"] for c in candles]


def _lows(candles):
    return [c["low"] for c in candles]


def _ema_series(values, p):
    """EMA series aligned to input; first p-1 entries are None (SMA seed)."""
    n = len(values)
    if p <= 0 or n < p:
        return [None] * n
    out = [None] * (p - 1)
    prev = sum(values[:p]) / p
    out.append(prev)
    k = 2.0 / (p + 1)
    for x in values[p:]:
        prev = (x - prev) * k + prev
        out.append(prev)
    return out


def _ema_all(values, p):
    """EMA seeded on the first value — used for double-smoothed oscillators
    (TSI) where we want a value at every index."""
    if not values:
        return []
    k = 2.0 / (p + 1)
    prev = values[0]
    out = [prev]
    for x in values[1:]:
        prev = (x - prev) * k + prev
        out.append(prev)
    return out


def _sma_series(values, p):
    n = len(values)
    if p <= 0 or n < p:
        return [None] * n
    out = [None] * (p - 1)
    s = sum(values[:p])
    out.append(s / p)
    for i in range(p, n):
        s += values[i] - values[i - p]
        out.append(s / p)
    return out


def _stdev(values):
    """Population standard deviation."""
    n = len(values)
    if n == 0:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((x - m) ** 2 for x in values) / n)


def _true_ranges(candles):
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c["high"] - c["low"])
        else:
            pc = candles[i - 1]["close"]
            trs.append(max(c["high"] - c["low"],
                           abs(c["high"] - pc),
                           abs(c["low"] - pc)))
    return trs


def _atr_series(candles, p):
    """Wilder-smoothed ATR series aligned to candles; head padded with None."""
    n = len(candles)
    if n < p + 1 or p <= 0:
        return [None] * n
    trs = _true_ranges(candles)
    out = [None] * p
    prev = sum(trs[1:p + 1]) / p  # skip the first TR (no prev close)
    out.append(prev)
    for i in range(p + 1, n):
        prev = (prev * (p - 1) + trs[i]) / p
        out.append(prev)
    return out


def _rsi_series(closes, p):
    """Wilder RSI series aligned to closes; head padded with None."""
    n = len(closes)
    if n < p + 1 or p <= 0:
        return [None] * n
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    out = [None] * p
    ag = sum(gains[:p]) / p
    al = sum(losses[:p]) / p
    out.append(100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al))
    for i in range(p, n - 1):
        ag = (ag * (p - 1) + gains[i]) / p
        al = (al * (p - 1) + losses[i]) / p
        out.append(100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al))
    return out


def _linreg_slope(values):
    """Least-squares slope of values vs index 0..n-1."""
    n = len(values)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(values) / n
    num = sum((i - mx) * (v - my) for i, v in enumerate(values))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def _have_volume(volumes, n_needed=1):
    return bool(volumes) and len(volumes) >= n_needed and any(v for v in volumes)


# ============================================================================
# TREND
# ============================================================================


def ema(closes, p):
    """Exponential moving average — full series, head padded with None."""
    return _ema_series(closes or [], p)


def sma(closes, p):
    """Simple moving average — full series, head padded with None."""
    return _sma_series(closes or [], p)


def supertrend(candles, period=10, mult=3):
    """Supertrend -> {"trend": "UP"/"DOWN", "line": float} or None."""
    n = len(candles or [])
    atrs = _atr_series(candles or [], period)
    if n < period + 2 or atrs[-1] is None:
        return None
    closes = _closes(candles)
    trend = "UP"
    fu = fl = None  # final upper / lower bands
    line = None
    for i in range(period, n):
        a = atrs[i]
        if a is None:
            continue
        mid = (candles[i]["high"] + candles[i]["low"]) / 2.0
        bu = mid + mult * a  # basic upper
        bl = mid - mult * a  # basic lower
        if fu is None:
            fu, fl = bu, bl
        else:
            fu = bu if (bu < fu or closes[i - 1] > fu) else fu
            fl = bl if (bl > fl or closes[i - 1] < fl) else fl
        if trend == "UP" and closes[i] < fl:
            trend = "DOWN"
        elif trend == "DOWN" and closes[i] > fu:
            trend = "UP"
        line = fl if trend == "UP" else fu
    if line is None:
        return None
    return {"trend": trend, "line": line}


def _mid_hl(candles):
    return (max(_highs(candles)) + min(_lows(candles))) / 2.0


def ichimoku(candles):
    """Ichimoku -> {"tenkan","kijun","senkou_a","senkou_b","cloud"} or None.

    Cloud status compares the last close against the cloud as plotted at the
    current bar (spans computed 26 bars ago) when enough history exists,
    otherwise against the freshly computed spans."""
    n = len(candles or [])
    if n < 52:
        return None
    tenkan = _mid_hl(candles[-9:])
    kijun = _mid_hl(candles[-26:])
    senkou_a = (tenkan + kijun) / 2.0
    senkou_b = _mid_hl(candles[-52:])
    if n >= 78:  # spans projected 26 bars forward => use data ending 26 ago
        past = candles[:-26]
        sa = (_mid_hl(past[-9:]) + _mid_hl(past[-26:])) / 2.0
        sb = _mid_hl(past[-52:])
    else:
        sa, sb = senkou_a, senkou_b
    close = candles[-1]["close"]
    top, bot = max(sa, sb), min(sa, sb)
    cloud = "ABOVE" if close > top else ("BELOW" if close < bot else "IN")
    return {"tenkan": tenkan, "kijun": kijun,
            "senkou_a": senkou_a, "senkou_b": senkou_b, "cloud": cloud}


def golden_cross(closes):
    """EMA50/EMA200 cross -> {"state": "GOLDEN"/"DEATH"/"NONE","ema50","ema200"}.

    GOLDEN/DEATH only if the cross happened within the last 5 bars."""
    closes = closes or []
    e50 = _ema_series(closes, 50)
    e200 = _ema_series(closes, 200)
    out = {"state": "NONE",
           "ema50": e50[-1] if e50 and e50[-1] is not None else None,
           "ema200": e200[-1] if e200 and e200[-1] is not None else None}
    if out["ema50"] is None or out["ema200"] is None:
        return out
    # sign of (ema50 - ema200) over the last 6 valid bars
    diffs = [a - b for a, b in zip(e50, e200) if a is not None and b is not None]
    if len(diffs) < 2:
        return out
    recent = diffs[-6:]
    for i in range(1, len(recent)):
        if recent[i - 1] <= 0 < recent[i]:
            out["state"] = "GOLDEN"
        elif recent[i - 1] >= 0 > recent[i]:
            out["state"] = "DEATH"
    return out


def donchian(candles, p=20):
    """Donchian channel of the prior p bars -> {"upper","lower","breakout"}.

    breakout "UP"/"DOWN" if the last close pierces the prior-window channel."""
    n = len(candles or [])
    if n < p + 1:
        return None
    window = candles[-p - 1:-1]  # exclude current bar so a breakout is detectable
    upper = max(_highs(window))
    lower = min(_lows(window))
    close = candles[-1]["close"]
    breakout = "UP" if close > upper else ("DOWN" if close < lower else None)
    return {"upper": upper, "lower": lower, "breakout": breakout}


def structure(candles, lookback=20):
    """Market structure via swing points -> {"pattern": "HH-HL"/"LH-LL"/"MIXED"}.

    Swing = high/low strictly above/below the 2 neighbours on each side.
    Compares the last two swing highs and last two swing lows."""
    candles = candles or []
    window = candles[-lookback:]
    n = len(window)
    if n < 7:
        return {"pattern": "MIXED"}
    hs, ls = _highs(window), _lows(window)
    swing_hi, swing_lo = [], []
    for i in range(2, n - 2):
        if hs[i] > max(hs[i - 2], hs[i - 1], hs[i + 1], hs[i + 2]):
            swing_hi.append(hs[i])
        if ls[i] < min(ls[i - 2], ls[i - 1], ls[i + 1], ls[i + 2]):
            swing_lo.append(ls[i])
    if len(swing_hi) < 2 or len(swing_lo) < 2:
        return {"pattern": "MIXED"}
    hh = swing_hi[-1] > swing_hi[-2]
    hl = swing_lo[-1] > swing_lo[-2]
    if hh and hl:
        return {"pattern": "HH-HL"}
    if not hh and not hl:
        return {"pattern": "LH-LL"}
    return {"pattern": "MIXED"}


def pivots(candles):
    """Classic floor-trader pivots from the last candle -> {"p","r1","s1","r2","s2"}."""
    if not candles:
        return None
    c = candles[-1]
    h, l, cl = c["high"], c["low"], c["close"]
    p = (h + l + cl) / 3.0
    return {"p": p,
            "r1": 2 * p - l, "s1": 2 * p - h,
            "r2": p + (h - l), "s2": p - (h - l)}


# ============================================================================
# MOMENTUM
# ============================================================================


def rsi(closes, p=14):
    """Wilder RSI, latest value -> float or None."""
    series = _rsi_series(closes or [], p)
    return series[-1] if series else None


def stoch_rsi(closes, rsi_p=14, stoch_p=14, smooth=3):
    """Stochastic RSI (%K, SMA-smoothed) -> float 0-100 or None."""
    series = [v for v in _rsi_series(closes or [], rsi_p) if v is not None]
    if len(series) < stoch_p + smooth - 1:
        return None
    ks = []
    for i in range(stoch_p - 1, len(series)):
        win = series[i - stoch_p + 1:i + 1]
        hi, lo = max(win), min(win)
        ks.append(50.0 if hi == lo else (series[i] - lo) / (hi - lo) * 100.0)
    if len(ks) < smooth:
        return None
    return sum(ks[-smooth:]) / smooth


def williams_r(candles, p=14):
    """Williams %R -> float in [-100, 0] or None."""
    if len(candles or []) < p:
        return None
    win = candles[-p:]
    hi, lo = max(_highs(win)), min(_lows(win))
    if hi == lo:
        return -50.0
    return (hi - candles[-1]["close"]) / (hi - lo) * -100.0


def cci(candles, p=20):
    """Commodity Channel Index -> float or None."""
    if len(candles or []) < p:
        return None
    tps = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in candles[-p:]]
    m = sum(tps) / p
    md = sum(abs(t - m) for t in tps) / p
    if md == 0:
        return 0.0
    return (tps[-1] - m) / (0.015 * md)


def roc(closes, p=12):
    """Rate of change, percent -> float or None."""
    closes = closes or []
    if len(closes) < p + 1 or closes[-1 - p] == 0:
        return None
    return (closes[-1] - closes[-1 - p]) / closes[-1 - p] * 100.0


def tsi(closes, long_p=25, short_p=13):
    """True Strength Index -> float in [-100, 100] or None."""
    closes = closes or []
    if len(closes) < long_p + short_p:
        return None
    mom = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    num = _ema_all(_ema_all(mom, long_p), short_p)
    den = _ema_all(_ema_all([abs(m) for m in mom], long_p), short_p)
    if not den or den[-1] == 0:
        return 0.0
    return num[-1] / den[-1] * 100.0


def macd(closes, fast=12, slow=26, signal_p=9):
    """MACD -> {"macd","signal","hist"} or None."""
    closes = closes or []
    if len(closes) < slow + signal_p:
        return None
    ef = _ema_series(closes, fast)
    es = _ema_series(closes, slow)
    line = [a - b for a, b in zip(ef, es) if a is not None and b is not None]
    if len(line) < signal_p:
        return None
    sig = _ema_series(line, signal_p)[-1]
    if sig is None:
        return None
    return {"macd": line[-1], "signal": sig, "hist": line[-1] - sig}


# ============================================================================
# VOLATILITY
# ============================================================================


def atr(candles, p=14):
    """Wilder ATR, latest value -> float or None."""
    series = _atr_series(candles or [], p)
    return series[-1] if series else None


def bollinger(closes, p=20, mult=2):
    """Bollinger bands -> {"upper","mid","lower","pct_b","bandwidth"} or None."""
    closes = closes or []
    if len(closes) < p:
        return None
    win = closes[-p:]
    mid = sum(win) / p
    sd = _stdev(win)
    upper, lower = mid + mult * sd, mid - mult * sd
    width = upper - lower
    pct_b = 0.5 if width == 0 else (closes[-1] - lower) / width
    bandwidth = 0.0 if mid == 0 else width / mid
    return {"upper": upper, "mid": mid, "lower": lower,
            "pct_b": pct_b, "bandwidth": bandwidth}


def keltner(candles, p=20, mult=2):
    """Keltner channel (EMA mid, ATR bands) -> {"upper","mid","lower"} or None."""
    candles = candles or []
    if len(candles) < p + 1:
        return None
    mid = _ema_series(_closes(candles), p)[-1]
    a = _atr_series(candles, p)[-1]
    if mid is None or a is None:
        return None
    return {"upper": mid + mult * a, "mid": mid, "lower": mid - mult * a}


def squeeze(candles, p=20, bb_mult=2.0, kc_mult=1.5):
    """TTM-style squeeze -> {"on": bool}. on=True when BB sits inside Keltner."""
    candles = candles or []
    bb = bollinger(_closes(candles), p, bb_mult) if candles else None
    kc = keltner(candles, p, kc_mult)
    if bb is None or kc is None:
        return {"on": False}
    return {"on": bb["upper"] < kc["upper"] and bb["lower"] > kc["lower"]}


def hv_rank(closes, win=20, lookback=252):
    """Percentile rank (0-100) of current historical volatility (stdev of log
    returns over `win`) versus its own values over `lookback` bars. None if
    there is not enough data for at least 2 vol readings."""
    closes = closes or []
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) < win + 1:
        return None
    vols = [_stdev(rets[i - win + 1:i + 1]) for i in range(win - 1, len(rets))]
    vols = vols[-lookback:]
    if len(vols) < 2:
        return None
    cur = vols[-1]
    below = sum(1 for v in vols if v <= cur)
    return below / len(vols) * 100.0


# ============================================================================
# VOLUME  (all return a neutral result when volume data is absent)
# ============================================================================


def obv(closes, volumes):
    """On-balance volume -> {"value": float|None, "slope": float}.

    slope = least-squares slope of the last 10 OBV points (0.0 when neutral)."""
    closes = closes or []
    if not _have_volume(volumes, 2) or len(closes) < 2:
        return {"value": None, "slope": 0.0}
    n = min(len(closes), len(volumes))
    val = 0.0
    series = [0.0]
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            val += volumes[i]
        elif closes[i] < closes[i - 1]:
            val -= volumes[i]
        series.append(val)
    return {"value": val, "slope": _linreg_slope(series[-10:])}


def volume_surge(volumes, p=20):
    """Last volume vs its p-bar average -> {"ratio": float, "surge": bool}.

    surge=True when last volume >= 2x average. Neutral: ratio 1.0, no surge."""
    if not _have_volume(volumes, p + 1):
        return {"ratio": 1.0, "surge": False}
    avg = sum(volumes[-p - 1:-1]) / p
    if avg <= 0:
        return {"ratio": 1.0, "surge": False}
    ratio = volumes[-1] / avg
    return {"ratio": ratio, "surge": ratio >= 2.0}


def cmf(candles, volumes, p=20):
    """Chaikin Money Flow -> float in [-1, 1]; 0.0 when volume is absent."""
    candles = candles or []
    if not _have_volume(volumes, p) or len(candles) < p:
        return 0.0
    n = min(len(candles), len(volumes))
    mfv = vol = 0.0
    for i in range(n - p, n):
        c = candles[i]
        rng = c["high"] - c["low"]
        mult = 0.0 if rng == 0 else ((c["close"] - c["low"]) - (c["high"] - c["close"])) / rng
        mfv += mult * volumes[i]
        vol += volumes[i]
    return 0.0 if vol == 0 else mfv / vol


def adl(candles, volumes):
    """Accumulation/Distribution line -> {"value": float|None, "slope": float}."""
    candles = candles or []
    if not _have_volume(volumes, 2) or len(candles) < 2:
        return {"value": None, "slope": 0.0}
    n = min(len(candles), len(volumes))
    val = 0.0
    series = []
    for i in range(n):
        c = candles[i]
        rng = c["high"] - c["low"]
        mult = 0.0 if rng == 0 else ((c["close"] - c["low"]) - (c["high"] - c["close"])) / rng
        val += mult * volumes[i]
        series.append(val)
    return {"value": val, "slope": _linreg_slope(series[-10:])}


def mfi(candles, volumes, p=14):
    """Money Flow Index -> float 0-100; 50.0 (neutral) when volume is absent."""
    candles = candles or []
    if not _have_volume(volumes, p + 1) or len(candles) < p + 1:
        return 50.0
    n = min(len(candles), len(volumes))
    pos = neg = 0.0
    prev_tp = None
    for i in range(n - p - 1, n):
        c = candles[i]
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        if prev_tp is not None:
            flow = tp * volumes[i]
            if tp > prev_tp:
                pos += flow
            elif tp < prev_tp:
                neg += flow
        prev_tp = tp
    if neg == 0:
        return 100.0 if pos > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + pos / neg)


# ============================================================================
# PATTERNS (last 1-3 candles)
# ============================================================================

BULLISH_PATTERNS = {"hammer", "bullish_engulfing"}
BEARISH_PATTERNS = {"shooting_star", "bearish_engulfing"}


def candle_patterns(candles):
    """Detect simple candle patterns on the last 1-3 candles -> list of names.

    Possible names: doji, hammer, shooting_star, bullish_engulfing,
    bearish_engulfing, inside_bar, pin_bar, three_bar_reversal."""
    candles = candles or []
    found = []
    if not candles:
        return found
    c = candles[-1]
    o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
    rng = h - l
    body = abs(cl - o)
    upper = h - max(o, cl)
    lower = min(o, cl) - l

    if rng > 0:
        # doji: tiny body relative to range
        if body <= 0.1 * rng:
            found.append("doji")
        # hammer: long lower wick, small upper wick, body in upper part
        if lower >= 2 * body and upper <= body and body > 0:
            found.append("hammer")
        # shooting star: long upper wick, small lower wick
        if upper >= 2 * body and lower <= body and body > 0:
            found.append("shooting_star")
        # pin bar: one wick dominates (>= 2/3 of range), small body
        if body <= rng / 3.0 and (upper >= 2 * rng / 3.0 or lower >= 2 * rng / 3.0):
            found.append("pin_bar")

    if len(candles) >= 2:
        p = candles[-2]
        po, pc = p["open"], p["close"]
        # engulfing: current body fully covers previous body, opposite colors
        if pc < po and cl > o and cl >= po and o <= pc and body > abs(pc - po):
            found.append("bullish_engulfing")
        if pc > po and cl < o and cl <= po and o >= pc and body > abs(pc - po):
            found.append("bearish_engulfing")
        # inside bar: current range fully inside previous range
        if h < p["high"] and l > p["low"]:
            found.append("inside_bar")

    if len(candles) >= 3:
        a, b = candles[-3], candles[-2]
        # bullish 3-bar reversal: down bar, lower low, then close above bar2 high
        if a["close"] < a["open"] and b["low"] < a["low"] and cl > b["high"]:
            found.append("three_bar_reversal")
        # bearish 3-bar reversal: up bar, higher high, then close below bar2 low
        elif a["close"] > a["open"] and b["high"] > a["high"] and cl < b["low"]:
            found.append("three_bar_reversal")

    return found


# ============================================================================
# REGISTRY — powers the toggleable indicator UI
# ============================================================================

REGISTRY = {
    # --- trend ---
    "ema":            {"label": "EMA 20",            "group": "trend",      "default_on": False},
    "sma":            {"label": "SMA 50",            "group": "trend",      "default_on": False},
    "supertrend":     {"label": "Supertrend",        "group": "trend",      "default_on": True},
    "ichimoku":       {"label": "Ichimoku Cloud",    "group": "trend",      "default_on": False},
    "golden_cross":   {"label": "EMA 50/200 Cross",  "group": "trend",      "default_on": True},
    "donchian":       {"label": "Donchian Channel",  "group": "trend",      "default_on": False},
    "structure":      {"label": "Market Structure",  "group": "trend",      "default_on": False},
    "pivots":         {"label": "Pivot Points",      "group": "trend",      "default_on": False},
    # --- momentum ---
    "rsi":            {"label": "RSI 14",            "group": "momentum",   "default_on": True},
    "stoch_rsi":      {"label": "Stochastic RSI",    "group": "momentum",   "default_on": False},
    "williams_r":     {"label": "Williams %R",       "group": "momentum",   "default_on": False},
    "cci":            {"label": "CCI 20",            "group": "momentum",   "default_on": False},
    "roc":            {"label": "Rate of Change",    "group": "momentum",   "default_on": False},
    "tsi":            {"label": "True Strength Idx", "group": "momentum",   "default_on": False},
    "macd":           {"label": "MACD",              "group": "momentum",   "default_on": True},
    # --- volatility ---
    "atr":            {"label": "ATR 14",            "group": "volatility", "default_on": False},
    "bollinger":      {"label": "Bollinger Bands",   "group": "volatility", "default_on": True},
    "keltner":        {"label": "Keltner Channel",   "group": "volatility", "default_on": False},
    "squeeze":        {"label": "TTM Squeeze",       "group": "volatility", "default_on": False},
    "hv_rank":        {"label": "HV Rank",           "group": "volatility", "default_on": False},
    # --- volume ---
    "obv":            {"label": "On-Balance Volume", "group": "volume",     "default_on": False},
    "volume_surge":   {"label": "Volume Surge",      "group": "volume",     "default_on": True},
    "cmf":            {"label": "Chaikin Money Flow","group": "volume",     "default_on": False},
    "adl":            {"label": "Accum/Dist Line",   "group": "volume",     "default_on": False},
    "mfi":            {"label": "Money Flow Index",  "group": "volume",     "default_on": False},
    # --- patterns ---
    "candle_patterns": {"label": "Candle Patterns",  "group": "pattern",    "default_on": False},
}


# --- per-indicator compute + vote rules -------------------------------------
# Each entry computes the latest value and converts it into a vote.
# Vote rules (documented inline below):
#   ema            close > EMA20  -> BULL, below -> BEAR
#   sma            close > SMA50  -> BULL, below -> BEAR
#   supertrend     trend UP -> BULL, DOWN -> BEAR
#   ichimoku       price ABOVE cloud -> BULL, BELOW -> BEAR, IN -> NEUTRAL
#   golden_cross   GOLDEN -> BULL, DEATH -> BEAR, NONE -> NEUTRAL
#   donchian       breakout UP -> BULL, DOWN -> BEAR, else NEUTRAL
#   structure      HH-HL -> BULL, LH-LL -> BEAR, MIXED -> NEUTRAL
#   pivots         close above pivot P -> BULL, below -> BEAR
#   rsi            > 55 -> BULL, < 45 -> BEAR, else NEUTRAL
#   stoch_rsi      < 20 (oversold, mean-reversion) -> BULL, > 80 -> BEAR
#   williams_r     < -80 (oversold) -> BULL, > -20 (overbought) -> BEAR
#   cci            > +100 -> BULL, < -100 -> BEAR (trend-strength reading)
#   roc            > +0.5% -> BULL, < -0.5% -> BEAR (small dead zone)
#   tsi            > 0 -> BULL, < 0 -> BEAR
#   macd           histogram > 0 -> BULL, < 0 -> BEAR
#   atr            context only -> always NEUTRAL
#   bollinger      mean-reversion: %B <= 0.2 -> BULL, >= 0.8 -> BEAR
#   keltner        breakout: close > upper -> BULL, close < lower -> BEAR
#   squeeze        context only -> always NEUTRAL
#   hv_rank        context only -> always NEUTRAL
#   obv            OBV slope > 0 -> BULL, < 0 -> BEAR
#   volume_surge   surge on an up candle -> BULL, on a down candle -> BEAR
#   cmf            > +0.05 -> BULL, < -0.05 -> BEAR
#   adl            ADL slope > 0 -> BULL, < 0 -> BEAR
#   mfi            > 60 -> BULL, < 40 -> BEAR
#   candle_patterns  majority of bullish vs bearish pattern names wins;
#                    neutral names (doji, inside_bar, pin_bar,
#                    three_bar_reversal) do not vote


def _vote_thresh(v, hi, lo, invert=False):
    if v is None:
        return "NEUTRAL"
    if invert:
        return "BULL" if v < lo else ("BEAR" if v > hi else "NEUTRAL")
    return "BULL" if v > hi else ("BEAR" if v < lo else "NEUTRAL")


def _signal(key, candles, closes, volumes):
    """Compute (value, vote) for one registry key."""
    last = closes[-1] if closes else None

    if key == "ema":
        v = _ema_series(closes, 20)[-1] if closes else None
        if v is None or last is None:
            return v, "NEUTRAL"
        return v, "BULL" if last > v else ("BEAR" if last < v else "NEUTRAL")

    if key == "sma":
        v = _sma_series(closes, 50)[-1] if closes else None
        if v is None or last is None:
            return v, "NEUTRAL"
        return v, "BULL" if last > v else ("BEAR" if last < v else "NEUTRAL")

    if key == "supertrend":
        v = supertrend(candles)
        if v is None:
            return None, "NEUTRAL"
        return v, "BULL" if v["trend"] == "UP" else "BEAR"

    if key == "ichimoku":
        v = ichimoku(candles)
        if v is None:
            return None, "NEUTRAL"
        return v, {"ABOVE": "BULL", "BELOW": "BEAR"}.get(v["cloud"], "NEUTRAL")

    if key == "golden_cross":
        v = golden_cross(closes)
        return v, {"GOLDEN": "BULL", "DEATH": "BEAR"}.get(v["state"], "NEUTRAL")

    if key == "donchian":
        v = donchian(candles)
        if v is None:
            return None, "NEUTRAL"
        return v, {"UP": "BULL", "DOWN": "BEAR"}.get(v["breakout"], "NEUTRAL")

    if key == "structure":
        v = structure(candles)
        return v, {"HH-HL": "BULL", "LH-LL": "BEAR"}.get(v["pattern"], "NEUTRAL")

    if key == "pivots":
        v = pivots(candles)
        if v is None or last is None:
            return v, "NEUTRAL"
        return v, "BULL" if last > v["p"] else ("BEAR" if last < v["p"] else "NEUTRAL")

    if key == "rsi":
        v = rsi(closes)
        return v, _vote_thresh(v, 55, 45)

    if key == "stoch_rsi":
        v = stoch_rsi(closes)
        return v, _vote_thresh(v, 80, 20, invert=True)

    if key == "williams_r":
        v = williams_r(candles)
        return v, _vote_thresh(v, -20, -80, invert=True)

    if key == "cci":
        v = cci(candles)
        return v, _vote_thresh(v, 100, -100)

    if key == "roc":
        v = roc(closes)
        return v, _vote_thresh(v, 0.5, -0.5)

    if key == "tsi":
        v = tsi(closes)
        return v, _vote_thresh(v, 0, 0)

    if key == "macd":
        v = macd(closes)
        if v is None:
            return None, "NEUTRAL"
        return v, _vote_thresh(v["hist"], 0, 0)

    if key == "atr":
        return atr(candles), "NEUTRAL"  # volatility context only

    if key == "bollinger":
        v = bollinger(closes)
        if v is None:
            return None, "NEUTRAL"
        return v, _vote_thresh(v["pct_b"], 0.8, 0.2, invert=True)

    if key == "keltner":
        v = keltner(candles)
        if v is None or last is None:
            return v, "NEUTRAL"
        vote = "BULL" if last > v["upper"] else ("BEAR" if last < v["lower"] else "NEUTRAL")
        return v, vote

    if key == "squeeze":
        return squeeze(candles), "NEUTRAL"  # context only

    if key == "hv_rank":
        return hv_rank(closes), "NEUTRAL"  # context only

    if key == "obv":
        v = obv(closes, volumes)
        return v, _vote_thresh(v["slope"], 0, 0)

    if key == "volume_surge":
        v = volume_surge(volumes)
        if v["surge"] and candles:
            up = candles[-1]["close"] >= candles[-1]["open"]
            return v, "BULL" if up else "BEAR"
        return v, "NEUTRAL"

    if key == "cmf":
        v = cmf(candles, volumes)
        return v, _vote_thresh(v, 0.05, -0.05)

    if key == "adl":
        v = adl(candles, volumes)
        return v, _vote_thresh(v["slope"], 0, 0)

    if key == "mfi":
        v = mfi(candles, volumes)
        return v, _vote_thresh(v, 60, 40)

    if key == "candle_patterns":
        v = candle_patterns(candles)
        bull = sum(1 for name in v if name in BULLISH_PATTERNS)
        bear = sum(1 for name in v if name in BEARISH_PATTERNS)
        vote = "BULL" if bull > bear else ("BEAR" if bear > bull else "NEUTRAL")
        return v, vote

    return None, "NEUTRAL"


def compute_panel(candles, volumes=None, enabled=None, weights=None):
    """Run the enabled indicators and aggregate a composite signal.

    Returns:
        {"signals": {key: {"value": ..., "vote": "BULL"/"BEAR"/"NEUTRAL"}},
         "score": float 0-10,
         "direction": "LONG"/"SHORT"/"NEUTRAL",
         "votes": {"bull": n, "bear": n, "neutral": n}}

    Score = weighted bull fraction * 10, where NEUTRAL votes count as half
    a bull (so an all-neutral panel scores 5.0 instead of 0).
    Direction: score >= 6 -> LONG, score <= 4 -> SHORT, else NEUTRAL.
    """
    candles = candles or []
    volumes = volumes or []
    weights = weights or {}
    if enabled is None:
        enabled = [k for k, meta in REGISTRY.items() if meta["default_on"]]
    closes = _closes(candles)

    signals = {}
    bull_w = bear_w = neutral_w = total_w = 0.0
    votes = {"bull": 0, "bear": 0, "neutral": 0}

    for key in enabled:
        if key not in REGISTRY:
            continue
        # Skip indicators the user weighted to 0 — never spend CPU/API on
        # inactive metrics (the scalper runs this every scan across a watchlist).
        w = float(weights.get(key, 1.0))
        if w <= 0:
            continue
        try:
            value, vote = _signal(key, candles, closes, volumes)
        except Exception:  # belt-and-braces: a bad indicator never sinks the panel
            value, vote = None, "NEUTRAL"
        signals[key] = {"value": value, "vote": vote}
        total_w += w
        if vote == "BULL":
            bull_w += w
            votes["bull"] += 1
        elif vote == "BEAR":
            bear_w += w
            votes["bear"] += 1
        else:
            neutral_w += w
            votes["neutral"] += 1

    score = 5.0 if total_w == 0 else (bull_w + 0.5 * neutral_w) / total_w * 10.0
    direction = "LONG" if score >= 6.0 else ("SHORT" if score <= 4.0 else "NEUTRAL")
    return {"signals": signals, "score": round(score, 2),
            "direction": direction, "votes": votes}


# ============================================================================
# Self-test
# ============================================================================

if __name__ == "__main__":
    import random

    random.seed(42)

    def make_candles(n=300, start=100.0, drift=0.05):
        out, vols, price = [], [], start
        for i in range(n):
            o = price
            move = random.gauss(drift, 1.2)
            c = max(1.0, o + move)
            h = max(o, c) + abs(random.gauss(0, 0.5))
            l = max(0.5, min(o, c) - abs(random.gauss(0, 0.5)))
            out.append({"time": i, "open": o, "high": h, "low": l, "close": c})
            vols.append(max(1.0, random.gauss(1000, 250)))
            price = c
        return out, vols

    candles, vols = make_candles(300)
    closes = _closes(candles)
    shorty = candles[:3]              # short-input safety check
    short_closes = _closes(shorty)

    # --- trend ---
    assert len(ema(closes, 20)) == 300 and ema(closes, 20)[-1] is not None
    assert len(sma(closes, 50)) == 300 and sma(closes, 50)[18] is None
    st = supertrend(candles); assert st["trend"] in ("UP", "DOWN")
    ich = ichimoku(candles); assert ich["cloud"] in ("ABOVE", "BELOW", "IN")
    gc = golden_cross(closes); assert gc["state"] in ("GOLDEN", "DEATH", "NONE")
    dc = donchian(candles); assert dc["breakout"] in ("UP", "DOWN", None)
    stx = structure(candles); assert stx["pattern"] in ("HH-HL", "LH-LL", "MIXED")
    pv = pivots(candles); assert pv["r1"] >= pv["p"] >= pv["s1"]
    for f in (lambda: ema(short_closes, 20), lambda: sma(short_closes, 50),
              lambda: supertrend(shorty), lambda: ichimoku(shorty),
              lambda: golden_cross(short_closes), lambda: donchian(shorty),
              lambda: structure(shorty), lambda: pivots([])):
        f()  # must not raise
    print("TREND OK")

    # --- momentum ---
    assert 0 <= rsi(closes) <= 100
    assert 0 <= stoch_rsi(closes) <= 100
    assert -100 <= williams_r(candles) <= 0
    assert cci(candles) is not None
    assert roc(closes) is not None
    assert -100 <= tsi(closes) <= 100
    m = macd(closes); assert abs(m["macd"] - m["signal"] - m["hist"]) < 1e-9
    for f in (lambda: rsi(short_closes), lambda: stoch_rsi(short_closes),
              lambda: williams_r(shorty), lambda: cci(shorty),
              lambda: roc(short_closes), lambda: tsi(short_closes),
              lambda: macd(short_closes)):
        assert f() is None
    print("MOMENTUM OK")

    # --- volatility ---
    assert atr(candles) > 0
    bb = bollinger(closes); assert bb["lower"] < bb["mid"] < bb["upper"]
    kc = keltner(candles); assert kc["lower"] < kc["mid"] < kc["upper"]
    sq = squeeze(candles); assert isinstance(sq["on"], bool)
    hv = hv_rank(closes); assert 0 <= hv <= 100
    assert atr(shorty) is None and bollinger(short_closes) is None
    assert keltner(shorty) is None and squeeze(shorty) == {"on": False}
    assert hv_rank(short_closes) is None
    print("VOLATILITY OK")

    # --- volume ---
    ob = obv(closes, vols); assert ob["value"] is not None
    vs = volume_surge(vols); assert vs["ratio"] > 0
    assert -1 <= cmf(candles, vols) <= 1
    ad = adl(candles, vols); assert ad["value"] is not None
    assert 0 <= mfi(candles, vols) <= 100
    # graceful behavior with missing volume
    assert obv(closes, None) == {"value": None, "slope": 0.0}
    assert volume_surge([]) == {"ratio": 1.0, "surge": False}
    assert cmf(candles, []) == 0.0
    assert adl(candles, None)["slope"] == 0.0
    assert mfi(candles, []) == 50.0
    print("VOLUME OK")

    # --- patterns ---
    pats = candle_patterns(candles)
    assert isinstance(pats, list)
    assert candle_patterns([]) == []
    # synthetic bullish engulfing must be detected
    eng = [{"time": 0, "open": 10, "high": 10.5, "low": 9.4, "close": 9.5},
           {"time": 1, "open": 9.4, "high": 11.2, "low": 9.3, "close": 11.0}]
    assert "bullish_engulfing" in candle_patterns(eng)
    print("PATTERN OK")

    # --- registry / panel ---
    assert all(meta["group"] in ("trend", "momentum", "volatility", "volume", "pattern")
               for meta in REGISTRY.values())
    panel = compute_panel(candles, vols, enabled=list(REGISTRY.keys()))
    assert set(panel["signals"]) == set(REGISTRY)
    assert 0 <= panel["score"] <= 10
    assert panel["direction"] in ("LONG", "SHORT", "NEUTRAL")
    assert sum(panel["votes"].values()) == len(REGISTRY)
    # defaults-only run, weighted run, and short-input run
    dflt = compute_panel(candles, vols)
    assert set(dflt["signals"]) == {k for k, m in REGISTRY.items() if m["default_on"]}
    compute_panel(candles, vols, weights={"rsi": 2.5, "macd": 0.5})
    empty = compute_panel([], None, enabled=list(REGISTRY.keys()))
    assert empty["direction"] == "NEUTRAL" and empty["score"] == 5.0
    print("PANEL OK  (%d indicators, score=%.2f, dir=%s, votes=%s)"
          % (len(REGISTRY), panel["score"], panel["direction"], panel["votes"]))
