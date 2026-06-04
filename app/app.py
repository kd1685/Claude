"""
HermesBot — MEXC Futures Scalper  v4.0
Multi-trade · Hedging · Persistent positions bar · Clean UI

Run:      python app.py
Requires: pip install anthropic matplotlib
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading, time, json, os, hmac, hashlib, uuid
import urllib.request, urllib.parse
from http.client import IncompleteRead
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
import pathlib

# ── Paths ──────────────────────────────────────────────────────────────────────
_HOME = pathlib.Path.home() / "HermesBot"
_HOME.mkdir(exist_ok=True)
STATE_FILE = str(_HOME / "hermesbot_state.json")
KEYS_FILE  = str(_HOME / "hermesbot_keys.json")

# ── Optional deps ──────────────────────────────────────────────────────────────
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

import warnings
warnings.filterwarnings("ignore", message=".*tight_layout.*")

try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.gridspec import GridSpec
    MPLOT = True
except ImportError:
    MPLOT = False

# ══════════════════════════════════════════════════════════════════════════════
#  PALETTE
# ══════════════════════════════════════════════════════════════════════════════
BG    = "#0b0e15"
BG2   = "#13192a"
BG3   = "#1e2738"
BG4   = "#090c12"
SEP   = "#1e2d45"
SEP2  = "#263348"

GREEN  = "#00e676"
RED    = "#ff3d57"
BLUE   = "#4dabf7"
AMBER  = "#ffa94d"
PURPLE = "#cc5de8"
CYAN   = "#22d3ee"
YELLOW = "#ffd43b"
ORANGE = "#ff922b"
PINK   = "#f783ac"
TEAL   = "#20c997"

TEXT    = "#f1f3f5"
SUB     = "#adb5bd"
MUTED   = "#6c757d"
DIM     = "#495057"

C_UP   = "#00e676"
C_DOWN = "#ff3d57"
C_GRID = "#161d2e"
C_AX   = "#495057"

PAIR_COL = {
    "BTC_USDT":    "#ffa94d",
    "ETH_USDT":    "#4dabf7",
    "SOL_USDT":    "#cc5de8",
    "XRP_USDT":    "#22d3ee",
    "DOGE_USDT":   "#00e676",
    "PEPE_USDT":   "#ff6eb4",
    "XAU_USDT":    "#ffd700",
    "SUI_USDT":    "#4aeadc",
    "TESLA_USDT":  "#e74c3c",
}
PAIRS = list(PAIR_COL.keys())

# Human-readable short names for display
PAIR_DISPLAY = {
    "BTC_USDT":      "BTC",
    "ETH_USDT":      "ETH",
    "SOL_USDT":      "SOL",
    "XRP_USDT":      "XRP",
    "DOGE_USDT":     "DOGE",
    "PEPE_USDT":     "PEPE",
    "XAU_USDT":      "GOLD",
    "SUI_USDT":      "SUI",
    "TESLA_USDT":    "TESLA",
}

# Pairs excluded from live API trading (price precision / volume issues)
API_EXCLUDED = {"PEPE_USDT"}  # PEPE price has too many decimals for API

def pair_label(p):
    return PAIR_DISPLAY.get(p, p.replace("_USDT","").replace("1000",""))

# MEXC volume precision (decimal places) per pair
# Determined by MEXC contract specs — wrong precision = code 2015 rejection
# MEXC volume precision (volScale from API docs)
# volScale=0 means integer contracts. Vol is in CONTRACT UNITS not coin units.
# contractSize tells you what 1 contract = in coin terms.
# BTC: volScale=0, contractSize=0.0001 BTC → vol=1 means 0.0001 BTC
PAIR_VOL_PRECISION = {
    "BTC_USDT":    0,   # volScale=0 (integer contracts, contractSize=0.0001 BTC)
    "ETH_USDT":    0,   # volScale=0 (integer contracts)
    "SOL_USDT":    0,   # volScale=0 (integer contracts)
    "XRP_USDT":    0,   # volScale=0 (integer contracts)
    "DOGE_USDT":   0,   # volScale=0 (integer contracts)
    "PEPE_USDT":   0,   # volScale=0 (integer contracts)
    "XAU_USDT":    0,   # volScale=0 (integer contracts)
    "SUI_USDT":    0,   # volScale=0 (integer contracts)
    "TESLA_USDT":  0,   # volScale=0 (integer contracts)
}

# Contract sizes (how much 1 contract = in coin terms)
# Used to calculate correct number of contracts from margin
PAIR_CONTRACT_SIZE = {
    "BTC_USDT":   0.0001,   # 1 contract = 0.0001 BTC
    "ETH_USDT":   0.001,    # 1 contract = 0.001 ETH
    "SOL_USDT":   0.1,      # 1 contract = 0.1 SOL
    "XRP_USDT":   10,       # 1 contract = 10 XRP
    "DOGE_USDT":  100,      # 1 contract = 100 DOGE
    "PEPE_USDT":  1000000,  # 1 contract = 1M PEPE
    "XAU_USDT":   0.01,     # 1 contract = 0.01 XAU
    "SUI_USDT":   10,       # 1 contract = 10 SUI
    "TESLA_USDT": 0.01,     # 1 contract = 0.01 TSLA
}

# Auto-learn precision: if code 2015, retry with fewer decimals
_learned_precision = {}  # runtime-updated if orders fail or fetched from API

def fetch_contract_precision():
    """
    Query MEXC futures API for exact volume precision per pair.
    Tries multiple endpoints. Updates PAIR_VOL_PRECISION in place.
    """
    updated = []

    # Try 1: bulk contract list (no auth needed)
    try:
        d = mexc_public("/api/v1/contract/detail")  # contract.mexc.com base
        contracts = []
        if d.get("success"):
            data = d.get("data", [])
            # Response may be list or dict with list inside
            if isinstance(data, list):
                contracts = data
            elif isinstance(data, dict):
                contracts = data.get("list", data.get("data", []))

        for info in contracts:
            sym = info.get("symbol", "")
            if sym in PAIRS:
                vol_dp = info.get("volDecimalPlace")
                if vol_dp is not None:
                    PAIR_VOL_PRECISION[sym] = int(vol_dp)
                    updated.append(f"{sym.replace('_USDT','')}={vol_dp}dp")

        if updated:
            return updated
    except Exception:
        pass

    # Try 2: individual symbol queries
    for sym in PAIRS:
        try:
            for endpoint in [
                f"/api/v1/contract/detail?symbol={sym}",
                f"/api/v1/contract/{sym}",
            ]:
                try:
                    d = mexc_public(endpoint)
                    info = d.get("data", {})
                    if isinstance(info, list) and info:
                        info = info[0]
                    vol_dp = info.get("volScale", info.get("volDecimalPlace")) if isinstance(info, dict) else None
                    if vol_dp is not None:
                        PAIR_VOL_PRECISION[sym] = int(vol_dp)
                        updated.append(f"{sym.replace('_USDT','')}={vol_dp}dp")
                        break
                except Exception:
                    continue
        except Exception:
            pass

    return updated

def round_vol(symbol, vol):
    """Round volume to MEXC required precision. Uses learned values if available."""
    base_prec = PAIR_VOL_PRECISION.get(symbol, 2)
    learned   = _learned_precision.get(symbol, base_prec)
    prec      = min(base_prec, learned)
    if prec == 0:
        return max(1, int(round(vol, 0)))
    return max(round(vol, prec), 10**(-prec))


# Max leverage per pair (MEXC actual limits)
PAIR_MAX_LEV = {
    "BTC_USDT":    200,
    "ETH_USDT":    200,
    "SOL_USDT":    100,
    "XRP_USDT":    100,
    "DOGE_USDT":   100,
    "PEPE_USDT":    50,
    "XAU_USDT":    200,
    "SUI_USDT":     50,
    "TESLA_USDT":   50,
}

# Confidence threshold to allow stacking extra longs (score out of 5)
STACK_LONG_THRESH = 4.5

FM  = ("Consolas", 10)
FMS = ("Consolas", 9)
FMB = ("Consolas", 10, "bold")
FUI = ("Segoe UI", 10)

# ══════════════════════════════════════════════════════════════════════════════
#  DATA
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Position:
    id:          str
    symbol:      str
    direction:   str        # LONG / SHORT
    entry_price: float
    margin:      float
    leverage:    int
    size_usdt:   float
    stop_loss:   float
    take_profit: float
    liq_price:   float
    opened_at:   str
    hedge_of:    str = ""   # id of parent if this is a hedge leg
    order_id:    str = ""

@dataclass
class BotState:
    balance:      float = 1000.0
    total_pnl:    float = 0.0
    wins:         int   = 0
    losses:       int   = 0
    liqs:         int   = 0
    trades:       list  = field(default_factory=list)
    positions:    dict  = field(default_factory=dict)   # id -> Position

# ══════════════════════════════════════════════════════════════════════════════
#  MEXC API
# ══════════════════════════════════════════════════════════════════════════════
MEXC_BASE = "https://contract.mexc.com"

def mexc_public(path, params={}, timeout=10):
    url = MEXC_BASE + path
    if params: url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "HermesBot/4.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def mexc_private(method, path, params, key, secret, dry, timeout=12):
    if dry: return {"success": True, "data": f"DRY-{int(time.time())}"}
    ts   = str(int(time.time() * 1000))
    body = json.dumps(params) if params else ""
    sig  = hmac.new(secret.encode(), (key + ts + body).encode(), hashlib.sha256).hexdigest()
    req  = urllib.request.Request(
        MEXC_BASE + path, data=body.encode() if body else None,
        headers={"ApiKey": key, "Request-Time": ts, "Signature": sig,
                 "Content-Type": "application/json", "User-Agent": "HermesBot/4.0"},
        method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def get_live_account(key, secret):
    """Fetch MEXC futures account balance — tries all known endpoints."""
    errors = []

    def _parse_asset(data):
        """Try to extract equity/available from various response shapes."""
        if isinstance(data, list):
            # List of assets — find USDT
            usdt = next((a for a in data
                         if str(a.get("currency","")).upper() in ("USDT","USD")), None)
            if usdt:
                return {
                    "equity":     float(usdt.get("equity", usdt.get("accountEquity", 0))),
                    "available":  float(usdt.get("availableBalance",
                                                  usdt.get("availableFunds", 0))),
                    "unrealised": float(usdt.get("unrealisedProfit",
                                                  usdt.get("unrealizedPnl", 0))),
                    "realised":   float(usdt.get("realisedProfit",
                                                  usdt.get("realizedPnl", 0))),
                }
        elif isinstance(data, dict):
            # Single account object
            eq = (data.get("equity") or data.get("accountEquity") or
                  data.get("totalEquity") or data.get("balance") or 0)
            av = (data.get("availableBalance") or data.get("availableFunds") or
                  data.get("available") or 0)
            return {
                "equity":     float(eq),
                "available":  float(av),
                "unrealised": float(data.get("unrealisedProfit",
                                              data.get("unrealizedPnl", 0))),
                "realised":   float(data.get("realisedProfit",
                                              data.get("realizedPnl", 0))),
            }
        return None

    endpoints = [
        ("GET", "/api/v1/private/account/assets"),
        ("GET", "/api/v1/private/account/overview"),
        ("GET", "/api/v1/private/account/asset"),
        ("GET", "/api/v1/private/position/open_positions"),
    ]

    for method, path in endpoints:
        try:
            r = mexc_private(method, path, {}, key, secret, False)
            if r.get("success"):
                result = _parse_asset(r.get("data", {}))
                if result and result["equity"] > 0:
                    return result
                # Try success but equity=0 (account exists, just empty)
                if result:
                    return result
        except Exception as e:
            errors.append(f"{path}: {str(e)[:40]}")

    raise RuntimeError(f"All endpoints failed: {'; '.join(errors[:2])}")

def get_ticker(sym):
    r = mexc_public("/api/v1/contract/ticker", {"symbol": sym})
    if not r.get("success"): raise RuntimeError(f"Ticker: {r}")
    d = r["data"]
    return {"last": float(d.get("lastPrice", 0)), "funding": float(d.get("fundingRate", 0))}

def get_klines(sym, tf="Min5", limit=60, timeout=12):
    r = mexc_public("/api/v1/contract/kline/" + sym, {"interval": tf})
    if not r.get("success"): raise RuntimeError(f"Klines: {r}")
    d  = r["data"]
    cl = d.get("close",[]); op = d.get("open",[]); hi = d.get("high",[])
    lo = d.get("low",[]); vo = d.get("vol",[])
    out = []
    for i in range(len(cl)):
        out.append({"open":   float(op[i]) if i < len(op) else float(cl[i]),
                    "high":   float(hi[i]) if i < len(hi) else float(cl[i]),
                    "low":    float(lo[i]) if i < len(lo) else float(cl[i]),
                    "close":  float(cl[i]),
                    "volume": float(vo[i]) if i < len(vo) else 0})
    return out[-limit:]

# ══════════════════════════════════════════════════════════════════════════════
#  INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def ema(vals, p):
    k = 2 / (p + 1); r = [vals[0]]
    for v in vals[1:]: r.append(v * k + r[-1] * (1 - k))
    return r

def rsi(closes, p=14):
    if len(closes) < p + 1: return 50.0
    d = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    g = [x if x > 0 else 0 for x in d[-p:]]
    l = [-x if x < 0 else 0 for x in d[-p:]]
    ag, al = sum(g) / p, sum(l) / p
    return 100.0 if al == 0 else round(100 - (100 / (1 + ag / al)), 2)

def macd_full(closes):
    if len(closes) < 26: return [], [], []
    e12 = ema(closes, 12); e26 = ema(closes, 26)
    ml  = [e12[i] - e26[i] for i in range(len(e26))]
    sig = ema(ml, 9)
    return ml, sig, [ml[i] - sig[i] for i in range(len(sig))]

def bollinger(closes, p=20, dev=2.0):
    """Returns (upper, middle, lower, %B) — %B: 0=lower band, 1=upper band."""
    if len(closes) < p: return None, None, None, 0.5
    sl = closes[-p:]
    mid = sum(sl) / p
    std = (sum((x - mid) ** 2 for x in sl) / p) ** 0.5
    if std == 0: return mid, mid, mid, 0.5
    upper = mid + dev * std
    lower = mid - dev * std
    pct_b = (closes[-1] - lower) / (upper - lower)
    return upper, mid, lower, round(pct_b, 4)

def stoch_rsi(closes, rsi_p=14, stoch_p=14):
    """Stochastic RSI — returns value 0-100. <20=oversold, >80=overbought."""
    if len(closes) < rsi_p + stoch_p: return 50.0
    rsi_series = [rsi(closes[:i+1], rsi_p) for i in range(rsi_p, len(closes))]
    if len(rsi_series) < stoch_p: return 50.0
    recent = rsi_series[-stoch_p:]
    lo, hi = min(recent), max(recent)
    if hi == lo: return 50.0
    return round((rsi_series[-1] - lo) / (hi - lo) * 100, 2)

def atr(candles, p=14):
    """Average True Range — measures volatility."""
    if len(candles) < p + 1: return 0
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"] if "high" in candles[i] else candles[i]["close"]
        l = candles[i]["low"]  if "low"  in candles[i] else candles[i]["close"]
        pc = candles[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs: return 0
    return sum(trs[-p:]) / min(p, len(trs))

def obv(closes, volumes):
    """On-Balance Volume — cumulative volume pressure."""
    if len(closes) < 2: return 0, 0
    result = [0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:   result.append(result[-1] + volumes[i])
        elif closes[i] < closes[i-1]: result.append(result[-1] - volumes[i])
        else:                          result.append(result[-1])
    # OBV trend: rising = bullish, falling = bearish
    if len(result) < 5: return result[-1], 0
    obv_slope = result[-1] - result[-5]
    return result[-1], obv_slope

def compute_signals(candles, ticker, thresh):
    cl = [c["close"]  for c in candles]
    vo = [c["volume"] for c in candles]

    # ── Existing indicators ───────────────────────────────────────────────────
    e9  = ema(cl, 9);  e21 = ema(cl, 21)
    rv  = rsi(cl)
    _, _, hist = macd_full(cl); mh = hist[-1] if hist else 0
    av  = sum(vo[-20:]) / 20 if len(vo) >= 20 else (vo[-1] if vo else 1)
    vr  = round(vo[-1] / av, 2) if av > 0 else 1.0
    fn  = ticker.get("funding", 0)
    bull = e9[-1] > e21[-1]

    # EMA gap: how far apart EMA9 and EMA21 are as % of price
    # Tiny gap = flat/ranging market where EMA trend signal is unreliable
    ema_gap_pct = abs(e9[-1] - e21[-1]) / e21[-1] * 100 if e21[-1] > 0 else 0

    # ── New indicators (backtested best performers) ───────────────────────────
    bb_upper, bb_mid, bb_lower, pct_b = bollinger(cl, 20, 2.0)
    srsi  = stoch_rsi(cl, 14, 14)
    atr_v = atr(candles, 14)
    atr_pct = (atr_v / cl[-1] * 100) if cl[-1] > 0 else 0  # ATR as % of price
    _, obv_slope = obv(cl, vo)

    # ATR filter: avoid entering in extremely low-volatility (flat) markets
    # Low ATR = price not moving = more false signals
    atr_ok = atr_pct > 0.05  # at least 0.05% movement per candle on average

    # MACD momentum direction: is the histogram growing or shrinking?
    # Shrinking = fading momentum, not a good entry point
    # macd_building_short: True when histogram is getting more negative (selling pressure building)
    # macd_building_long:  True when histogram is getting more positive (buying pressure building)
    macd_building_short = len(hist) >= 3 and hist[-1] < hist[-2] and hist[-2] < hist[-3]
    macd_building_long  = len(hist) >= 3 and hist[-1] > hist[-2] and hist[-2] > hist[-3]

    # ── Score LONG (max 9 points) ─────────────────────────────────────────────
    ls = 0
    ls += 1.0 if bull else 0                          # EMA trend
    ls += 1.0 if rv < 35 else (0.5 if rv < 50 else 0) # RSI (oversold=1, neutral bull=0.5)
    ls += 1.0 if (mh > 0 and macd_building_long) else (0.5 if mh > 0 else 0)  # MACD: full only if accelerating
    ls += 0.5 if vr > 1.3 else 0                      # Volume surge
    ls += 0.5 if fn < -0.01 else 0                    # Funding (shorts paying)
    ls += 1.0 if pct_b < 0.2 else 0                   # Bollinger: near/below lower band
    ls += 1.0 if srsi < 20 else (0.5 if srsi < 40 else 0)  # Stoch RSI oversold
    ls += 1.0 if obv_slope > 0 else 0                 # OBV rising = buying pressure
    ls += 1.0 if atr_ok else 0                         # ATR: market is moving

    # ── Score SHORT (max 9 points) ────────────────────────────────────────────
    ss = 0
    ss += 1.0 if not bull else 0                       # EMA trend
    ss += 1.0 if rv > 65 else (0.5 if rv > 50 else 0) # RSI (overbought=1)
    ss += 1.0 if (mh < 0 and macd_building_short) else (0.5 if mh < 0 else 0)  # MACD: full only if accelerating
    ss += 0.5 if vr > 1.3 else 0                      # Volume surge
    ss += 0.5 if fn > 0.01 else 0                     # Funding (longs paying)
    ss += 1.0 if pct_b > 0.8 else 0                   # Bollinger: near/above upper band
    ss += 1.0 if srsi > 80 else (0.5 if srsi > 60 else 0)  # Stoch RSI overbought
    ss += 1.0 if obv_slope < 0 else 0                 # OBV falling = selling pressure
    ss += 1.0 if atr_ok else 0                         # ATR: market is moving

    ls, ss = round(ls, 1), round(ss, 1)

    if ls >= thresh and ls > ss:   dr, sc = "LONG",  ls
    elif ss >= thresh and ss > ls: dr, sc = "SHORT", ss
    else:                          dr, sc = "HOLD",  max(ls, ss)

    # ── RSI divergence detection ─────────────────────────────────────────────
    # Bearish: price higher high but RSI lower high → fade LONG signal
    # Bullish: price lower low but RSI higher low → fade SHORT signal
    rsi_divergence = None
    if len(cl) >= 10 and len(hist) >= 10:
        rsi_series = [rsi(cl[:i+1]) for i in range(max(0,len(cl)-10), len(cl))]
        pr_hi2, pr_hi1 = max(cl[-10:-5]), max(cl[-5:])
        pr_lo2, pr_lo1 = min(cl[-10:-5]), min(cl[-5:])
        ri_hi2, ri_hi1 = max(rsi_series[:5]), max(rsi_series[5:])
        ri_lo2, ri_lo1 = min(rsi_series[:5]), min(rsi_series[5:])
        if pr_hi1 > pr_hi2 and ri_hi1 < ri_hi2 - 2:
            rsi_divergence = "BEARISH"   # price up, RSI down → fade longs
        elif pr_lo1 < pr_lo2 and ri_lo1 > ri_lo2 + 2:
            rsi_divergence = "BULLISH"   # price down, RSI up → fade shorts

    return {"direction": dr, "score": sc, "max_score": 9,
            "trend": "BULL" if bull else "BEAR",
            "rsi": rv, "srsi": srsi, "macd_h": round(mh, 6),
            "vol_ratio": vr, "funding": round(fn * 100, 4),
            "pct_b": pct_b, "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_mid": bb_mid,
            "atr_pct": round(atr_pct, 4), "atr_ok": atr_ok,
            "obv_slope": round(obv_slope, 2),
            "ema_gap_pct": round(ema_gap_pct, 4),
            "macd_building_long": macd_building_long,
            "macd_building_short": macd_building_short,
            "rsi_divergence": rsi_divergence,
            "price": cl[-1], "e9": e9, "e21": e21,
            "closes": cl, "macd_hist": hist, "candles": candles}

# ══════════════════════════════════════════════════════════════════════════════
#  CLAUDE
# ══════════════════════════════════════════════════════════════════════════════
def claude_decision(signals, state, symbol, leverage, margin,
                     base_sl, base_tp, api_key, last3="no trades yet"):
    """
    Claude acts as decision engine — returns:
    {
      "action":     "TRADE" | "VETO" | "HOLD",
      "confidence": 0-100,
      "sl_pct":     adjusted stop loss %,
      "tp_pct":     adjusted take profit %,
      "reason":     short rationale string,
      "tokens_used": int
    }
    On any error returns None so bot falls back to indicator-only logic.
    """
    if not ANTHROPIC_AVAILABLE or not api_key:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""You are the decision engine for HermesBot, a MEXC futures scalper.

Market: {symbol} @ ${signals["price"]:,.6g}  |  {leverage}x leverage  |  ${margin} margin
Direction signal: {signals["direction"]}  |  Score: {signals["score"]}/9

Indicators:
- Trend (EMA9/21): {signals["trend"]}
- RSI(14): {signals["rsi"]:.1f}  ({">70 overbought" if signals["rsi"]>70 else "<30 oversold" if signals["rsi"]<30 else "neutral"})
- Stoch RSI: {signals.get("srsi",50):.1f}
- MACD histogram: {signals["macd_h"]:+.6f}
- Bollinger %B: {signals.get("pct_b",0.5):.2f}  (0=lower band, 1=upper band)
- OBV slope: {"rising" if signals.get("obv_slope",0)>0 else "falling"}
- Volume ratio: {signals["vol_ratio"]}x avg
- ATR: {signals.get("atr_pct",0):.3f}% per candle  ({"active" if signals.get("atr_ok") else "too flat"})
- Funding rate: {signals["funding"]:+.4f}%

Session: P&L ${state.total_pnl:+.2f}  |  {state.wins}W / {state.losses}L / {state.liqs} LIQ
Base SL: {base_sl*100:.2f}%  |  Base TP: {base_tp*100:.2f}%
Fees: 0.2% round-trip (open+close taker) = ${margin*leverage*0.002:.3f} on this trade.
TP price move must exceed 0.2% just to break even — set TP at least 0.3%+ above fees.
Last 3 trades: {last3}
{signals.get("_existing_note", "")}

Your job:
1. Decide: TRADE (proceed), VETO (block this trade), or HOLD (no trade signal)
2. Set confidence 0-100
3. Adjust SL and TP based on market quality:
   - Strong confluence + low ATR noise → widen TP (let it run), tighten SL
   - Weak/mixed signals → tighten TP (take profit fast), widen SL slightly
   - Never set SL below 0.03% or above 5%, never set TP below 0.05% or above 10%
4. VETO if: signals clearly contradict each other despite high score, or risk/reward is poor

Respond in EXACTLY this JSON format, nothing else:
{"action":"TRADE","confidence":82,"sl_pct":0.006,"tp_pct":0.025,"reason":"Strong RSI oversold + MACD cross with rising OBV confirms genuine buying pressure."}"""

        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}])

        raw  = msg.content[0].text.strip()
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)

        # Parse JSON response
        import re as _re
        m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())

        return {
            "action":     data.get("action", "HOLD"),
            "confidence": int(data.get("confidence", 50)),
            "sl_pct":     float(data.get("sl_pct", base_sl)),
            "tp_pct":     float(data.get("tp_pct", base_tp)),
            "reason":     str(data.get("reason", "")),
            "tokens_used": tokens,
        }
    except Exception as e:
        return None


def claude_near_tp_check(pos, cur_px, pct_to_tp, signals, api_key):
    """
    Called when a profitable trade is within 20% of its TP distance.
    Claude decides: take profit now, or hold for full TP.
    Returns:
      { "action": "TAKE" | "HOLD",
        "reason": str,
        "tokens_used": int }
    or None on error.
    """
    if not ANTHROPIC_AVAILABLE or not api_key:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        d = pos.direction
        tp_dist  = abs(pos.take_profit - pos.entry_price)
        sl_dist  = abs(pos.stop_loss   - pos.entry_price)
        cur_dist = abs(cur_px - pos.entry_price)
        profit_pct = cur_dist / pos.entry_price * 100
        rr_if_hold = (pct_to_tp * tp_dist) / sl_dist if sl_dist else 0

        prompt = f"""You are managing an open futures position that is CLOSE TO TAKE PROFIT.
Decide: take profit NOW at current price, or hold for full TP target.

Position:
- Symbol: {pos.symbol}  |  Direction: {d}  |  Leverage: {pos.leverage}x
- Entry: ${pos.entry_price:,.6g}  |  Current: ${cur_px:,.6g}  |  TP: ${pos.take_profit:,.6g}
- Distance to TP: {pct_to_tp:.1f}% of remaining TP gap  ({abs(pos.take_profit-cur_px):,.4g} price units away)
- Locked-in profit so far: {profit_pct:.3f}% price move ({profit_pct*pos.leverage:.1f}% margin return)
- SL at: ${pos.stop_loss:,.6g}  (would lose {sl_dist/pos.entry_price*100:.3f}% price if hit)

Market signals RIGHT NOW:
- Trend (EMA9/21): {signals.get("trend","?")}
- RSI: {signals.get("rsi",50):.1f}  |  Stoch RSI: {signals.get("srsi",50):.1f}
- MACD histogram: {signals.get("macd_h",0):+.6f}
- OBV slope: {"falling" if signals.get("obv_slope",0) < 0 else "rising"}
- Bollinger %B: {signals.get("pct_b",0.5):.2f}
- ATR: {signals.get("atr_pct",0):.3f}% per candle

Take profit early (TAKE) if:
- Momentum is reversing AGAINST the trade (RSI turning, MACD crossing, OBV diverging)
- We are very close (<10% gap left) and momentum is stalling
- Risk of snapback outweighs the small remaining gain

Hold for full TP (HOLD) if:
- Momentum is still WITH the trade
- RSI still has room (not at extreme reversal zone)
- The remaining distance is worth the risk

Respond in EXACTLY this JSON format, nothing else:
{"action":"HOLD","reason":"MACD still negative and RSI has room — momentum intact, hold for full TP."}"""

        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}])

        raw    = msg.content[0].text.strip()
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)

        import re as _re
        m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        return {
            "action":      data.get("action", "HOLD").upper(),
            "reason":      str(data.get("reason", "")),
            "tokens_used": tokens,
        }
    except Exception:
        return None


def claude_stale_trade_check(pos, cur_px, minutes_open, max_drift_pct, signals, api_key):
    """
    Called when a trade has been open a long time with little movement.
    Claude decides: close to free up margin, or hold longer.
    Returns:
      { "action": "CLOSE" | "HOLD",
        "reason": str,
        "tokens_used": int }
    or None on error.
    """
    if not ANTHROPIC_AVAILABLE or not api_key:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        d = pos.direction
        raw_chg = ((cur_px - pos.entry_price)/pos.entry_price if d=="LONG"
                   else (pos.entry_price - cur_px)/pos.entry_price)
        margin_pct = raw_chg * pos.leverage * 100
        dist_to_tp = abs(pos.take_profit - cur_px) / pos.entry_price * 100
        dist_to_sl = abs(pos.stop_loss   - cur_px) / pos.entry_price * 100

        prompt = f"""You are reviewing a stale open futures position that has barely moved.
The trade has been open for {minutes_open:.0f} minutes with only {max_drift_pct:.3f}% max price drift.

Position:
- Symbol: {pos.symbol}  |  Direction: {d}  |  Leverage: {pos.leverage}x
- Entry: ${pos.entry_price:,.6g}  |  Current: ${cur_px:,.6g}
- Time open: {minutes_open:.0f} minutes
- Max drift from entry: {max_drift_pct:.3f}% price  (very little movement)
- Current P&L: {margin_pct:+.1f}% on margin
- Distance to TP: {dist_to_tp:.3f}%  |  Distance to SL: {dist_to_sl:.3f}%

Market signals RIGHT NOW:
- Trend (EMA9/21): {signals.get("trend","?")}
- RSI: {signals.get("rsi",50):.1f}  |  Stoch RSI: {signals.get("srsi",50):.1f}
- MACD histogram: {signals.get("macd_h",0):+.6f}
- OBV slope: {"falling" if signals.get("obv_slope",0) < 0 else "rising"}
- Bollinger %B: {signals.get("pct_b",0.5):.2f}
- ATR: {signals.get("atr_pct",0):.3f}% per candle  (low ATR = low volatility)
- Funding rate: {signals.get("funding",0):+.4f}%

Close (CLOSE) if:
- No catalyst visible — trend flat, ATR low, all indicators neutral
- Holding is paying ongoing funding costs with no directional conviction
- Margin is better deployed on a fresh signal

Hold (HOLD) if:
- Trend still aligns with position direction
- A catalyst appears imminent (RSI at extreme, MACD about to cross)
- Position is near TP and just needs patience

Respond in EXACTLY this JSON format, nothing else:
{"action":"CLOSE","reason":"All indicators neutral, ATR flat, funding cost accumulating — no reason to hold stale position."}"""

        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}])

        raw    = msg.content[0].text.strip()
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)

        import re as _re
        m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        return {
            "action":      data.get("action", "HOLD").upper(),
            "reason":      str(data.get("reason", "")),
            "tokens_used": tokens,
        }
    except Exception:
        return None

def claude_sl_update(pos, cur_px, drawdown_pct, velocity_pct, signals, api_key):
    """
    Called when a position is moving against us quickly.
    Claude decides whether to tighten the SL, hold it, or close immediately.
    Returns:
      { "action": "TIGHTEN" | "HOLD" | "CLOSE",
        "new_sl_price": float,   # only if TIGHTEN
        "reason": str,
        "tokens_used": int }
    or None on error.
    """
    if not ANTHROPIC_AVAILABLE or not api_key:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        d = pos.direction
        current_sl_pct = abs(cur_px - pos.stop_loss) / pos.entry_price * 100
        current_tp_pct = abs(pos.take_profit - pos.entry_price) / pos.entry_price * 100
        dist_to_sl_pct = abs(cur_px - pos.stop_loss) / pos.entry_price * 100

        prompt = f"""You are monitoring an open futures position that is moving AGAINST us.

Position:
- Symbol: {pos.symbol}  |  Direction: {d}  |  Leverage: {pos.leverage}x
- Entry: ${pos.entry_price:,.6g}  |  Current: ${cur_px:,.6g}
- Drawdown: {drawdown_pct:+.3f}% on margin  ({drawdown_pct/pos.leverage:.3f}% price move)
- Move velocity: {velocity_pct:.4f}% price move per cycle (fast = bad)
- Current SL: ${pos.stop_loss:,.6g}  ({current_sl_pct:.3f}% from entry)
- Current TP: ${pos.take_profit:,.6g}  ({current_tp_pct:.3f}% from entry)
- Distance to SL: {dist_to_sl_pct:.3f}% of entry price

Market context:
- RSI: {signals.get("rsi", 50):.1f}  |  Stoch RSI: {signals.get("srsi", 50):.1f}
- MACD histogram: {signals.get("macd_h", 0):+.6f}
- OBV slope: {"falling" if signals.get("obv_slope", 0) < 0 else "rising"}
- Bollinger %B: {signals.get("pct_b", 0.5):.2f}
- Trend: {signals.get("trend", "?")}

Decide ONE of:
1. TIGHTEN — move SL closer to current price to limit loss (give new_sl_price)
2. HOLD    — leave SL where it is, normal volatility, likely to reverse
3. CLOSE   — momentum is strongly against us, get out now before SL is hit

Rules:
- TIGHTEN: new SL must be between current price and original SL (cannot widen it)
- TIGHTEN: keep at least 0.03% buffer from current price to avoid immediate trigger
- CLOSE only if multiple indicators confirm continuation against us
- HOLD if this looks like normal noise within ATR range

Respond in EXACTLY this JSON format, nothing else:
{{"action":"TIGHTEN","new_sl_price":{pos.stop_loss:.6g},"reason":"RSI collapsing with OBV falling confirms selling pressure accelerating."}}"""

        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}])

        raw    = msg.content[0].text.strip()
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)

        import re as _re
        m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())

        action = data.get("action", "HOLD").upper()
        result = {
            "action":      action,
            "new_sl_price": float(data.get("new_sl_price", pos.stop_loss)),
            "reason":      str(data.get("reason", "")),
            "tokens_used": tokens,
        }

        # Safety: never let Claude widen the SL or set it past current price
        if action == "TIGHTEN":
            min_buffer = cur_px * 0.0003  # 0.03% buffer minimum
            if d == "LONG":
                # New SL must be below current price with buffer, but above original SL
                result["new_sl_price"] = max(
                    pos.stop_loss,
                    min(result["new_sl_price"], cur_px - min_buffer))
            else:
                # SHORT: new SL must be above current price with buffer, below original SL
                result["new_sl_price"] = min(
                    pos.stop_loss,
                    max(result["new_sl_price"], cur_px + min_buffer))

        return result
    except Exception:
        return None



def claude_hedge_check(pos, cur_px, drawdown_pct, signals, api_key):
    """
    Claude independently decides whether to open a hedge on an existing position.
    Called every cycle for each open non-hedge position, regardless of hedge toggle.
    Returns:
      { "action": "HEDGE" | "HOLD",
        "confidence": 0-100,
        "reason": str,
        "tokens_used": int }
    or None on error.
    """
    if not ANTHROPIC_AVAILABLE or not api_key:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        d = pos.direction
        dist_to_sl  = abs(cur_px - pos.stop_loss) / pos.entry_price * 100
        dist_to_tp  = abs(pos.take_profit - cur_px) / pos.entry_price * 100
        dist_to_liq = abs(cur_px - pos.liq_price)  / pos.entry_price * 100
        time_open   = ""
        try:
            from datetime import datetime, timezone
            opened = datetime.fromisoformat(pos.opened_at.replace("Z", "+00:00"))
            mins   = int((datetime.now(timezone.utc) - opened).total_seconds() / 60)
            time_open = f"{mins} minutes"
        except Exception:
            time_open = "unknown"

        prompt = f"""You are risk manager for HermesBot, a MEXC futures scalper.
An existing position is in drawdown. Decide if opening a HEDGE (opposite direction, half margin) is wise.

Position:
- Symbol: {pos.symbol}  |  Direction: {d}  |  Leverage: {pos.leverage}x
- Entry: ${pos.entry_price:,.6g}  |  Current: ${cur_px:,.6g}
- Drawdown on margin: {drawdown_pct:+.2f}%  ({drawdown_pct/pos.leverage:.3f}% price move)
- Time open: {time_open}
- Distance to SL:  {dist_to_sl:.3f}%  |  Distance to TP: {dist_to_tp:.3f}%
- Distance to LIQ: {dist_to_liq:.3f}%

Market signals now:
- Trend (EMA9/21): {signals.get("trend", "?")}
- RSI: {signals.get("rsi", 50):.1f}  |  Stoch RSI: {signals.get("srsi", 50):.1f}
- MACD histogram: {signals.get("macd_h", 0):+.6f}
- OBV slope: {"falling" if signals.get("obv_slope", 0) < 0 else "rising"}
- Bollinger %B: {signals.get("pct_b", 0.5):.2f}
- ATR: {signals.get("atr_pct", 0):.3f}% per candle
- Funding rate: {signals.get("funding", 0):+.4f}%

Hedge logic: opening opposite direction at half margin locks in partial loss now,
caps further downside, and profits if price continues against original position.
Best when: momentum clearly reversed, indicators agree, SL still far away (room to worsen).
Avoid when: normal noise dip, indicators mixed, or position close to SL already.

Decide ONE of:
1. HEDGE — open opposite position at half margin to cap losses
2. HOLD  — drawdown is noise, leave position alone

Rules:
- Only HEDGE if 3+ indicators confirm the adverse move will continue
- Only HEDGE if drawdown > -5% on margin (worth the cost)
- Only HEDGE if distance to SL > 0.1% price (room for it to get worse)
- HOLD in all other cases

Respond in EXACTLY this JSON format, nothing else:
{{"action":"HEDGE","confidence":78,"reason":"RSI dropped below 30 with MACD turning negative and OBV falling — reversal unlikely short term."}}"""

        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}])

        raw    = msg.content[0].text.strip()
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)

        import re as _re
        m = _re.search(r'\{[^{}]+\}', raw, _re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())

        return {
            "action":      data.get("action", "HOLD").upper(),
            "confidence":  int(data.get("confidence", 50)),
            "reason":      str(data.get("reason", "")),
            "tokens_used": tokens,
        }
    except Exception:
        return None

# Keep old function name as alias for HOLD reasoning (no decision needed)
def claude_reasoning(signals, state, symbol, leverage, margin, api_key):
    """Used for HOLD cycles — just returns explanatory text, no decision."""
    if not ANTHROPIC_AVAILABLE or not api_key: return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (f"HermesBot HOLD analysis. {symbol} @ ${signals['price']:,.6g} "
                  f"Score {signals['score']}/9 {signals['direction']}. "
                  f"Trend:{signals['trend']} RSI:{signals['rsi']:.0f} "
                  f"StochRSI:{signals.get('srsi',50):.0f} MACD:{'pos' if signals['macd_h']>0 else 'neg'} "
                  f"BB%B:{signals.get('pct_b',0.5):.2f} OBV:{'up' if signals.get('obv_slope',0)>0 else 'dn'} "
                  f"ATR:{signals.get('atr_pct',0):.3f}% Fund:{signals['funding']:+.4f}%. "
                  f"2 sentences: why hold and what would change your mind.")
        msg = client.messages.create(model="claude-haiku-4-5", max_tokens=100,
                                     messages=[{"role": "user", "content": prompt}])
        return msg.content[0].text
    except Exception:
        return None

def test_claude_key(api_key):
    if not ANTHROPIC_AVAILABLE:
        return False, "Run:  pip install anthropic"
    if not api_key.strip():
        return False, "No key entered"
    try:
        client = anthropic.Anthropic(api_key=api_key.strip())
        client.messages.create(model="claude-haiku-4-5", max_tokens=5,
                                messages=[{"role": "user", "content": "hi"}])
        return True, "✅  Connected"
    except Exception as e:
        raw = str(e)
        if "401" in raw or "authentication" in raw.lower(): return False, "❌  Invalid key"
        if "403" in raw or "credit" in raw.lower():        return False, "❌  Add billing: console.anthropic.com"
        if "connection" in raw.lower():                    return False, "❌  No internet"
        return False, f"❌  {raw[:80]}"

# ══════════════════════════════════════════════════════════════════════════════
#  CHART PANEL
# ══════════════════════════════════════════════════════════════════════════════
class ChartPanel:
    def __init__(self, parent, symbol, colour):
        self.symbol = symbol; self.colour = colour
        self.fig = None; self.canvas = None
        self._build(parent)

    def _build(self, parent):
        if not MPLOT:
            tk.Label(parent, text="pip install matplotlib\nto enable charts",
                     bg=BG4, fg=MUTED, font=FM, justify="center").pack(expand=True)
            return

        # ── Toolbar: TF buttons + zoom controls ──────────────────────────────
        toolbar = tk.Frame(parent, bg=BG3, height=26)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        self._chart_tf     = "Min5"
        self._chart_zoom   = 60   # number of candles visible
        self._chart_offset = 0    # candles from right (0 = live edge)
        self._last_candles   = []
        self._last_signals   = None
        self._last_positions = []
        self._on_tf_change   = None  # callback set by app on first update()

        tf_opts = [("1m","Min1"),("5m","Min5"),("15m","Min15"),("1h","Hour1"),("1d","Day1")]
        for label, tf_val in tf_opts:
            b = tk.Button(toolbar, text=label,
                          font=("Consolas", 7, "bold"),
                          bg=BLUE if tf_val == "Min5" else BG3,
                          fg=BG if tf_val == "Min5" else MUTED,
                          relief="flat", padx=6, pady=2, cursor="hand2",
                          command=lambda t=tf_val: self._set_tf(t))
            b.pack(side="left", padx=(2,0), pady=2)
            setattr(self, f"_tf_btn_{tf_val}", b)

        tk.Frame(toolbar, bg=SEP, width=1).pack(side="left", fill="y", padx=4, pady=3)

        for txt, cmd in [("🔍+", lambda: self._zoom(-10)),
                          ("🔍−", lambda: self._zoom(+10)),
                          ("◀",   lambda: self._scroll(+10)),
                          ("▶",   lambda: self._scroll(-10)),
                          ("↺",   lambda: self._reset_view())]:
            tk.Button(toolbar, text=txt, font=("Consolas", 8), bg=BG3, fg=MUTED,
                      relief="flat", padx=5, pady=1, cursor="hand2",
                      command=cmd).pack(side="left", padx=(2,0), pady=2)

        self._zoom_lbl = tk.Label(toolbar, text="60 candles", font=("Consolas", 7),
                                   fg=DIM, bg=BG3)
        self._zoom_lbl.pack(side="right", padx=6)

        plt.style.use("dark_background")
        self.fig = plt.Figure(figsize=(8, 5), facecolor=BG4)
        gs = GridSpec(3, 1, figure=self.fig, hspace=0.04, height_ratios=[3, 1, 1],
                       left=0.02, right=0.88, top=0.97, bottom=0.03)
        self.ax_p = self.fig.add_subplot(gs[0])
        self.ax_r = self.fig.add_subplot(gs[1], sharex=self.ax_p)
        self.ax_m = self.fig.add_subplot(gs[2], sharex=self.ax_p)
        for ax in (self.ax_p, self.ax_r, self.ax_m):
            ax.set_facecolor(BG4)
            ax.tick_params(colors=C_AX, labelsize=7.5)
            ax.spines[:].set_color(C_GRID)
            ax.grid(color=C_GRID, linewidth=0.5, alpha=0.8)
        plt.setp(self.ax_p.get_xticklabels(), visible=False)
        plt.setp(self.ax_r.get_xticklabels(), visible=False)
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # Mouse scroll for zoom, drag not needed (use buttons)
        self.canvas.get_tk_widget().bind("<MouseWheel>",
            lambda e: self._zoom(-5 if e.delta > 0 else 5))
        self.canvas.get_tk_widget().bind("<Button-4>",
            lambda e: self._zoom(-5))   # Linux scroll up
        self.canvas.get_tk_widget().bind("<Button-5>",
            lambda e: self._zoom(+5))   # Linux scroll down
        self._placeholder()

    def _set_tf(self, tf):
        self._chart_tf = tf
        self._chart_offset = 0   # jump to live edge on TF change
        # Update button highlights
        tf_opts = ["Min1","Min5","Min15","Hour1","Day1"]
        for t in tf_opts:
            btn = getattr(self, f"_tf_btn_{t}", None)
            if btn:
                btn.config(bg=BLUE if t == tf else BG3,
                           fg=BG if t == tf else MUTED)
        # Trigger a refresh of this chart via the app's fetch pipeline
        if hasattr(self, "_on_tf_change") and self._on_tf_change:
            self._on_tf_change(self.symbol, tf)

    def _zoom(self, delta):
        self._chart_zoom = max(15, min(200, self._chart_zoom + delta))
        try: self._zoom_lbl.config(text=f"{self._chart_zoom} candles")
        except Exception: pass
        self._redraw()

    def _scroll(self, delta):
        max_off = max(0, len(self._last_candles) - self._chart_zoom)
        self._chart_offset = max(0, min(max_off, self._chart_offset + delta))
        self._redraw()

    def _reset_view(self):
        self._chart_offset = 0
        self._chart_zoom   = 60
        try: self._zoom_lbl.config(text="60 candles")
        except Exception: pass
        self._redraw()

    def _redraw(self):
        if self._last_candles:
            self._draw(self._last_candles, self._last_signals, self._last_positions)

    def _placeholder(self):
        if not MPLOT: return
        self.ax_p.clear(); self.ax_p.set_facecolor(BG4)
        self.ax_p.text(0.5, 0.5, f"{self.symbol}\nWaiting for data…",
                       transform=self.ax_p.transAxes, ha="center", va="center",
                       color=self.colour, fontsize=13, alpha=0.4)
        self.canvas.draw()

    def update(self, candles, signals=None, positions=None, on_tf_change=None):
        if not MPLOT or not candles: return
        if on_tf_change:
            self._on_tf_change = on_tf_change
        self._last_candles   = candles
        self._last_signals   = signals
        self._last_positions = positions or []
        # Always go through _redraw so zoom/offset are applied consistently
        self._redraw()

    def _draw(self, candles, signals, positions):
        # Apply zoom and scroll offset
        zoom   = getattr(self, "_chart_zoom",   60)
        offset = getattr(self, "_chart_offset",  0)
        total  = len(candles)
        end    = total - offset
        start  = max(0, end - zoom)
        candles = candles[start:end] if end > 0 else candles[-zoom:]

        cl = [c["close"] for c in candles]; op = [c["open"]  for c in candles]
        hi = [c["high"]  for c in candles]; lo = [c["low"]   for c in candles]
        n = len(candles); xs = list(range(n))

        for ax in (self.ax_p, self.ax_r, self.ax_m):
            ax.clear(); ax.set_facecolor(BG4)
            ax.tick_params(colors=C_AX, labelsize=7.5)
            ax.grid(color=C_GRID, linewidth=0.5, alpha=0.8)
            ax.spines[:].set_color(C_GRID)

        # Candles
        for i, (o, c, h, l) in enumerate(zip(op, cl, hi, lo)):
            col  = C_UP if c >= o else C_DOWN
            bbot = min(o, c)
            bh   = max(abs(c - o), c * 0.0002)
            self.ax_p.bar(i, bh, bottom=bbot, color=col, width=0.7, linewidth=0, alpha=0.9)
            self.ax_p.plot([i, i], [l, h], color=col, linewidth=0.9, alpha=0.85)

        # EMAs — slice to the same window as candles
        if signals and "e9" in signals:
            e9_full  = signals["e9"]
            e21_full = signals["e21"]
            total_full = len(self._last_candles) if self._last_candles else n
            # Slice the same start:end window applied to candles
            zoom   = getattr(self, "_chart_zoom",   60)
            offset = getattr(self, "_chart_offset",  0)
            end_i  = total_full - offset
            start_i= max(0, end_i - zoom)
            e9  = e9_full[start_i:end_i]  if len(e9_full)  >= total_full else e9_full
            e21 = e21_full[start_i:end_i] if len(e21_full) >= total_full else e21_full
            if len(e9) == n:
                self.ax_p.plot(xs, e9,  color=YELLOW, linewidth=1.2, alpha=0.9, label="EMA9")
            if len(e21) == n:
                self.ax_p.plot(xs, e21, color=ORANGE, linewidth=1.2, alpha=0.9, label="EMA21")

        # Position lines — entry, TP, SL, LIQ with price labels
        def _fp(v):
            if v < 0.001:  return f"${v:.6f}"
            if v < 0.1:    return f"${v:.5f}"
            if v < 10:     return f"${v:.4f}"
            if v >= 1000:  return f"${v:,.1f}"
            return f"${v:,.2f}"

        for pos in positions:
            if pos.symbol != self.symbol: continue
            is_long = pos.direction == "LONG"
            pc  = GREEN if is_long else RED
            tag = "L" if is_long else "S"
            h_tag = " [H]" if pos.hedge_of else ""

            # Entry line — blue dashed, distinct from TP/SL
            ENTRY_COL = "#4da6ff"  # bright blue, clearly different from green/red
            self.ax_p.axhline(pos.entry_price, color=ENTRY_COL, lw=1.5, ls="--", alpha=0.95,
                               label=f"Entry ({tag}){h_tag}")
            self.ax_p.annotate(
                f" Entry {_fp(pos.entry_price)}",
                xy=(n * 0.01, pos.entry_price),
                color=ENTRY_COL, fontsize=7.5, fontweight="bold",
                va="bottom", ha="left",
                bbox=dict(boxstyle="round,pad=0.15", fc=BG4, ec=ENTRY_COL, alpha=0.85))

            # Take profit — green dashed
            self.ax_p.axhline(pos.take_profit, color="#00e676", lw=1.2, ls="--", alpha=0.9,
                               label=f"TP {_fp(pos.take_profit)}")
            self.ax_p.annotate(
                f" TP  {_fp(pos.take_profit)}",
                xy=(n * 0.01, pos.take_profit),
                color="#00e676", fontsize=7.5, fontweight="bold",
                va="bottom", ha="left",
                bbox=dict(boxstyle="round,pad=0.15", fc=BG4, ec="#00e676", alpha=0.85))

            # Stop loss — red dashed
            self.ax_p.axhline(pos.stop_loss, color="#ff3d57", lw=1.2, ls="--", alpha=0.9,
                               label=f"SL  {_fp(pos.stop_loss)}")
            self.ax_p.annotate(
                f" SL  {_fp(pos.stop_loss)}",
                xy=(n * 0.01, pos.stop_loss),
                color="#ff3d57", fontsize=7.5, fontweight="bold",
                va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.15", fc=BG4, ec="#ff3d57", alpha=0.85))

            # Liquidation — pink dotted, thinner
            self.ax_p.axhline(pos.liq_price, color="#f783ac", lw=0.9, ls="-.", alpha=0.75,
                               label=f"LIQ {_fp(pos.liq_price)}")
            self.ax_p.annotate(
                f" LIQ {_fp(pos.liq_price)}",
                xy=(n * 0.01, pos.liq_price),
                color="#f783ac", fontsize=7, fontweight="bold",
                va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.15", fc=BG4, ec="#f783ac", alpha=0.75))

        # Price label
        if cl:
            pcol = C_UP if cl[-1] >= op[-1] else C_DOWN
            pstr = f"  ${cl[-1]:,.4f}" if cl[-1] < 10 else f"  ${cl[-1]:,.2f}"
            self.ax_p.annotate(pstr, xy=(n-1, cl[-1]), color=pcol,
                               fontsize=8.5, fontweight="bold", va="center")

        self.ax_p.text(0.01, 0.97, pair_label(self.symbol),
                       transform=self.ax_p.transAxes,
                       color=self.colour, fontsize=10, fontweight="bold", va="top")
        if hi and lo:
            pad = (max(hi) - min(lo)) * 0.08 or 1
            self.ax_p.set_ylim(min(lo) - pad, max(hi) + pad)
        self.ax_p.yaxis.tick_right(); self.ax_p.yaxis.set_label_position("right")
        self.ax_p.legend(loc="upper left", fontsize=7.5, facecolor=BG2,
                         edgecolor=SEP, labelcolor=C_AX, framealpha=0.92,
                         ncol=2, handlelength=1.8, borderpad=0.5)

        # RSI — compute from full close history for accuracy, then slice to window
        if self._last_candles:
            full_cl = [c["close"] for c in self._last_candles]
            zoom_   = getattr(self, "_chart_zoom",   60)
            offset_ = getattr(self, "_chart_offset",  0)
            total_  = len(full_cl)
            end_    = total_ - offset_
            start_  = max(0, end_ - zoom_)
            rsi_full = [rsi(full_cl[:i+1]) for i in range(total_)]
            rsi_v    = rsi_full[start_:end_]
            if len(rsi_v) != n:
                rsi_v = [rsi(cl[:i+1]) for i in range(n)]  # fallback
        else:
            rsi_v = [rsi(cl[:i+1]) for i in range(n)]
        self.ax_r.plot(xs, rsi_v, color=self.colour, linewidth=1.2)
        self.ax_r.axhline(70, color=RED,   lw=0.7, ls="--", alpha=0.7)
        self.ax_r.axhline(50, color=MUTED, lw=0.4, ls="-",  alpha=0.35)
        self.ax_r.axhline(30, color=GREEN, lw=0.7, ls="--", alpha=0.7)
        self.ax_r.fill_between(xs, rsi_v, 70, where=[v > 70 for v in rsi_v], color=RED,   alpha=0.1)
        self.ax_r.fill_between(xs, rsi_v, 30, where=[v < 30 for v in rsi_v], color=GREEN, alpha=0.1)
        self.ax_r.set_ylim(0, 100); self.ax_r.set_yticks([30, 50, 70])
        self.ax_r.yaxis.tick_right()
        if rsi_v:
            rv = rsi_v[-1]
            rc = RED if rv > 70 else (GREEN if rv < 30 else C_AX)
            self.ax_r.text(0.99, 0.82, f"RSI  {rv:.1f}", transform=self.ax_r.transAxes,
                           color=rc, fontsize=8, ha="right", fontweight="bold")

        # MACD — slice to the same visible window
        if signals and signals.get("macd_hist"):
            mh_full = list(signals["macd_hist"])
            total_full = len(self._last_candles) if self._last_candles else n
            zoom   = getattr(self, "_chart_zoom",   60)
            offset = getattr(self, "_chart_offset",  0)
            end_i  = total_full - offset
            start_i= max(0, end_i - zoom)
            if len(mh_full) >= total_full:
                mh = mh_full[start_i:end_i]
            else:
                mh = mh_full
            if len(mh) < n: mh = [0] * (n - len(mh)) + mh
            elif len(mh) > n: mh = mh[-n:]
            self.ax_m.bar(xs, mh, color=[C_UP if v >= 0 else C_DOWN for v in mh],
                          width=0.7, alpha=0.85)
            self.ax_m.axhline(0, color=SEP2, lw=0.6)
        self.ax_m.yaxis.tick_right(); self.ax_m.set_xticks([])
        self.ax_m.text(0.01, 0.82, "MACD", transform=self.ax_m.transAxes, color=C_AX, fontsize=7)

        plt.setp(self.ax_p.get_xticklabels(), visible=False)
        plt.setp(self.ax_r.get_xticklabels(), visible=False)
        try: self.canvas.draw()
        except Exception: pass

# ══════════════════════════════════════════════════════════════════════════════
#  OPEN POSITIONS DOCK  — persistent bar shown on every tab
# ══════════════════════════════════════════════════════════════════════════════
class PositionsDock:
    """Slim bar at the bottom of the window showing all open positions."""

    def __init__(self, parent, state: BotState, on_close=None, on_hedge=None):
        self.state    = state
        self.frames   = {}   # pos_id -> frame widget
        self.on_close = on_close   # callback(pid) to manually close a position
        self.on_hedge = on_hedge   # callback(pid) to manually open hedge

        self.outer = tk.Frame(parent, bg=BG2, height=155)
        self.outer.pack(fill="x", side="bottom")
        self.outer.pack_propagate(False)
        tk.Frame(self.outer, bg=BLUE, height=1).pack(fill="x")

        # Header strip
        hdr = tk.Frame(self.outer, bg=BG3, height=20)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  OPEN POSITIONS", font=("Consolas", 8, "bold"),
                 fg=MUTED, bg=BG3, anchor="w").pack(side="left")
        self.count_lbl = tk.Label(hdr, text="0 open", font=("Consolas", 8, "bold"),
                                   fg=DIM, bg=BG3)
        self.count_lbl.pack(side="right", padx=8)

        # Scrollable row of position cards
        self.scroll_frame = tk.Frame(self.outer, bg=BG2)
        self.scroll_frame.pack(fill="both", expand=True, padx=4, pady=1)

        self.no_pos_lbl = tk.Label(self.scroll_frame,
                                    text="No open positions",
                                    font=("Consolas", 9), fg=DIM, bg=BG2)
        self.no_pos_lbl.pack(side="left", padx=12, pady=4)

    def refresh(self, current_prices: dict):
        # Remove closed positions
        for pid in list(self.frames.keys()):
            if pid not in self.state.positions:
                self.frames[pid].destroy()
                del self.frames[pid]

        positions = self.state.positions
        if not positions:
            self.no_pos_lbl.pack(side="left", padx=12, pady=4)
            self.count_lbl.config(text="0 open")
            return
        self.no_pos_lbl.pack_forget()
        self.count_lbl.config(text=f"{len(positions)} open")

        def _fp(v):
            """Format price — more decimals for small values."""
            if v < 0.001:  return f"${v:.6f}"
            if v < 0.1:    return f"${v:.5f}"
            if v < 10:     return f"${v:.4f}"
            if v >= 1000:  return f"${v:,.1f}"
            return f"${v:,.2f}"

        for pid, pos in positions.items():
            px = current_prices.get(pos.symbol, pos.entry_price)
            if pos.direction == "LONG":
                raw_chg = (px - pos.entry_price) / pos.entry_price
            else:
                raw_chg = (pos.entry_price - px) / pos.entry_price
            price_pct  = raw_chg * 100                      # actual price move %
            margin_pct = raw_chg * pos.leverage * 100       # leveraged margin return %
            unr        = raw_chg * pos.leverage * pos.margin # $ PnL on margin
            sym  = pair_label(pos.symbol)
            dcol = GREEN if pos.direction == "LONG" else RED
            pct  = margin_pct  # keep compat ref
            pcol = GREEN if unr >= 0 else RED
            hedge_tag = " [H]" if pos.hedge_of else ""

            if pid not in self.frames:
                f = tk.Frame(self.scroll_frame, bg=BG3, padx=8, pady=2,
                             highlightthickness=1, highlightbackground=SEP)
                f.pack(side="left", padx=(0, 6))

                # Row 0 — symbol | direction | unrealised pnl
                f._sym = tk.Label(f, font=("Consolas", 9, "bold"), bg=BG3)
                f._dir = tk.Label(f, font=("Consolas", 9, "bold"), bg=BG3)
                f._unr = tk.Label(f, font=("Consolas", 10, "bold"), bg=BG3)
                f._sym.grid(row=0, column=0, sticky="w")
                f._dir.grid(row=0, column=1, padx=(6,0), sticky="w")
                f._unr.grid(row=0, column=2, rowspan=2, padx=(14,0), sticky="e")

                # Row 1 — entry price
                f._epx_lbl = tk.Label(f, text="Entry", font=("Consolas", 7),
                                       fg=MUTED, bg=BG3)
                f._epx = tk.Label(f, font=("Consolas", 8, "bold"), fg=SUB, bg=BG3)
                f._epx_lbl.grid(row=1, column=0, sticky="w")
                f._epx.grid(row=1, column=1, padx=(6,0), sticky="w")

                # Row 2 — current price + time open
                f._cur_lbl = tk.Label(f, font=("Consolas", 7), fg=CYAN, bg=BG3, justify="left")
                f._cur_lbl.grid(row=2, column=0, columnspan=2, sticky="w")
                # fee label on right
                f._fee_lbl = tk.Label(f, font=("Consolas", 7), fg=AMBER, bg=BG3)
                f._fee_lbl.grid(row=2, column=2, sticky="e")

                # Row 3 — TP | SL | LIQ
                f._levels = tk.Label(f, font=("Consolas", 7), bg=BG3, justify="left")
                f._levels.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0,0))

                # Row 4 — Close and Hedge buttons
                btn_frame = tk.Frame(f, bg=BG3)
                btn_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(3,0))

                _pid = pid  # capture for lambda
                close_btn = tk.Button(
                    btn_frame, text="✕ Close",
                    font=("Consolas", 8, "bold"),
                    bg="#3d0a0a", fg=RED,
                    activebackground="#5a1010", activeforeground=RED,
                    relief="flat", padx=8, pady=2, cursor="hand2",
                    command=lambda p=_pid: self._manual_close(p))
                close_btn.pack(side="left", padx=(0,4))

                hedge_btn = tk.Button(
                    btn_frame, text="⇄ Hedge",
                    font=("Consolas", 8, "bold"),
                    bg="#1a2a0a", fg=AMBER,
                    activebackground="#2a3d10", activeforeground=AMBER,
                    relief="flat", padx=8, pady=2, cursor="hand2",
                    command=lambda p=_pid: self._manual_hedge(p))
                hedge_btn.pack(side="left")

                self.frames[pid] = f

            frm = self.frames[pid]
            frm._sym.config(text=f"{sym}{hedge_tag}",
                             fg=PAIR_COL.get(pos.symbol, CYAN))
            frm._dir.config(text=f"{pos.direction} {pos.leverage}x", fg=dcol)
            frm._unr.config(
                text=(f"{'+'if unr>=0 else '-'}${abs(unr):.2f}  {margin_pct:+.1f}%"),
                fg=pcol, justify="right")
            frm._epx.config(text=_fp(pos.entry_price))

            # Current price + time open
            try:
                from datetime import datetime, timezone
                opened = datetime.fromisoformat(pos.opened_at.replace("Z","+00:00"))
                secs   = int((datetime.now(timezone.utc) - opened).total_seconds())
                if secs < 3600:
                    dur_str = f"{secs//60}m {secs%60}s"
                else:
                    dur_str = f"{secs//3600}h {(secs%3600)//60}m"
            except Exception:
                dur_str = "—"
            fee_cost = round(pos.margin * pos.leverage * 0.001 * 2, 4)  # 0.1% each side
            if hasattr(frm, "_cur_lbl"):
                frm._cur_lbl.config(text=f"Now {_fp(px)}  {dur_str}")
            if hasattr(frm, "_fee_lbl"):
                frm._fee_lbl.config(text=f"fee≈${fee_cost:.3f}")
            # Colour-coded TP / SL / LIQ on one line
            frm._levels.config(
                text=f"TP {_fp(pos.take_profit)}   SL {_fp(pos.stop_loss)}   LIQ {_fp(pos.liq_price)}",
                fg=SUB)

    def _manual_close(self, pid):
        if self.on_close:
            self.on_close(pid)

    def _manual_hedge(self, pid):
        if self.on_hedge:
            self.on_hedge(pid)

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════
class HermesBotApp:
    def __init__(self, root):
        self.root = root
        root.title("HermesBot  v4  —  MEXC Futures")
        root.configure(bg=BG)
        root.geometry("1520x960")
        root.minsize(1280, 800)

        self.bot_running   = False
        self.bot_thread    = None
        self.state         = BotState()
        self._stop_event   = threading.Event()
        self.chart_panels  = {}
        self._last_claude_call  = 0
        self._claude_tokens     = 0   # total tokens used this session
        self._claude_cost       = 0.0 # estimated $ cost this session
        self._claude_calls      = 0   # number of calls this session
        self._bot_start_time    = None
        self._cycles_run        = 0
        self._last_signal_time  = None
        self._last_signal_pair  = None
        self._last_signal_dir   = None
        self._hold_streak       = 0   # consecutive HOLD cycles
        self._adaptive_thr      = None  # None = use config value
        self._dead_pairs     = set()
        self._live_balance   = None   # cached MEXC account data
        self._balance_fetch  = 0      # timestamp of last fetch  # pairs that returned code 1001
        self._price_history  = {}     # pid -> list of (timestamp, price) for velocity tracking
        self._price_peak     = {}     # pid -> best price seen (for near-TP and stale checks)
        self._ai_trade_log   = {}     # pid -> list of {time, event, reason, col} dicts
        self._stale_checked  = set()  # pids already sent to stale check this hour
        self._pair_cooldown  = {}     # pair -> timestamp of last loss (cooldown tracking)
        self._h1_trends      = {}     # pair -> "BULL"/"BEAR" from hourly TF
        self._h1_last_fetch  = 0      # last time h1 trends were refreshed
        self._losing_streak  = 0      # consecutive losses this session
        self._peak_leverage  = None   # original leverage before streak reduction
        self.pair_candles  = {p: [] for p in PAIRS}
        self.pair_signals  = {p: None for p in PAIRS}
        self._chart_timer  = None
        self._dock_timer   = None
        self.current_prices= {p: 0.0 for p in PAIRS}

        self._style()
        self._build_ui()
        self._load_keys()
        self._log("HermesBot v4 ready.  Press START BOT to begin.", BLUE)
        self._log("Select ● Paper or ⚡ Live! in the MODE section above.", DIM)
        self._log("─" * 55, DIM)
        self._log("Optimised defaults loaded:", CYAN)
        self._log("  Signal threshold : 6.0/9  (6 of 9 indicators must agree)", DIM)
        self._log("  Leverage         : 10x    (survives 10% adverse move)", DIM)
        self._log("  Stop loss        : 0.8%   |  Take profit: 2.0%  (1:2.5 R/R)", DIM)
        self._log("  Max trades       : 2      |  Hedge at: -3.0% drawdown", DIM)
        self._log("  Stack longs at   : 7.0/9  (only on high-confidence signals)", DIM)
        self._log("  Candle TF        : Min5 trend + Min1 entry (dual TF)  |  Scan: every 30s", DIM)
        self._log("  Scans all 9 pairs — trades the best signal each cycle", DIM)
        self._log("  Includes: BTC ETH SOL XRP DOGE PEPE GOLD SUI TESLA", DIM)
        self._log("─" * 55, DIM)
        self._log("⚠  Paper mode — adjust leverage/margin before going live", AMBER)
        # Delay first chart load by 1.5s to let UI fully render
        self.root.after(1500, self._initial_load)
        self._chart_cycle()
        self._dock_cycle()

    # ── STYLE ──────────────────────────────────────────────────────────────────
    def _style(self):
        s = ttk.Style(); s.theme_use("clam")
        s.configure("D.TCombobox", fieldbackground=BG3, background=BG3,
                    foreground=TEXT, selectbackground=BG3, selectforeground=TEXT,
                    bordercolor=SEP, arrowcolor=MUTED, font=FM, padding=4)
        s.map("D.TCombobox", fieldbackground=[("readonly", BG3)],
              foreground=[("readonly", TEXT)])
        s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=0)
        s.configure("TNotebook.Tab", background=BG2, foreground=MUTED,
                    font=FMS, padding=(12, 6), borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", BG3)],
              foreground=[("selected", TEXT)], expand=[("selected", [0, 0, 0, 2])])
        s.configure("Vertical.TScrollbar", background=BG3, troughcolor=BG,
                    bordercolor=SEP, arrowcolor=MUTED)

    # ── TOP-LEVEL LAYOUT ───────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=BG2)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=BLUE, height=3).pack(fill="x")
        hi = tk.Frame(hdr, bg=BG2, pady=10)
        hi.pack(fill="x", padx=16)
        tk.Label(hi, text="HERMES", font=("Consolas", 20, "bold"), fg=BLUE,  bg=BG2).pack(side="left")
        tk.Label(hi, text="BOT",    font=("Consolas", 20, "bold"), fg=TEXT,  bg=BG2).pack(side="left")
        tk.Label(hi, text="  MEXC Futures  v4",   font=FUI, fg=MUTED, bg=BG2).pack(side="left", padx=10)
        # Multi-pair price ticker
        ticker_frame = tk.Frame(hi, bg=BG2)
        ticker_frame.pack(side="left", padx=12)
        self.price_lbls = {}
        for _p in PAIRS:
            _sym = pair_label(_p)
            _col = PAIR_COL[_p]
            _lf  = tk.Frame(ticker_frame, bg=BG2)
            _lf.pack(side="left", padx=(0,10))
            tk.Label(_lf, text=_sym, font=("Consolas",8,"bold"), fg=_col, bg=BG2).pack(side="left")
            lbl = tk.Label(_lf, text=" —", font=("Consolas",8), fg=SUB, bg=BG2)
            lbl.pack(side="left")
            self.price_lbls[_p] = lbl
        self.price_lbl = tk.Label(hi, text="", font=FM, fg=CYAN, bg=BG2)  # compat
        self.mode_lbl = tk.Label(hi, text="● PAPER MODE — no real orders",
                                   font=("Consolas", 10, "bold"), fg=AMBER, bg=BG2,
                                   padx=10)
        self.mode_lbl.pack(side="right", padx=4)
        self.status_dot = tk.Label(hi, text="●", font=FMB, fg=DIM, bg=BG2)
        self.status_dot.pack(side="right", padx=4)

        # Positions dock — persistent across all views
        self.dock = PositionsDock(self.root, self.state,
                                   on_close=self._manual_close_position,
                                   on_hedge=self._manual_hedge_position)

        # Body
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG, width=330)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.pack_propagate(False); left.grid_propagate(False)

        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1); right.columnconfigure(0, weight=1)

        self._build_sidebar(left)
        self._build_metrics(right)
        self._build_claude_panel(right)
        self._build_tabs(right)

    # ── SIDEBAR ────────────────────────────────────────────────────────────────
    def _build_sidebar(self, parent):
        cv = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(fill="both", expand=True)
        inner = tk.Frame(cv, bg=BG)
        wid = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: (cv.configure(scrollregion=cv.bbox("all")),
                                              cv.itemconfig(wid, width=e.width)))
        cv.bind("<Configure>", lambda e: cv.itemconfig(wid, width=e.width))
        self._sidebar_content(inner)

    def _section(self, p, title, accent=BLUE):
        o = tk.Frame(p, bg=BG2, highlightthickness=1, highlightbackground=SEP)
        o.pack(fill="x", pady=(0, 7))
        hrow = tk.Frame(o, bg=BG2)
        hrow.pack(fill="x")
        tk.Frame(hrow, bg=accent, width=3).pack(side="left", fill="y")
        tk.Label(hrow, text=f" {title}", font=("Consolas", 8, "bold"), fg=accent,
                 bg=BG2, anchor="w", padx=8, pady=6).pack(side="left", fill="x")
        inn = tk.Frame(o, bg=BG2, padx=10, pady=6)
        inn.pack(fill="x")
        return inn

    def _lrow(self, p, label, w=13):
        r = tk.Frame(p, bg=BG2); r.pack(fill="x", pady=2)
        tk.Label(r, text=label, font=("Consolas", 8), fg=SUB, bg=BG2,
                 width=w, anchor="w").pack(side="left", padx=(2,0))
        return r

    def _combo(self, p, vals, default):
        cb = ttk.Combobox(p, values=vals, state="readonly", width=16,
                          style="D.TCombobox", font=FM)
        cb.set(default); cb.pack(side="left", fill="x", expand=True)
        return cb

    def _entry(self, p, default="", show=None):
        e = tk.Entry(p, bg=BG3, fg=TEXT, insertbackground=TEXT, relief="flat",
                     font=FM, width=16, highlightthickness=1,
                     highlightbackground=SEP, highlightcolor=BLUE)
        if show: e.config(show=show)
        e.insert(0, default); e.pack(side="left", fill="x", expand=True)
        return e

    def _sidebar_content(self, p):
        # ── Mode ──────────────────────────────────────────────────────────────
        s0 = self._section(p, "MODE", AMBER)
        self.dry_var = tk.BooleanVar(value=True)
        rf = self._lrow(s0, "Mode")
        tk.Radiobutton(rf, text="● Paper", variable=self.dry_var, value=True,
                       bg=BG2, fg=GREEN, selectcolor=BG3, activebackground=BG2,
                       font=FMS, command=self._on_mode).pack(side="left")
        tk.Radiobutton(rf, text="⚡ Live!", variable=self.dry_var, value=False,
                       bg=BG2, fg=RED, selectcolor=BG3, activebackground=BG2,
                       font=FMS, command=self._on_mode).pack(side="left", padx=8)

        # ── Claude ────────────────────────────────────────────────────────────
        claude_outer = tk.Frame(p, bg=PURPLE, padx=2, pady=2)
        claude_outer.pack(fill="x", pady=(0, 8))
        ci = tk.Frame(claude_outer, bg=BG2)
        ci.pack(fill="x")
        tk.Frame(ci, bg=PURPLE, height=2).pack(fill="x")
        th = tk.Frame(ci, bg="#1e0f2e")
        th.pack(fill="x")
        tk.Label(th, text="  🤖  CLAUDE AI", font=("Consolas", 9, "bold"),
                 fg=PURPLE, bg="#1e0f2e", pady=6, anchor="w").pack(side="left")
        tk.Label(th, text="optional", font=FMS, fg=MUTED, bg="#1e0f2e").pack(side="right", padx=8)
        ci2 = tk.Frame(ci, bg=BG2, padx=10, pady=6)
        ci2.pack(fill="x")

        self.claude_enabled = tk.BooleanVar(value=False)
        self.claude_toggle  = tk.Button(ci2,
            text="  OFF  —  click to enable",
            font=("Consolas", 9, "bold"), bg=BG3, fg=MUTED,
            relief="flat", cursor="hand2", pady=5, anchor="w",
            command=self._toggle_claude)
        self.claude_toggle.pack(fill="x", pady=(0, 3))

        # Claude role badges
        role_frame = tk.Frame(ci2, bg=BG2)
        role_frame.pack(fill="x", pady=(0, 4))
        for role, col in [("VETO", RED), ("BOOST", CYAN), ("DYN SL/TP", PURPLE)]:
            tk.Label(role_frame, text=role, font=("Consolas", 7, "bold"),
                     fg=col, bg="#0d0a14", padx=5, pady=2,
                     relief="flat").pack(side="left", padx=(0, 3))

        # Cost tracker
        cost_frame = tk.Frame(ci2, bg=BG2)
        cost_frame.pack(fill="x", pady=(0, 4))
        tk.Label(cost_frame, text="Session cost:",
                 font=("Consolas", 8), fg=MUTED, bg=BG2).pack(side="left")
        self._cost_lbl = tk.Label(cost_frame, text="$0.0000",
                                   font=("Consolas", 8, "bold"), fg=DIM, bg=BG2)
        self._cost_lbl.pack(side="left", padx=(4, 0))
        self._calls_lbl = tk.Label(cost_frame, text="0 calls",
                                    font=("Consolas", 8), fg=DIM, bg=BG2)
        self._calls_lbl.pack(side="right")

        def _open_console(_=None):
            import webbrowser
            webbrowser.open("https://console.anthropic.com/settings/keys")
        lnk = tk.Label(ci2, text="→ console.anthropic.com/settings/keys",
                       font=("Consolas", 8), fg=CYAN, bg=BG2, cursor="hand2", anchor="w")
        lnk.pack(fill="x")
        lnk.bind("<Button-1>", _open_console)
        lnk.bind("<Enter>", lambda e: lnk.config(fg=TEXT))
        lnk.bind("<Leave>", lambda e: lnk.config(fg=CYAN))

        tk.Label(ci2, text="Requires $5 credit to activate API",
                 font=("Consolas", 8), fg=DIM, bg=BG2, anchor="w").pack(fill="x", pady=(0, 6))

        kr = tk.Frame(ci2, bg=BG2); kr.pack(fill="x", pady=(0, 4))
        self.claude_entry = tk.Entry(kr, bg="#140a20", fg=PURPLE, insertbackground=PURPLE,
                                      relief="flat", font=FM, show="*",
                                      highlightthickness=1, highlightbackground=PURPLE,
                                      highlightcolor="#e879f9", state="disabled")
        self.claude_entry.pack(side="left", fill="x", expand=True, ipady=5)

        self._claude_show = False
        def _tog_show():
            self._claude_show = not self._claude_show
            self.claude_entry.config(show="" if self._claude_show else "*")
            self._show_btn.config(text="🙈" if self._claude_show else "👁")
        self._show_btn = tk.Button(kr, text="👁", command=_tog_show,
                                    bg="#1e0f2e", fg=PURPLE, relief="flat",
                                    font=FM, cursor="hand2", padx=6,
                                    state="disabled", activebackground=BG3)
        self._show_btn.pack(side="left", padx=(3, 0), ipady=5)

        tr = tk.Frame(ci2, bg=BG2); tr.pack(fill="x")
        self.claude_status = tk.Label(tr, text="OFF — local signals only",
                                       font=FMS, fg=MUTED, bg=BG2, anchor="w")
        self.claude_status.pack(side="left", fill="x", expand=True)
        self._test_btn = tk.Button(tr, text="Test ▶", command=self._test_claude,
                                    bg=BG3, fg=MUTED, relief="flat", font=FMS,
                                    cursor="hand2", padx=8, pady=3,
                                    state="disabled", activebackground=BG3)
        self._test_btn.pack(side="right")

        # ── MEXC Keys ─────────────────────────────────────────────────────────
        s2 = self._section(p, "MEXC API KEYS  (live trading only)", BLUE)
        tk.Label(s2, text="mexc.com → Profile → API Management\nEnable Contract Trading — NO withdrawals",
                 font=("Consolas", 8), fg=DIM, bg=BG2, justify="left",
                 wraplength=250).pack(fill="x", pady=(0, 6))
        self.mexc_key_e = self._entry(self._lrow(s2, "API key"), "")
        self.mexc_sec_e = self._entry(self._lrow(s2, "Secret"),  "", show="*")

        # ── Trade Config ──────────────────────────────────────────────────────
        s3 = self._section(p, "TRADE CONFIG", CYAN)
        self.pair_cb = self._combo(self._lrow(s3, "Pair"), PAIRS, "BTC_USDT")
        self.pair_cb.bind("<<ComboboxSelected>>", self._on_pair)

        self.lev_cb  = self._combo(self._lrow(s3, "Leverage"),
            self._lev_opts("BTC_USDT"), "10x")
        self.lev_cb.bind("<<ComboboxSelected>>", self._on_lev)
        self.lev_warn_inline = tk.Label(s3, text="10x: 10% move = 100% loss",
            font=("Consolas", 8), fg=AMBER, bg=BG2, anchor="w", wraplength=240)
        self.lev_warn_inline.pack(fill="x", pady=(0, 3))

        self.margin_e= self._entry(self._lrow(s3, "Margin USDT"), "50")
        self._tf_lbl_var = tk.StringVar(value="Trend TF")
        self.tf_cb   = self._combo(self._lrow(s3, "Trend TF"),
            ["Min1","Min5","Min15","Min30","Min60","Hour4","Day1"], "Min5")

        # Dual timeframe toggle
        dtf_row = tk.Frame(s3, bg=BG2); dtf_row.pack(fill="x", pady=(2,4))
        self.dual_tf_var = tk.BooleanVar(value=True)
        tk.Checkbutton(dtf_row, text="Dual TF  (Min5 trend + Min1 entry)",
                       variable=self.dual_tf_var,
                       bg=BG2, fg=CYAN, selectcolor=BG3,
                       activebackground=BG2, font=("Consolas",8,"bold"),
                       command=self._on_dual_tf).pack(side="left")
        self._dtf_lbl = tk.Label(dtf_row, text="ON",
                                  font=("Consolas",8,"bold"), fg=CYAN, bg=BG2)
        self._dtf_lbl.pack(side="left", padx=(6,0))
        self.int_cb  = self._combo(self._lrow(s3, "Scan interval"),
            ["10s","15s","20s","25s","30s","35s","40s","45s",
             "60s","90s","2 min","3 min","5 min","10 min"], "30s")
        self.int_cb.bind("<<ComboboxSelected>>", self._on_interval)
        self._ivl_hint = tk.Label(s3, text="",
            font=("Consolas", 8), fg=CYAN, bg=BG2, anchor="w", wraplength=240)
        self._ivl_hint.pack(fill="x", pady=(0, 3))
        self.sl_cb   = self._combo(self._lrow(s3, "Stop loss"),
            ["0.05%","0.08%","0.10%","0.12%","0.15%","0.18%","0.20%",
             "0.25%","0.30%","0.35%","0.40%","0.50%","0.60%","0.70%",
             "0.80%","0.90%","1.0%","1.5%","2.0%","2.5%","3.0%",
             "4.0%","5.0%","7.5%","10.0%","15.0%","20.0%"], "0.8%")
        self.tp_cb   = self._combo(self._lrow(s3, "Take profit"),
            ["0.05%","0.08%","0.10%","0.12%","0.15%","0.18%","0.20%",
             "0.25%","0.30%","0.35%","0.40%","0.50%","0.60%","0.70%",
             "0.80%","0.90%","1.0%","1.2%","1.5%","2.0%","2.5%","3.0%",
             "4.0%","5.0%","7.5%","10.0%","15.0%","20.0%","30.0%","50.0%"], "2.0%")
        self.thr_cb  = self._combo(self._lrow(s3, "Min signal"),
            ["2.0/9","3.0/9","4.0/9","5.0/9","6.0/9","7.0/9","8.0/9"], "6.0/9")

        # ── Multi-trade / Hedge ───────────────────────────────────────────────
        # ── Scan Pairs ───────────────────────────────────────────────────────────
        sp = self._section(p, "SCAN PAIRS", CYAN)
        tk.Label(sp, text="Toggle pairs to scan. Fewer = faster cycles.",
                 font=("Consolas", 8), fg=DIM, bg=BG2,
                 wraplength=250, justify="left").pack(fill="x", pady=(0, 6))

        self._pair_vars = {}
        grid = tk.Frame(sp, bg=BG2)
        grid.pack(fill="x")
        for i, pair in enumerate(PAIRS):
            sym = pair_label(pair)
            col = PAIR_COL.get(pair, CYAN)
            var = tk.BooleanVar(value=True)
            self._pair_vars[pair] = var
            cb = tk.Checkbutton(grid, text=sym, variable=var,
                                bg=BG2, fg=col, selectcolor=BG3,
                                activebackground=BG2, activeforeground=col,
                                font=("Consolas", 8, "bold"),
                                command=self._on_pair_toggle)
            cb.grid(row=i//3, column=i%3, sticky="w", padx=(0,6), pady=1)

        # Select all / none buttons
        btn_row = tk.Frame(sp, bg=BG2)
        btn_row.pack(fill="x", pady=(4,0))
        tk.Button(btn_row, text="All", font=("Consolas", 8),
                  bg=BG3, fg=CYAN, relief="flat", cursor="hand2",
                  command=lambda: self._set_all_pairs(True)).pack(side="left", padx=(0,4))
        tk.Button(btn_row, text="None", font=("Consolas", 8),
                  bg=BG3, fg=MUTED, relief="flat", cursor="hand2",
                  command=lambda: self._set_all_pairs(False)).pack(side="left", padx=(0,4))
        tk.Button(btn_row, text="Crypto only", font=("Consolas", 8),
                  bg=BG3, fg=AMBER, relief="flat", cursor="hand2",
                  command=lambda: self._set_preset(["BTC_USDT","ETH_USDT","SOL_USDT",
                                                     "XRP_USDT","DOGE_USDT","PEPE_USDT",
                                                     "SUI_USDT"])).pack(side="left", padx=(0,4))
        tk.Button(btn_row, text="Majors", font=("Consolas", 8),
                  bg=BG3, fg=GREEN, relief="flat", cursor="hand2",
                  command=lambda: self._set_preset(["BTC_USDT","ETH_USDT",
                                                     "SOL_USDT","XRP_USDT"])).pack(side="left")

        s4 = self._section(p, "MULTI-TRADE & HEDGING", AMBER)

        mr = self._lrow(s4, "Max trades")
        self.max_trades_cb = self._combo(mr,
            ["1 (single)","2","3","5","10","Unlimited"], "2")

        # Multi-long stacking (extra contracts on high confidence)
        sr = self._lrow(s4, "Stack longs")
        self.stack_var = tk.BooleanVar(value=False)
        tk.Checkbutton(sr, text="Enable", variable=self.stack_var,
                       bg=BG2, fg=CYAN, selectcolor=BG3,
                       activebackground=BG2, font=FMS).pack(side="left")

        self.stack_thresh_cb = self._combo(self._lrow(s4, "Stack at"),
            ["5.0/9","5.5/9","6.0/9","6.5/9","7.0/9","7.5/9","8.0/9","9.0/9"], "7.0/9")
        self.stack_max_cb = self._combo(self._lrow(s4, "Max stack"),
            ["2x","3x","4x","5x"], "2x")

        tk.Label(s4,
            text="Stacking opens extra LONG contracts\nwhen score exceeds threshold,\nimitating buying multiple contracts.",
            font=("Consolas", 8), fg=DIM, bg=BG2,
            justify="left", wraplength=250).pack(fill="x", pady=(2, 6))

        tk.Frame(s4, bg=SEP, height=1).pack(fill="x", pady=(0,6))

        hr2 = self._lrow(s4, "Hedging")
        self.hedge_var = tk.BooleanVar(value=False)
        tk.Checkbutton(hr2, text="Enable", variable=self.hedge_var,
                       bg=BG2, fg=AMBER, selectcolor=BG3,
                       activebackground=BG2, font=FMS).pack(side="left")

        tk.Label(s4,
            text="Opens opposite position to lock\nprofits when in drawdown.",
            font=("Consolas", 8), fg=DIM, bg=BG2,
            justify="left", wraplength=250).pack(fill="x", pady=(2, 0))

        self.hedge_thresh_cb = self._combo(self._lrow(s4, "Hedge at"),
            ["-0.5%","-1.0%","-1.5%","-2.0%","-2.5%","-3.0%","-5.0%"], "-3.0%")

        # ── Adaptive Threshold ────────────────────────────────────────────────
        s5 = self._section(p, "ADAPTIVE THRESHOLD", CYAN)

        ar = tk.Frame(s5, bg=BG2); ar.pack(fill="x", pady=(0,4))
        self.adaptive_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ar, text="Enable", variable=self.adaptive_var,
                       bg=BG2, fg=CYAN, selectcolor=BG3,
                       activebackground=BG2, font=FMS,
                       command=self._on_adaptive_toggle).pack(side="left")
        self._adaptive_status_lbl = tk.Label(ar, text="ON",
            font=("Consolas", 8, "bold"), fg=CYAN, bg=BG2)
        self._adaptive_status_lbl.pack(side="left", padx=(8,0))

        tk.Label(s5,
            text="Relaxes signal threshold during\nlong HOLD streaks to find more trades.",
            font=("Consolas", 8), fg=DIM, bg=BG2,
            justify="left", wraplength=250).pack(fill="x", pady=(0,4))

        self._adaptive_info = tk.Label(s5,
            text="Relaxes after 20 cycles → -0.5\n              40 cycles → -1.0",
            font=("Consolas", 8), fg=DIM, bg=BG2,
            justify="left")
        self._adaptive_info.pack(fill="x")

        # ── Overnight Mode ────────────────────────────────────────────────
        night_outer = tk.Frame(p, bg=TEAL, padx=2, pady=2)
        night_outer.pack(fill="x", pady=(0, 7))
        ni = tk.Frame(night_outer, bg=BG2)
        ni.pack(fill="x")
        tk.Frame(ni, bg=TEAL, height=2).pack(fill="x")
        nth = tk.Frame(ni, bg="#0a1f1f")
        nth.pack(fill="x")
        tk.Label(nth, text="  🌙  OVERNIGHT MODE", font=("Consolas", 9, "bold"),
                 fg=TEAL, bg="#0a1f1f", pady=6, anchor="w").pack(side="left")
        ni2 = tk.Frame(ni, bg=BG2, padx=10, pady=6)
        ni2.pack(fill="x")

        self.overnight_var = tk.BooleanVar(value=False)
        self.overnight_btn = tk.Button(ni2,
            text="  OFF  —  click to enable",
            font=("Consolas", 9, "bold"), bg=BG3, fg=MUTED,
            relief="flat", cursor="hand2", pady=5, anchor="w",
            command=self._toggle_overnight)
        self.overnight_btn.pack(fill="x", pady=(0, 4))

        tk.Label(ni2,
            text="Relaxes filters for low-volume\novernight sessions:",
            font=("Consolas", 8), fg=DIM, bg=BG2,
            justify="left", wraplength=250).pack(fill="x", pady=(0, 3))

        self._overnight_detail = tk.Label(ni2,
            text="  • Min signal  6/9 → 5/9\n"
                 "  • Adaptive kicks in at 10cy\n"
                 "  • Dual TF RSI filter +10 pts\n"
                 "  • Adaptive floor 4.0 → 3.5",
            font=("Consolas", 8), fg=MUTED, bg=BG2, justify="left")
        self._overnight_detail.pack(fill="x")

        self.lev_warn = tk.Label(p, text="", font=FMS, fg=AMBER, bg=BG,
                                  wraplength=270, justify="left", padx=2, pady=2)
        self.lev_warn.pack(fill="x")

        # ── Buttons ────────────────────────────────────────────────────────────
        self.start_btn = tk.Button(
            p, text="▶  START BOT",
            font=("Consolas", 11, "bold"), bg=GREEN, fg=BG,
            activebackground="#00b85a", relief="flat", pady=12,
            cursor="hand2", command=self.toggle_bot)
        self.start_btn.pack(fill="x", pady=(6, 3))

        tk.Button(p, text="↺  Reset Defaults", command=self._reset_defaults,
                  bg=BG3, fg=CYAN, relief="flat", font=FMS,
                  cursor="hand2").pack(fill="x", pady=(0,3))

        tk.Button(p, text="💾  Save Keys", command=self._save_keys,
                  bg=BG3, fg=SUB, relief="flat", font=FMS,
                  cursor="hand2", pady=5).pack(fill="x", pady=(0, 8))

    # ── METRICS BAR ───────────────────────────────────────────────────────────
    def _build_metrics(self, parent):
        mf = tk.Frame(parent, bg=BG)
        mf.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for i in range(6): mf.columnconfigure(i, weight=1)

        specs = [
            ("SESSION P&L",  "$0.00",    "+0.00%",           TEXT),
            ("WIN RATE",     "—",        "— W / — L",        TEXT),
            ("TRADES",       "0",        "avg  $—",          TEXT),
            ("BALANCE",      "1,000 USDT", "starting capital", TEXT),
            ("OPEN POS",     "0",        "0 hedged",         MUTED),
            ("LIQS",         "0",        "0.0% of trades",   MUTED),
            ("UPTIME",       "—",        "0 cycles",         MUTED),
            ("LAST SIGNAL",  "—",        "waiting…",         MUTED),
        ]
        self.mv = []; self.ms = []
        for i in range(8): mf.columnconfigure(i, weight=1)
        for i, (lbl, val, sub, col) in enumerate(specs):
            c = tk.Frame(mf, bg=BG2, highlightthickness=1, highlightbackground=SEP)
            c.grid(row=0, column=i, sticky="ew", padx=(0, 5 if i < 7 else 0))
            tk.Label(c, text=lbl, font=("Consolas", 7, "bold"), fg=MUTED, bg=BG2, pady=4).pack()
            v = tk.Label(c, text=val, font=("Consolas", 12, "bold"), fg=col, bg=BG2); v.pack()
            s = tk.Label(c, text=sub, font=("Consolas", 8), fg=DIM, bg=BG2, pady=4); s.pack()
            self.mv.append(v); self.ms.append(s)

    # ── TABS ──────────────────────────────────────────────────────────────────
    def _build_tabs(self, parent):
        self.nb = ttk.Notebook(parent)
        self.nb.grid(row=2, column=0, sticky="nsew")

        for pair in PAIRS:
            tab = tk.Frame(self.nb, bg=BG4)
            sym_label = pair_label(pair)
            self.nb.add(tab, text=f" {sym_label} ")
            cp = ChartPanel(tab, pair, PAIR_COL[pair]) if MPLOT else None
            if not MPLOT:
                tk.Label(tab, text="pip install matplotlib  to enable charts",
                         bg=BG4, fg=MUTED, font=FM).pack(expand=True)
            self.chart_panels[pair] = cp

        log_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(log_tab, text="  Log  ")
        self._build_log(log_tab)

        trades_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(trades_tab, text="  Trades  ")
        self._build_trades_tab(trades_tab)

        ai_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(ai_tab, text="  🤖 AI  ")
        self._build_ai_tab(ai_tab)

        self.nb.bind("<<NotebookTabChanged>>", self._on_tab)

    def _build_claude_panel(self, parent):
        """Persistent Claude AI reasoning + live signal scores bar."""
        self._claude_panel = tk.Frame(parent, bg=BG2,
                                       highlightthickness=1,
                                       highlightbackground=SEP)
        self._claude_panel.grid(row=1, column=0, sticky="ew",
                                 pady=(0, 6), ipady=0)

        # Left accent bar
        tk.Frame(self._claude_panel, bg=PURPLE, width=3).pack(side="left", fill="y")

        # Claude reasoning text block (full width now — signal scores moved to charts)
        right_block = tk.Frame(self._claude_panel, bg=BG2)
        right_block.pack(side="left", fill="both", expand=True,
                         padx=10, pady=5)

        hrow = tk.Frame(right_block, bg=BG2)
        hrow.pack(fill="x")
        tk.Label(hrow, text="🤖  CLAUDE REASONING",
                 font=("Consolas", 7, "bold"), fg=PURPLE,
                 bg=BG2).pack(side="left")
        self._claude_panel_status = tk.Label(
            hrow, text="● OFF — enable Claude in sidebar",
            font=("Consolas", 7), fg=DIM, bg=BG2)
        self._claude_panel_status.pack(side="right")

        self._claude_reason_lbl = tk.Label(
            right_block,
            text="Start the bot — Claude will analyse every signal and explain HOLD decisions.",
            font=("Consolas", 9), fg=MUTED, bg=BG2,
            anchor="w", justify="left", wraplength=700)
        self._claude_reason_lbl.pack(fill="x", pady=(2, 0))

    def _update_claude_panel(self, signals, reasoning=None):
        """Update Claude reasoning text in the persistent panel."""
        def _do():
            # Claude reasoning text + status
            if reasoning:
                self._claude_reason_lbl.config(text=reasoning, fg=SUB)
                self._claude_panel_status.config(text="● LIVE", fg=GREEN)
            elif self.claude_enabled.get():
                self._claude_panel_status.config(
                    text="● Active — analyses every signal and HOLD cycle", fg=AMBER)
            else:
                self._claude_panel_status.config(
                    text="● OFF — enable Claude in sidebar", fg=DIM)
                self._claude_reason_lbl.config(
                    text="Enable Claude AI in the sidebar → toggle ON → paste key → Test.",
                    fg=DIM)
        self.root.after(0, _do)



    def _ai_log_event(self, pid, event, reason, col):
        """Record an AI decision event for a position — shown in the AI tab."""
        import time as _t
        if pid not in self._ai_trade_log:
            self._ai_trade_log[pid] = []
        self._ai_trade_log[pid].append({
            "time":   _t.strftime("%H:%M:%S"),
            "event":  event,
            "reason": reason,
            "col":    col,
        })
        # Keep last 30 events per position
        self._ai_trade_log[pid] = self._ai_trade_log[pid][-30:]
        self.root.after(0, self._refresh_ai_tab)

    def _build_ai_tab(self, parent):
        """AI reasoning tab — one card per open position showing Claude's logic."""
        # Outer scrollable container
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG3)
        header.pack(fill="x")
        tk.Frame(header, bg=PURPLE, width=3).pack(side="left", fill="y")
        tk.Label(header, text="  🤖  AI TRADE ANALYSIS",
                 font=("Consolas", 9, "bold"), fg=PURPLE, bg=BG3,
                 pady=7).pack(side="left")
        self._ai_tab_status = tk.Label(header,
            text="No open positions", font=("Consolas", 8),
            fg=DIM, bg=BG3)
        self._ai_tab_status.pack(side="right", padx=10)

        tk.Frame(outer, bg=SEP, height=1).pack(fill="x")

        # Scrollable body
        scroll_outer = tk.Frame(outer, bg=BG)
        scroll_outer.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(scroll_outer, orient="vertical")
        sb.pack(side="right", fill="y")
        cv = tk.Canvas(scroll_outer, bg=BG, yscrollcommand=sb.set,
                       highlightthickness=0)
        cv.pack(fill="both", expand=True)
        sb.config(command=cv.yview)
        self._ai_tab_frame = tk.Frame(cv, bg=BG)
        self._ai_tab_win   = cv.create_window((0,0), window=self._ai_tab_frame,
                                               anchor="nw")
        cv.bind("<Configure>",
            lambda e: cv.itemconfig(self._ai_tab_win, width=e.width))
        self._ai_tab_frame.bind("<Configure>",
            lambda e: cv.configure(scrollregion=cv.bbox("all")))
        self._ai_tab_canvas = cv

        # Bind mousewheel
        def _mw(e):
            cv.yview_scroll(-1 if e.delta > 0 else 1, "units")
        cv.bind("<MouseWheel>", _mw)
        cv.bind("<Button-4>", lambda e: cv.yview_scroll(-1, "units"))
        cv.bind("<Button-5>", lambda e: cv.yview_scroll( 1, "units"))

        self._refresh_ai_tab()

    def _refresh_ai_tab(self):
        """Rebuild the AI tab — one card per open position."""
        if not hasattr(self, "_ai_tab_frame"):
            return

        for w in self._ai_tab_frame.winfo_children():
            w.destroy()

        positions = self.state.positions
        if not positions:
            tk.Label(self._ai_tab_frame,
                     text="No open positions — AI analysis will appear here when trades are open.",
                     font=("Consolas", 10), fg=MUTED, bg=BG,
                     pady=30, padx=20, justify="left").pack(anchor="w")
            try: self._ai_tab_status.config(text="No open positions")
            except Exception: pass
            return

        try:
            self._ai_tab_status.config(
                text=f"{len(positions)} open position{'s' if len(positions)>1 else ''}")
        except Exception:
            pass

        def _fp(v):
            if v < 0.001:  return f"${v:.6f}"
            if v < 0.1:    return f"${v:.5f}"
            if v < 10:     return f"${v:.4f}"
            if v >= 1000:  return f"${v:,.1f}"
            return f"${v:,.2f}"

        for pid, pos in positions.items():
            cur_px   = self.current_prices.get(pos.symbol, pos.entry_price)
            sig      = self.pair_signals.get(pos.symbol) or {}
            events   = self._ai_trade_log.get(pid, [])
            d        = pos.direction
            dcol     = GREEN if d == "LONG" else RED
            pair_col = PAIR_COL.get(pos.symbol, CYAN)

            raw_chg  = ((cur_px - pos.entry_price)/pos.entry_price if d=="LONG"
                        else (pos.entry_price - cur_px)/pos.entry_price)
            margin_pct = raw_chg * pos.leverage * 100
            price_pct  = raw_chg * 100
            pnl_usd    = raw_chg * pos.leverage * pos.margin
            pnl_col    = GREEN if pnl_usd >= 0 else RED

            tp_total = abs(pos.take_profit - pos.entry_price)
            tp_left  = abs(pos.take_profit - cur_px)
            tp_progress = max(0, min(100, (1 - tp_left/tp_total)*100)) if tp_total else 0

            sl_total = abs(pos.stop_loss - pos.entry_price)
            sl_left  = abs(cur_px - pos.stop_loss)
            sl_progress = max(0, min(100, (1 - sl_left/sl_total)*100)) if sl_total else 0

            try:
                from datetime import datetime, timezone
                opened = datetime.fromisoformat(pos.opened_at.replace("Z","+00:00"))
                secs   = int((datetime.now(timezone.utc) - opened).total_seconds())
                dur    = f"{secs//3600}h {(secs%3600)//60}m" if secs>=3600 else f"{secs//60}m {secs%60}s"
            except Exception:
                dur = "—"

            fee_cost = round(pos.margin * pos.leverage * 0.001 * 2, 4)

            # ── Card ─────────────────────────────────────────────────────────
            card = tk.Frame(self._ai_tab_frame, bg=BG2,
                            highlightthickness=1, highlightbackground=SEP)
            card.pack(fill="x", padx=10, pady=(8,0))

            # Card header bar
            hdr = tk.Frame(card, bg=BG3)
            hdr.pack(fill="x")
            tk.Frame(hdr, bg=pair_col, width=4).pack(side="left", fill="y")
            tk.Label(hdr, text=f"  {pair_label(pos.symbol)}",
                     font=("Consolas", 11, "bold"), fg=pair_col, bg=BG3,
                     pady=6).pack(side="left")
            tk.Label(hdr, text=f"{d}  {pos.leverage}x",
                     font=("Consolas", 10, "bold"), fg=dcol, bg=BG3,
                     padx=10).pack(side="left")
            tk.Label(hdr,
                     text=f"{'+'if pnl_usd>=0 else ''}${pnl_usd:.2f}  ({margin_pct:+.1f}% margin)",
                     font=("Consolas", 10, "bold"), fg=pnl_col, bg=BG3,
                     padx=10).pack(side="left")
            tk.Label(hdr, text=f"open {dur}",
                     font=("Consolas", 8), fg=DIM, bg=BG3).pack(side="right", padx=10)

            # Body: two columns — left=stats, right=AI event log
            body = tk.Frame(card, bg=BG2)
            body.pack(fill="both", expand=True, padx=1)
            body.columnconfigure(0, weight=2)
            body.columnconfigure(1, weight=3)

            # ── Left column: position stats + indicators ──────────────────
            left_col = tk.Frame(body, bg=BG2)
            left_col.grid(row=0, column=0, sticky="nsew", padx=(10,4), pady=8)

            def _stat(parent, label, val, vcol=None):
                r = tk.Frame(parent, bg=BG2)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=label, font=("Consolas", 8), fg=MUTED,
                         bg=BG2, width=16, anchor="w").pack(side="left")
                tk.Label(r, text=val, font=("Consolas", 8, "bold"),
                         fg=vcol or TEXT, bg=BG2).pack(side="left")

            _stat(left_col, "Entry",       _fp(pos.entry_price))
            _stat(left_col, "Current",     _fp(cur_px),
                  GREEN if pnl_usd>=0 else RED)
            _stat(left_col, "Take Profit", _fp(pos.take_profit), "#00e676")
            _stat(left_col, "Stop Loss",   _fp(pos.stop_loss),   "#ff3d57")
            _stat(left_col, "Liq Price",   _fp(pos.liq_price),   "#f783ac")
            _stat(left_col, "P&L",
                  f"{'+'if pnl_usd>=0 else ''}${pnl_usd:.3f}  ({price_pct:+.3f}% price)",
                  pnl_col)
            _stat(left_col, "Round-trip fee", f"≈${fee_cost:.3f}", AMBER)

            # TP progress bar
            bar_frame = tk.Frame(left_col, bg=BG2)
            bar_frame.pack(fill="x", pady=(6,2))
            tk.Label(bar_frame, text="TP progress", font=("Consolas", 7),
                     fg=MUTED, bg=BG2).pack(anchor="w")
            bar_bg = tk.Frame(bar_frame, bg=BG3, height=6)
            bar_bg.pack(fill="x")
            bar_bg.update_idletasks()
            bar_w  = bar_bg.winfo_width() or 200
            fill_w = max(2, int(bar_w * tp_progress / 100))
            bar_fill = tk.Frame(bar_bg,
                bg=GREEN if tp_progress > 60 else (AMBER if tp_progress > 30 else MUTED),
                height=6, width=fill_w)
            bar_fill.place(x=0, y=0)
            tk.Label(bar_frame, text=f"{tp_progress:.0f}% to TP",
                     font=("Consolas", 7), fg=DIM, bg=BG2).pack(anchor="e")

            # SL danger bar
            bar_frame2 = tk.Frame(left_col, bg=BG2)
            bar_frame2.pack(fill="x", pady=(2,6))
            tk.Label(bar_frame2, text="SL proximity", font=("Consolas", 7),
                     fg=MUTED, bg=BG2).pack(anchor="w")
            bar_bg2 = tk.Frame(bar_frame2, bg=BG3, height=6)
            bar_bg2.pack(fill="x")
            fill_w2 = max(2, int((bar_bg.winfo_width() or 200) * sl_progress / 100))
            bar_fill2 = tk.Frame(bar_bg2,
                bg=RED if sl_progress > 70 else (AMBER if sl_progress > 40 else DIM),
                height=6, width=fill_w2)
            bar_fill2.place(x=0, y=0)
            tk.Label(bar_frame2, text=f"{sl_progress:.0f}% toward SL",
                     font=("Consolas", 7), fg=DIM, bg=BG2).pack(anchor="e")

            # Current indicators
            if sig:
                tk.Frame(left_col, bg=SEP, height=1).pack(fill="x", pady=4)
                tk.Label(left_col, text="CURRENT INDICATORS",
                         font=("Consolas", 7, "bold"), fg=MUTED, bg=BG2).pack(anchor="w")
                ind_grid = tk.Frame(left_col, bg=BG2)
                ind_grid.pack(fill="x", pady=2)
                ind_data = [
                    ("Trend",    sig.get("trend","—"),
                     GREEN if sig.get("trend")=="BULL" else RED),
                    ("RSI",      f"{sig.get('rsi',0):.0f}",
                     RED if sig.get("rsi",50)>70 else (GREEN if sig.get("rsi",50)<30 else SUB)),
                    ("StochRSI", f"{sig.get('srsi',0):.0f}",
                     RED if sig.get("srsi",50)>80 else (GREEN if sig.get("srsi",50)<20 else SUB)),
                    ("MACD",     "▲" if sig.get("macd_h",0)>0 else "▼",
                     GREEN if sig.get("macd_h",0)>0 else RED),
                    ("OBV",      "▲" if sig.get("obv_slope",0)>0 else "▼",
                     GREEN if sig.get("obv_slope",0)>0 else RED),
                    ("BB%B",     f"{sig.get('pct_b',0.5):.2f}", SUB),
                    ("ATR",      f"{sig.get('atr_pct',0):.3f}%",
                     GREEN if sig.get("atr_ok") else RED),
                    ("Score",    f"{sig.get('score',0)}/9  {sig.get('direction','—')}",
                     CYAN if sig.get("score",0)>=7 else (
                         GREEN if sig.get("direction")=="LONG" else
                         RED if sig.get("direction")=="SHORT" else MUTED)),
                ]
                for row_i, (name, val, col) in enumerate(ind_data):
                    r = row_i // 2
                    c = (row_i % 2) * 2
                    tk.Label(ind_grid, text=name, font=("Consolas", 7),
                             fg=MUTED, bg=BG2).grid(row=r, column=c, sticky="w", padx=(0,4))
                    tk.Label(ind_grid, text=val, font=("Consolas", 7, "bold"),
                             fg=col, bg=BG2).grid(row=r, column=c+1, sticky="w", padx=(0,12))

            # ── Right column: AI event log ────────────────────────────────
            tk.Frame(body, bg=SEP, width=1).grid(row=0, column=0, sticky="ns",
                                                   padx=(0,0), pady=4)
            right_col = tk.Frame(body, bg=BG2)
            right_col.grid(row=0, column=1, sticky="nsew", padx=(10,10), pady=8)

            tk.Label(right_col, text="AI DECISION LOG",
                     font=("Consolas", 8, "bold"), fg=PURPLE, bg=BG2).pack(anchor="w")
            tk.Frame(right_col, bg=SEP, height=1).pack(fill="x", pady=(2,6))

            if not events:
                tk.Label(right_col,
                         text=("No AI decisions yet for this position.\n"
                               "Claude will analyse on: near-TP, fast adverse moves,\n"
                               "stale trade timeout, and every 5-cycle monitoring check."),
                         font=("Consolas", 8), fg=DIM, bg=BG2,
                         justify="left", wraplength=380).pack(anchor="w")
            else:
                # Show events newest-first
                for ev in reversed(events):
                    ev_frame = tk.Frame(right_col, bg=BG3,
                                        highlightthickness=1,
                                        highlightbackground=SEP)
                    ev_frame.pack(fill="x", pady=(0,4))
                    tk.Frame(ev_frame, bg=ev["col"], width=3).pack(
                        side="left", fill="y")
                    ev_body = tk.Frame(ev_frame, bg=BG3)
                    ev_body.pack(side="left", fill="x", expand=True,
                                 padx=6, pady=4)
                    hrow = tk.Frame(ev_body, bg=BG3)
                    hrow.pack(fill="x")
                    tk.Label(hrow, text=ev["event"],
                             font=("Consolas", 8, "bold"),
                             fg=ev["col"], bg=BG3).pack(side="left")
                    tk.Label(hrow, text=ev["time"],
                             font=("Consolas", 7), fg=DIM,
                             bg=BG3).pack(side="right")
                    tk.Label(ev_body, text=ev["reason"],
                             font=("Consolas", 8), fg=SUB, bg=BG3,
                             anchor="w", justify="left",
                             wraplength=380).pack(fill="x", pady=(1,0))

    def _build_trades_tab(self, parent):
        """Full trade history with P&L, entry/exit, duration."""
        wrap = tk.Frame(parent, bg=BG2, highlightthickness=1, highlightbackground=SEP)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)

        # Header
        hdr = tk.Frame(wrap, bg=BG3)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=CYAN, width=3).pack(side="left", fill="y")
        tk.Label(hdr, text="  TRADE HISTORY", font=("Consolas", 9, "bold"),
                 fg=CYAN, bg=BG3, pady=7).pack(side="left")

        # Summary bar
        self._tlog_summary = tk.Label(wrap, text="No trades yet",
                                       font=("Consolas", 9), fg=MUTED, bg=BG2,
                                       anchor="w", padx=12, pady=4)
        self._tlog_summary.pack(fill="x")
        tk.Frame(wrap, bg=SEP, height=1).pack(fill="x")

        # Column headers
        col_hdr = tk.Frame(wrap, bg=BG3)
        col_hdr.pack(fill="x")
        for txt, w in [("TIME", 80), ("PAIR", 72), ("DIR", 52), ("LEV", 42),
                       ("ENTRY", 82), ("EXIT", 82), ("SIZE", 58),
                       ("P&L $", 72), ("P&L %", 62), ("STATUS", 72)]:
            tk.Label(col_hdr, text=txt, font=("Consolas", 8, "bold"),
                     fg=MUTED, bg=BG3, width=w//8, anchor="w",
                     padx=4, pady=4).pack(side="left")

        # Scrollable trade rows
        outer = tk.Frame(wrap, bg=BG)
        outer.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(outer, orient="vertical")
        sb.pack(side="right", fill="y")
        cv = tk.Canvas(outer, bg=BG, yscrollcommand=sb.set,
                       highlightthickness=0)
        cv.pack(fill="both", expand=True)
        sb.config(command=cv.yview)
        self._trades_frame = tk.Frame(cv, bg=BG)
        self._trades_win   = cv.create_window((0, 0), window=self._trades_frame,
                                               anchor="nw")
        def _on_resize(e):
            cv.itemconfig(self._trades_win, width=e.width)
        cv.bind("<Configure>", _on_resize)
        self._trades_frame.bind(
            "<Configure>",
            lambda e: cv.configure(scrollregion=cv.bbox("all")))
        self._trades_cv = cv

    def _refresh_trades_tab(self):
        """Rebuild the trades tab rows from state.trades."""
        if not hasattr(self, "_trades_frame"): return
        # Clear existing rows
        for w in self._trades_frame.winfo_children():
            w.destroy()

        trades = list(reversed(self.state.trades))  # newest first
        if not trades:
            tk.Label(self._trades_frame, text="No closed trades yet",
                     font=("Consolas", 10), fg=MUTED, bg=BG,
                     pady=20).pack()
            self._tlog_summary.config(text="No trades yet")
            return

        # Summary
        total   = sum(t.get("pnl_usdt", 0) for t in trades)
        wins    = sum(1 for t in trades if t.get("pnl_usdt", 0) >= 0)
        losses  = len(trades) - wins
        wr      = wins / len(trades) * 100 if trades else 0
        sc      = GREEN if total >= 0 else RED
        self._tlog_summary.config(
            text=f"  {len(trades)} trades  |  "
                 f"W:{wins} L:{losses}  WR:{wr:.1f}%  |  "
                 f"Total P&L: {'+'if total>=0 else''}${total:.2f}",
            fg=sc)

        def _fp(v):
            if v is None: return "—"
            if abs(v) < 0.001: return f"${v:.6f}"
            if abs(v) < 0.1:   return f"${v:.5f}"
            if abs(v) < 10:    return f"${v:.4f}"
            if abs(v) >= 1000: return f"${v:,.1f}"
            return f"${v:,.2f}"

        for i, t in enumerate(trades):
            bg = BG2 if i % 2 == 0 else BG3
            row = tk.Frame(self._trades_frame, bg=bg)
            row.pack(fill="x", pady=0)

            pnl      = t.get("pnl_usdt", 0)
            margin   = t.get("margin", 0) or 1
            lev      = t.get("leverage", 1)
            margin_r = pnl / margin * 100
            status   = t.get("status", "—")
            entry    = t.get("entry_price")
            exit_    = t.get("exit_price")
            dirn     = t.get("direction", "—")
            sym      = pair_label(t.get("symbol", "—"))
            hedge    = t.get("hedge", False)
            ts       = t.get("closed_at", "")
            if ts:
                try:   ts = ts[11:19]  # HH:MM:SS from ISO
                except: pass

            pnl_col  = GREEN if pnl >= 0 else (PURPLE if "LIQ" in status else RED)
            dir_col  = GREEN if dirn == "LONG" else RED
            sym_col  = PAIR_COL.get(t.get("symbol",""), CYAN)
            sta_col  = GREEN if "WIN" in status else (PURPLE if "LIQ" in status
                        else AMBER if "MANUAL" in status else RED)

            cells = [
                (ts,                              80, MUTED),
                (f"{sym}{'[H]'if hedge else ''}",  72, sym_col),
                (dirn,                             52, dir_col),
                (f"{lev}x",                        42, BLUE),
                (_fp(entry),                       82, SUB),
                (_fp(exit_),                       82, SUB),
                (f"${margin:.0f}",                 58, MUTED),
                (f"{'+'if pnl>=0 else '-'}${abs(pnl):.2f}", 72, pnl_col),
                (f"{'+'if margin_r>=0 else''}{margin_r:.1f}%", 62, pnl_col),
                (status,                           72, sta_col),
            ]
            for txt, w, fg in cells:
                tk.Label(row, text=txt, font=("Consolas", 9),
                         fg=fg, bg=bg, width=w//8, anchor="w",
                         padx=4, pady=5).pack(side="left")

        self._trades_cv.yview_moveto(0)

    def _build_log(self, parent):
        head = tk.Frame(parent, bg=BG2); head.pack(fill="x")
        tk.Frame(head, bg=BLUE, height=2).pack(fill="x")
        hr = tk.Frame(head, bg=BG2, pady=6); hr.pack(fill="x", padx=12)
        tk.Label(hr, text="LIVE LOG", font=("Consolas", 9, "bold"),
                 fg=MUTED, bg=BG2).pack(side="left")
        tk.Button(hr, text="Clear", font=FMS, bg=BG3, fg=MUTED,
                  relief="flat", cursor="hand2",
                  command=lambda: (self.log_box.config(state="normal"),
                                   self.log_box.delete("1.0", "end"),
                                   self.log_box.config(state="disabled"))).pack(side="right")
        self.log_box = scrolledtext.ScrolledText(
            parent, bg="#070a10", fg=SUB, font=("Consolas", 10),
            relief="flat", wrap="word", state="disabled",
            insertbackground=TEXT, padx=14, pady=10,
            selectbackground=BG3, selectforeground=TEXT)
        self.log_box.pack(fill="both", expand=True)
        for tag, col in [("g", GREEN), ("r", RED), ("b", BLUE), ("a", AMBER),
                          ("p", PURPLE), ("c", CYAN), ("dim", DIM), ("mu", MUTED), ("w", TEXT)]:
            self.log_box.tag_config(tag, foreground=col)

    # ── CHART REFRESH ─────────────────────────────────────────────────────────
    def _initial_load(self):
        """Fetch all pairs on startup so charts and prices load immediately."""
        self._log("Loading market data for all pairs…", DIM)
        def _go():
            # Fetch exact precision from MEXC API first
            try:
                updated = fetch_contract_precision()
                if updated:
                    self._log(f"Precision loaded from MEXC: {' '.join(updated)}", CYAN)
                else:
                    self._log("Using default precisions (MEXC API unavailable)", MUTED)
            except Exception as e:
                self._log(f"Precision fetch failed: {e}", MUTED)

            loaded = 0
            for pair in (self._active_pairs() if hasattr(self, "_pair_vars") else PAIRS):
                try:
                    tf  = self.tf_cb.get() if hasattr(self, 'tf_cb') else "Min5"
                    can = get_klines(pair, tf, 60)
                    tkr = get_ticker(pair)
                    sig = compute_signals(can, tkr, self._thresh())
                    if sig is None: continue
                    self.pair_candles[pair]   = can
                    self.pair_signals[pair]   = sig
                    self.current_prices[pair] = sig["price"]
                    px = sig["price"]
                    self.root.after(0, lambda p=pair, v=px: self._set_price(p, v))
                    cp = self.chart_panels.get(pair)
                    if cp:
                        self.root.after(0, lambda c=can, s=sig, p=cp: p.update(c, s, []))
                    loaded += 1
                    time.sleep(0.35)
                except Exception:
                    pass
            self.root.after(0, lambda: self._log(
                f"Market data loaded for {loaded}/{len(PAIRS)} pairs", CYAN))
            # Update claude panel with best available signal
            valid_sigs = {p: s for p, s in self.pair_signals.items() if s is not None}
            if valid_sigs:
                best = max(valid_sigs.values(), key=lambda s: s.get("score", 0))
                self.root.after(0, lambda s=best: self._update_claude_panel(s))
        threading.Thread(target=_go, daemon=True).start()

    def _chart_cycle(self):
        self._refresh_visible()
        self._refresh_all_prices()
        self._chart_timer = self.root.after(12000, self._chart_cycle)

    def _refresh_all_prices(self):
        """Fetch ticker prices for all pairs to keep header strip updated."""
        def _go():
            for pair in (self._active_pairs() if hasattr(self, "_pair_vars") else PAIRS):
                try:
                    tkr = get_ticker(pair)
                    px  = tkr["last"]
                    if px > 0:
                        self.current_prices[pair] = px
                        self.root.after(0, lambda p=pair, v=px: self._set_price(p, v))
                except Exception:
                    pass
        threading.Thread(target=_go, daemon=True).start()

    def _refresh_visible(self):
        try:
            idx = self.nb.index(self.nb.select())
            if idx < len(PAIRS): self._fetch_pair(PAIRS[idx])
        except Exception: pass

    def _fetch_pair(self, pair):
        def _go():
            try:
                tf  = self.tf_cb.get()
                can = get_klines(pair, tf, 60)
                tkr = get_ticker(pair)
                sig = compute_signals(can, tkr, self._thresh())
                self.pair_candles[pair] = can
                self.pair_signals[pair] = sig
                self.current_prices[pair] = sig["price"]
                self.root.after(0, lambda: self._set_price(pair, sig["price"]))
                self.root.after(0, lambda s={**sig,"symbol":pair}: self._update_claude_panel(s))
                cp = self.chart_panels.get(pair)
                if cp:
                    open_pos = [p for p in self.state.positions.values()
                                if p.symbol == pair]
                    def _on_tf_change(sym, tf, _cp=cp):
                        """Called by chart TF buttons to re-fetch with new timeframe."""
                        def _go():
                            try:
                                can2 = get_klines(sym, tf, 200)
                                tkr2 = get_ticker(sym)
                                sig2 = compute_signals(can2, tkr2, self._thresh())
                                ops2 = [p for p in self.state.positions.values()
                                        if p.symbol == sym]
                                self.root.after(0, lambda: _cp.update(can2, sig2, ops2))
                            except Exception:
                                pass
                        threading.Thread(target=_go, daemon=True).start()
                    self.root.after(0, lambda c=can, s=sig, o=open_pos: cp.update(c, s, o, on_tf_change=_on_tf_change))
            except Exception: pass
        threading.Thread(target=_go, daemon=True).start()

    def _set_price(self, pair, px):
        col = PAIR_COL.get(pair, CYAN)
        sym = pair.replace("_USDT", "")
        # Update per-pair ticker label
        lbl = self.price_lbls.get(pair)
        if lbl:
            if px < 0.01:   txt = f" ${px:,.5f}"
            elif px < 10:   txt = f" ${px:,.4f}"
            elif px >= 1000:txt = f" ${px:,.1f}"
            else:           txt = f" ${px:,.2f}"
            lbl.config(text=txt, fg=col)
        # Also keep compat label updated for selected pair
        self.price_lbl.config(text=f"{sym} {px:,.2f}", fg=col)

    def _on_tab(self, _=None): self._refresh_visible()
    def _on_pair(self, _=None):
        pair = self.pair_cb.get()
        if pair in PAIRS: self.nb.select(PAIRS.index(pair))
        # Update leverage options to match pair max
        opts = self._lev_opts(pair)
        self.lev_cb.config(values=opts)
        cur = self.lev_cb.get()
        if cur not in opts: self.lev_cb.set(opts[min(3, len(opts)-1)])  # default 10x
        self._on_lev()
        self._fetch_pair(pair)

    # ── DOCK CYCLE ────────────────────────────────────────────────────────────
    def _dock_cycle(self):
        self.dock.state = self.state
        self.dock.refresh(self.current_prices)
        if not self.dry_var.get():
            self._fetch_live_balance()
        self._dock_timer = self.root.after(2000, self._dock_cycle)

    # ── HELPERS ───────────────────────────────────────────────────────────────
    def _log(self, msg, col=None):
        tag = {GREEN:"g", RED:"r", BLUE:"b", AMBER:"a",
               PURPLE:"p", CYAN:"c", DIM:"dim", MUTED:"mu"}.get(col, "w")
        def _w():
            self.log_box.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}]  ", "dim")
            self.log_box.insert("end", msg + "\n", tag)
            self.log_box.see("end"); self.log_box.config(state="disabled")
        self.root.after(0, _w)

    def _met(self, i, val, sub=None, col=None):
        def _w():
            self.mv[i].config(text=val, fg=col or TEXT)
            if sub is not None: self.ms[i].config(text=sub)
        self.root.after(0, _w)

    def _on_mode(self):
        if self.dry_var.get():
            self.mode_lbl.config(text="● PAPER MODE — no real orders", fg=AMBER, bg=BG2)
            self._live_balance = None
            self._refresh_metrics()
        else:
            self.mode_lbl.config(text="⚡ LIVE TRADING — real money", fg="#ffffff", bg="#8b0000")
            ak = self.mexc_key_e.get().strip() if hasattr(self, "mexc_key_e") else ""
            sc = self.mexc_sec_e.get().strip() if hasattr(self, "mexc_sec_e") else ""
            if ak and sc:
                self._met(3, "fetching…", "MEXC futures USDT", MUTED)
                self._met(0, "fetching…", "live P&L", MUTED)
                self._balance_fetch = 0
                self._fetch_live_balance()
            else:
                self._met(3, "no API keys", "add keys in sidebar", RED)
                self._met(0, "—", "live P&L", MUTED)

    def _active_pairs(self):
        """Returns list of currently enabled pairs."""
        return [p for p, v in self._pair_vars.items() if v.get()] if hasattr(self, "_pair_vars") else PAIRS

    def _set_all_pairs(self, state):
        for v in self._pair_vars.values(): v.set(state)
        self._on_pair_toggle()

    def _set_preset(self, pairs):
        for p, v in self._pair_vars.items(): v.set(p in pairs)
        self._on_pair_toggle()

    def _on_pair_toggle(self, _=None):
        """Update scan interval hint when pairs change."""
        n = len(self._active_pairs())
        # Each pair needs: 0.45s stagger + ~3s avg API response = ~3.45s per pair
        # Add 5s safety buffer so cycle completes before next one starts
        min_secs = round(n * 3.45 + 5)
        # Round up to nearest available interval
        if   min_secs <= 10: rec = "10s"
        elif min_secs <= 15: rec = "15s"
        elif min_secs <= 20: rec = "20s"
        elif min_secs <= 25: rec = "25s"
        elif min_secs <= 30: rec = "30s"
        elif min_secs <= 35: rec = "35s"
        elif min_secs <= 40: rec = "40s"
        elif min_secs <= 45: rec = "45s"
        elif min_secs <= 60: rec = "60s"
        elif min_secs <= 90: rec = "90s"
        elif min_secs <= 120: rec = "2 min"
        else:                 rec = "3 min"
        if hasattr(self, "_ivl_hint"):
            self._ivl_hint.config(
                text=f"{n} pairs active · min recommended: {rec}",
                fg=CYAN if self._ivl_satisfies_min(n) else RED)
        # Note: we just show the hint — never auto-change the user's setting

    def _ivl_satisfies_min(self, n=None):
        if n is None: n = len(self._active_pairs())
        min_secs = max(10, round(n * 0.45 + 2))
        return self._ivl() >= min_secs

    def _on_interval(self, _=None):
        """Update hint colour when interval is changed."""
        self._on_pair_toggle()

    def _on_dual_tf(self, _=None):
        enabled = self.dual_tf_var.get()
        self._dtf_lbl.config(
            text="ON" if enabled else "OFF",
            fg=CYAN if enabled else MUTED)
        if enabled:
            # Dual TF: force trend TF to Min5 if currently set to Min1
            if self.tf_cb.get() == "Min1":
                self.tf_cb.set("Min5")
        try:
            lbl_widget = self.tf_cb.master.winfo_children()[0]
            if enabled:
                lbl_widget.config(text="Trend TF", fg=CYAN)
            else:
                lbl_widget.config(text="Candle TF", fg=SUB)
        except Exception:
            pass

    def _on_lev(self, _=None):
        lv = self._lev()
        if lv == 0: return
        wipe_pct = round(100 / lv, 1)
        msg = f"{lv}x: {wipe_pct}% adverse move wipes margin"
        col = AMBER if lv <= 20 else RED
        try: self.lev_warn_inline.config(text=msg, fg=col)
        except: pass
        try: self.lev_warn.config(text=msg, fg=col)
        except: pass
        # Auto-set optimal SL/TP for leverage — user can still change after
        self._auto_sl_tp(lv)

    def _auto_sl_tp(self, lv):
        """
        Set SL/TP based on PRICE MOVE needed to survive candle noise, not margin %.
        Key insight: at 50x the old values (SL 0.12% / TP 0.25%) are within normal
        wick range — trades get stopped out before having any chance to work.

        SL must be at least 2-3x a typical 5-min candle ATR (~0.15-0.25% for crypto).
        TP = 2.2x SL for 1:2.2 R/R (profitable at 32%+ win rate).

        These are PRICE MOVE %s, not margin return %s:
          50x + SL 0.40% price = 20% margin loss if stopped — survivable and realistic
          50x + old SL 0.12% price = 6% margin loss — hit by normal wicks constantly
        User can always adjust after selecting leverage.
        """
        # sl/tp are price-move percentages (market move, not margin return)
        if   lv >= 150: sl, tp = "0.20%", "0.50%"
        elif lv >= 100: sl, tp = "0.25%", "0.60%"
        elif lv >= 75:  sl, tp = "0.30%", "0.70%"
        elif lv >= 50:  sl, tp = "0.40%", "0.90%"
        elif lv >= 40:  sl, tp = "0.50%", "1.2%"
        elif lv >= 25:  sl, tp = "0.60%", "1.5%"
        elif lv >= 20:  sl, tp = "0.70%", "1.5%"
        elif lv >= 15:  sl, tp = "0.80%", "2.0%"
        elif lv >= 10:  sl, tp = "0.90%", "2.0%"
        elif lv >= 5:   sl, tp = "1.5%",  "3.0%"
        elif lv >= 3:   sl, tp = "2.0%",  "4.0%"
        else:           sl, tp = "2.5%",  "5.0%"
        try:
            self.sl_cb.set(sl)
            self.tp_cb.set(tp)
            # Brief hint showing what changed and why
            liq_pct  = round(100 / lv, 1)
            sl_f     = float(sl.replace("%",""))
            tp_f     = float(tp.replace("%",""))
            sl_margin = round(sl_f * lv, 1)
            tp_margin = round(tp_f * lv, 1)
            hint = (f"Auto-set for {lv}x:  SL {sl} price ({sl_margin}% margin)  "
                    f"TP {tp} price ({tp_margin}% margin)  |  LIQ at {liq_pct}%")
            try:
                self.lev_warn.config(text=hint, fg=CYAN)
                self.root.after(5000, lambda: self.lev_warn.config(
                    text=f"{lv}x: {liq_pct}% adverse move wipes margin",
                    fg=AMBER if lv <= 20 else RED))
            except Exception:
                pass
        except Exception:
            pass

    def _lev_opts(self, pair):
        max_lev = PAIR_MAX_LEV.get(pair, 100)
        steps = [1,2,3,5,10,20,25,50,75,100,125,150,200]
        return [f"{l}x" for l in steps if l <= max_lev]

    def _lev(self):
        try: return int(self.lev_cb.get().replace("x","").strip())
        except: return 10

    def _thresh(self): return float(self.thr_cb.get().split("/")[0])
    def _sl(self):    return float(self.sl_cb.get().replace("%","")) / 100
    def _tp(self):    return float(self.tp_cb.get().replace("%","")) / 100
    def _ivl(self):   return {"10s":10,"15s":15,"20s":20,"25s":25,"30s":30,"35s":35,"40s":40,"45s":45,"60s":60,"90s":90,"2 min":120,"3 min":180,"5 min":300,"10 min":600}.get(self.int_cb.get(),30)
    def _max_trades(self):
        v = self.max_trades_cb.get()
        return 999 if "Unlimited" in v else int(v.split(" ")[0])
    def _stack_max(self):
        return int(self.stack_max_cb.get().replace("x",""))
    def _stack_thresh(self):
        return float(self.stack_thresh_cb.get().split("/")[0])

    def _toggle_claude(self):
        enabled = not self.claude_enabled.get()
        self.claude_enabled.set(enabled)
        if enabled:
            self.claude_toggle.config(text="  ON  ✅  —  click to disable", bg="#0d2818", fg=GREEN)
            self.claude_entry.config(state="normal")
            self._show_btn.config(state="normal")
            self._test_btn.config(state="normal", bg=PURPLE, fg=TEXT)
            self.claude_status.config(text="Paste key and click Test ▶", fg=AMBER)
        else:
            self.claude_toggle.config(text="  OFF  —  click to enable", bg=BG3, fg=MUTED)
            self.claude_entry.config(state="disabled")
            self._show_btn.config(state="disabled")
            self._test_btn.config(state="disabled", bg=BG3, fg=MUTED)
            self.claude_status.config(text="OFF — local signals only", fg=MUTED)

    def _test_claude(self):
        key = self.claude_entry.get().strip()
        if not key:
            self.claude_status.config(text="⚠ Paste your key first", fg=AMBER); return
        self.claude_status.config(text="Testing…", fg=AMBER)
        self.root.update()
        def _go():
            ok, msg = test_claude_key(key)
            col = GREEN if ok else RED
            self.root.after(0, lambda: self.claude_status.config(text=msg, fg=col))
            if ok: self._log("Claude API key verified.", GREEN)
        threading.Thread(target=_go, daemon=True).start()

    def _save_keys(self):
        with open(KEYS_FILE, "w") as f:
            json.dump({"mexc_api_key":    self.mexc_key_e.get().strip(),
                       "mexc_api_secret": self.mexc_sec_e.get().strip(),
                       "anthropic_key":   self.claude_entry.get().strip()}, f)
        self._log(f"Keys saved → {KEYS_FILE}", GREEN)

    def _load_keys(self):
        if not os.path.exists(KEYS_FILE): return
        try:
            k = json.load(open(KEYS_FILE))
            self.mexc_key_e.delete(0,"end"); self.mexc_key_e.insert(0, k.get("mexc_api_key",""))
            self.mexc_sec_e.delete(0,"end"); self.mexc_sec_e.insert(0, k.get("mexc_api_secret",""))
            ck = k.get("anthropic_key","")
            self.claude_entry.delete(0,"end"); self.claude_entry.insert(0, ck)
            if ck: self.claude_status.config(text="Key loaded — click Test to verify", fg=MUTED)
        except Exception: pass

    def _refresh_metrics(self):
        s    = self.state
        dry  = self.dry_var.get()
        n    = s.wins + s.losses + s.liqs
        np_  = len(s.positions)
        nh   = sum(1 for p in s.positions.values() if p.hedge_of)
        pc   = GREEN if s.total_pnl >= 0 else RED

        # ── Session P&L — always from state.total_pnl (tracks this session) ──
        pnl_sign = "+" if s.total_pnl >= 0 else ""
        if not dry and self._live_balance:
            urp = self._live_balance.get("unrealised", 0)
            urp_str = f"  open {urp:+.2f}" if abs(urp) > 0.0001 else ""
            sub_pnl = f"session{urp_str}"
        else:
            sub_pnl = f"session"
        self._met(0, f"{pnl_sign}${abs(s.total_pnl):.2f}", sub_pnl, pc)

        # ── Win rate ──────────────────────────────────────────────────────────
        wr  = f"{s.wins/n*100:.1f}%" if n > 0 else "—"
        avg = f"${s.total_pnl/n:+.2f} avg" if n > 0 else "avg  $—"
        self._met(1, wr, f"{s.wins}W / {s.losses}L")
        self._met(2, str(n), avg)

        # ── Balance — paper vs live ───────────────────────────────────────────
        if dry:
            bal_val = f"{s.balance:,.2f} USDT"
            bal_sub = "paper balance"
            bal_col = GREEN if s.balance >= 1000 else RED
        else:
            lb = self._live_balance
            if lb:
                used = lb["equity"] - lb["available"]
                bal_val = f"{lb['equity']:,.2f} USDT"
                bal_sub = (f"avail {lb['available']:,.2f}  used {used:,.2f}" 
                           if used > 0.001 else f"avail {lb['available']:,.2f} USDT")
                bal_col = GREEN if lb["equity"] > 0 else RED
            else:
                bal_val = "fetching…"
                bal_sub = "MEXC balance"
                bal_col = MUTED
        self._met(3, bal_val, bal_sub, bal_col)

        # ── Open positions & liqs ─────────────────────────────────────────────
        self._met(4, str(np_), f"{nh} hedged", CYAN if np_ > 0 else MUTED)
        lp = f"{s.liqs/n*100:.1f}% of trades" if n > 0 else "0.0% of trades"
        self._met(5, str(s.liqs), lp, RED if s.liqs > 0 else MUTED)

        # ── Runtime ───────────────────────────────────────────────────────────
        if self._bot_start_time and self.bot_running:
            elapsed = time.time() - self._bot_start_time
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            sec = int(elapsed % 60)
            uptime_str = f"{h:02d}:{m:02d}:{sec:02d}"
            thr_now = self._adaptive_thr or self._thresh()
            cyc_sub = (f"{self._cycles_run} cycles  thr:{thr_now}/9"
                       + (" ↓adaptive" if self._adaptive_thr else ""))
            adp_on  = self.adaptive_var.get() if hasattr(self,"adaptive_var") else True
            thr_col = AMBER if self._adaptive_thr else (CYAN if adp_on else MUTED)
            self._met(6, uptime_str, cyc_sub, thr_col)
        elif self.bot_running:
            self._met(6, "starting…", "0 cycles", MUTED)
        else:
            self._met(6, "—", "bot stopped", MUTED)

        # ── Last signal ───────────────────────────────────────────────────────
        if self._last_signal_pair:
            ago = int(time.time() - self._last_signal_time) if self._last_signal_time else 0
            ago_str = f"{ago//60}m {ago%60}s ago" if ago >= 60 else f"{ago}s ago"
            sig_col = GREEN if self._last_signal_dir == "LONG" else (
                      RED if self._last_signal_dir == "SHORT" else MUTED)
            self._met(7, pair_label(self._last_signal_pair),
                      f"{self._last_signal_dir} · {ago_str}", sig_col)
        else:
            self._met(7, "—", "no signal yet", MUTED)

    def _fetch_live_balance(self):
        """Background fetch of live MEXC account balance every 10s."""
        if self.dry_var.get(): return
        ak = self.mexc_key_e.get().strip()
        sc = self.mexc_sec_e.get().strip()
        if not ak or not sc: return
        # Refresh faster when positions are open
        has_open = len(self.state.positions) > 0 if hasattr(self, "state") else False
        min_interval = 3 if has_open else 12
        if time.time() - self._balance_fetch < min_interval: return
        self._balance_fetch = time.time()
        def _go():
            try:
                data = get_live_account(ak, sc)
                self._live_balance = data
                self.root.after(0, self._refresh_metrics)
            except Exception as e:
                err = str(e)[:80]
                self._log(f"Balance fetch error: {err}", RED)
                self.root.after(0, lambda: self._met(3, "API error", err[:22], RED))
                self.root.after(0, lambda: self._met(0, "API error", "check keys", RED))
        threading.Thread(target=_go, daemon=True).start()

    def _save(self):
        s = self.state
        with open(STATE_FILE, "w") as f:
            pos_list = [asdict(p) for p in s.positions.values()]
            json.dump({"balance": s.balance, "total_pnl": s.total_pnl,
                       "wins": s.wins, "losses": s.losses, "liqs": s.liqs,
                       "trades": s.trades, "positions": pos_list}, f, indent=2)

    # ── BOT CONTROL ───────────────────────────────────────────────────────────
    # ── MANUAL POSITION CONTROLS ─────────────────────────────────────────────
    def _manual_close_position(self, pid):
        """Manually close a position at market price."""
        if pid not in self.state.positions:
            return
        pos = self.state.positions[pid]
        px  = self.current_prices.get(pos.symbol, pos.entry_price)
        dry = self.dry_var.get()
        ak  = self.mexc_key_e.get().strip()
        asc = self.mexc_sec_e.get().strip()
        lev = pos.leverage

        def _do():
            closed, status, pnl = self._check_exit_force(pos, px, lev, dry, ak, asc)
            if closed:
                col = GREEN if status == "WIN" else (PURPLE if status == "LIQUIDATED" else RED)
                self._log(f"MANUAL CLOSE [{status}] {pos.direction} "
                          f"{pos.symbol} @ ${px:,.4f}  PnL ${pnl:+.2f}", col)
                self._price_history.pop(pid, None)
                self._price_peak.pop(pid, None)
                self._stale_checked.discard(pid)
                self._refresh_metrics()
                self._save()
                self.root.after(0, self._refresh_trades_tab)
        threading.Thread(target=_do, daemon=True).start()

    def _manual_hedge_position(self, pid):
        """Manually open a hedge for a position."""
        if pid not in self.state.positions:
            return
        pos = self.state.positions[pid]
        px  = self.current_prices.get(pos.symbol, pos.entry_price)
        dry = self.dry_var.get()
        ak  = self.mexc_key_e.get().strip()
        asc = self.mexc_sec_e.get().strip()
        sl  = self._sl(); tp = self._tp()
        lev = pos.leverage

        # Check not already hedged
        already = any(p.hedge_of == pid for p in self.state.positions.values())
        if already:
            self._log(f"Position {pid[:6]} already has a hedge", AMBER)
            return

        hedge_dir = "SHORT" if pos.direction == "LONG" else "LONG"

        def _do():
            hid = self._open_position(pos.symbol, hedge_dir, px,
                                       pos.margin * 0.5, lev, sl, tp,
                                       dry, ak, asc, hedge_of=pid)
            if hid:
                self._log(f"MANUAL HEDGE: {hedge_dir} {pos.symbol} "
                          f"@ ${px:,.4f}  (hedging {pos.direction})", AMBER)
                self._refresh_metrics()
                self._save()
        threading.Thread(target=_do, daemon=True).start()

    def _check_exit_force(self, pos, px, lev, dry, ak, asc):
        """Force-close a position at current market price regardless of SL/TP."""
        d = pos.direction
        raw = (px - pos.entry_price) / pos.entry_price if d == "LONG"               else (pos.entry_price - px) / pos.entry_price
        gross_pnl = raw * pos.leverage * pos.margin
        fee    = pos.size_usdt * 0.002   # 0.2% round-trip taker fees
        pnl    = round(gross_pnl - fee, 4)
        status = "WIN" if pnl >= 0 else "LOSS"

        if not dry:
            side = 4 if d == "LONG" else 2
            vol  = round_vol(pos.symbol, pos.size_usdt / pos.entry_price)
            try:
                mexc_private("POST", "/api/v1/private/order/submit",
                             {"symbol": pos.symbol, "price": 0, "vol": vol,
                              "side": side, "type": 5, "openType": 1},
                             ak, asc, dry)
            except Exception as e:
                self._log(f"Close order error: {e}", RED)
                return False, None, 0

        self.state.total_pnl  = round(self.state.total_pnl + pnl, 4)
        if self.dry_var.get():
            self.state.balance = round(self.state.balance + pos.margin + pnl, 4)
        else:
            self.state.balance = round(self.state.balance + pnl, 4)
        if pnl >= 0: self.state.wins  += 1
        else:        self.state.losses += 1

        self.state.trades.append({
            "symbol": pos.symbol, "direction": d,
            "entry_price": pos.entry_price, "exit_price": px,
            "margin": pos.margin, "leverage": pos.leverage,
            "pnl_usdt": pnl, "status": f"MANUAL {status}",
            "hedge": bool(pos.hedge_of),
            "opened_at": pos.opened_at,
            "closed_at": datetime.now(timezone.utc).isoformat()})

        del self.state.positions[pos.id]
        return True, status, pnl

    def _on_adaptive_toggle(self, _=None):
        enabled = self.adaptive_var.get()
        if enabled:
            self._adaptive_status_lbl.config(text="ON", fg=CYAN)
            self._adaptive_info.config(
                text="Relaxes after 20 cycles → -0.5\n              40 cycles → -1.0",
                fg=DIM)
        else:
            self._adaptive_status_lbl.config(text="OFF", fg=MUTED)
            self._adaptive_info.config(text="Manual threshold only", fg=MUTED)
            self._adaptive_thr = None   # clear any active adaptation
            self._hold_streak  = 0

    def _toggle_overnight(self):
        enabled = not self.overnight_var.get()
        self.overnight_var.set(enabled)
        if enabled:
            self.overnight_btn.config(
                text="  ON  🌙  —  click to disable",
                bg="#0a2a2a", fg=TEAL)
            self._overnight_detail.config(fg=TEAL)
            # Apply overnight defaults: lower threshold, keep user's other settings
            try:
                cur_thr = self.thr_cb.get()
                if cur_thr == "6.0/9":
                    self.thr_cb.set("5.0/9")
            except Exception:
                pass
            self._log("🌙 Overnight mode ON — threshold relaxed, dual TF filter loosened, "
                      "adaptive triggers at 10 cycles", TEAL)
        else:
            self.overnight_btn.config(
                text="  OFF  —  click to enable",
                bg=BG3, fg=MUTED)
            self._overnight_detail.config(fg=MUTED)
            # Restore daytime threshold if it was auto-lowered
            try:
                cur_thr = self.thr_cb.get()
                if cur_thr == "5.0/9":
                    self.thr_cb.set("6.0/9")
            except Exception:
                pass
            self._log("☀ Overnight mode OFF — normal daytime filters restored", CYAN)

    def _overnight_rsi_limit(self):
        """RSI limit for dual-TF entry filter. Loosened in overnight mode."""
        return 75 if (hasattr(self, "overnight_var") and self.overnight_var.get()) else 65

    def _adaptive_trigger_cycle(self):
        """How many HOLD cycles before adaptive threshold kicks in."""
        return 10 if (hasattr(self, "overnight_var") and self.overnight_var.get()) else 20

    def _adaptive_floor(self):
        """Minimum threshold adaptive can relax to."""
        return 3.5 if (hasattr(self, "overnight_var") and self.overnight_var.get()) else 4.0

    def _reset_defaults(self):
        """Reset all config to optimised defaults and delete saved config."""
        import tkinter.messagebox as mb
        msg = "Reset all settings to optimised defaults? API keys kept."
        if not mb.askyesno("Reset defaults", msg): return
        # Delete saved config file
        cfg_path = os.path.join(str(pathlib.Path.home()), "HermesBot", "hermesbot_cfg.json")
        try: os.remove(cfg_path)
        except: pass
        # Re-apply UI defaults
        try:
            self.lev_cb.set("10x");           self._on_lev()
            # _on_lev calls _auto_sl_tp which sets SL/TP correctly for the leverage
            # so don't override them with hardcoded values here
            self.thr_cb.set("5.0/9")
            self.int_cb.set("30s")
            self.tf_cb.set("Min5")
            self.margin_e.delete(0, "end");   self.margin_e.insert(0, "50")
            self.max_trades_cb.set("2")
            self.hedge_var.set(False)
            self.stack_var.set(False)
            self.adaptive_var.set(True);      self._on_adaptive_toggle()
            # Keep current mode — only reset config, not live/paper selection
            self._on_mode()
        except Exception as e:
            self._log(f"Reset error: {e}", RED)
        self._log("✓ Settings reset to optimised defaults", CYAN)

    def _preflight_check(self):
        """Check balance, margin, and order size before going live."""
        warnings_ = []
        errors_   = []
        margin   = float(self.margin_e.get() or 0)
        lev      = self._lev()
        notional = margin * lev

        # 1. Margin must be positive
        if margin <= 0:
            errors_.append("Margin USDT must be greater than 0")

        # 2. No API keys
        ak = self.mexc_key_e.get().strip()
        sc = self.mexc_sec_e.get().strip()
        if not ak or not sc:
            errors_.append("MEXC API key and secret are required for live trading")

        # 3. Check live balance vs margin (only if balance fetched)
        if self._live_balance:
            avail = self._live_balance.get("available", 0)
            if avail <= 0:
                errors_.append(
                    f"Futures wallet is empty ({avail:.4f} USDT)\n"
                    "Go to MEXC → Assets → Transfer USDT to Futures wallet first")
            elif margin > avail:
                errors_.append(
                    f"Margin {margin} USDT > available {avail:.4f} USDT\n"
                    "Reduce margin or transfer more USDT to futures wallet")
            elif margin > avail * 0.8:
                warnings_.append(
                    f"Margin uses {margin/avail*100:.0f}% of available balance "
                    f"({avail:.4f} USDT) — leaves little room for multiple trades")

            # 4. Max trades vs balance
            try:
                maxt = int(str(self.max_trades_cb.get()).split()[0])
            except Exception:
                maxt = 1
            total_needed = margin * maxt
            if total_needed > avail:
                warnings_.append(
                    f"{maxt} trades × {margin} USDT = {total_needed} USDT needed "
                    f"but only {avail:.4f} USDT available — reduce max trades or margin")
        else:
            # Balance not fetched yet — warn but don't block
            warnings_.append(
                "Could not verify MEXC balance — make sure you have USDT "
                "in your Futures wallet before trading")

        # 5. High leverage warnings
        if lev >= 100:
            warnings_.append(
                f"{lev}x: a {100/lev:.1f}% price move = 100% margin loss. "
                "Recommended: 10-25x until win rate is proven above 55%")
        elif lev >= 50:
            warnings_.append(
                f"{lev}x: a {100/lev:.1f}% price move = 100% margin loss")

        return errors_, warnings_

    def toggle_bot(self):
        if not self.bot_running:
            if not self.dry_var.get():
                errors_, warnings_ = self._preflight_check()

                # Build warning message
                msg_parts = []
                if errors_:
                    msg_parts.append("❌ ERRORS (must fix):\n" + "\n".join(f"  • {e}" for e in errors_))
                if warnings_:
                    msg_parts.append("⚠ WARNINGS:\n" + "\n".join(f"  • {w}" for w in warnings_))
                msg_parts.append(f"\nMode     : LIVE TRADING")
                msg_parts.append(f"Leverage : {self._lev()}x")
                msg_parts.append(f"Margin   : {self.margin_e.get()} USDT per trade")
                if self._live_balance:
                    msg_parts.append(f"Available: {self._live_balance.get('available',0):.2f} USDT")

                if errors_:
                    messagebox.showerror("Cannot start — fix errors", "\n\n".join(msg_parts))
                    return

                if not messagebox.askyesno("⚠ Start LIVE trading?", "\n".join(msg_parts)
                                            + "\n\nStart live trading?"): return
            self._start()
        else: self._stop()

    def _start(self):
        self.bot_running = True; self._stop_event.clear(); self.state = BotState(); self.dock.state = self.state
        self._bot_start_time  = time.time()
        self._cycles_run      = 0
        self._hold_streak     = 0
        self._adaptive_thr    = None
        self._last_signal_pair= None
        self._last_signal_time= None
        self._last_signal_dir = None
        self._claude_tokens  = 0
        self._claude_cost    = 0.0
        self._claude_calls   = 0
        if hasattr(self, "_cost_lbl"):
            self._cost_lbl.config(text="$0.0000", fg=DIM)
            self._calls_lbl.config(text="0 calls")
        self.root.after(200, self._refresh_trades_tab)
        self.start_btn.config(text="■  STOP BOT", bg=RED, fg=TEXT, activebackground="#c0392b")
        self.status_dot.config(fg=GREEN)
        dry = self.dry_var.get()
        mode_str = "PAPER (no real orders)" if dry else "⚡ LIVE TRADING ⚡"
        mode_col = AMBER if dry else RED
        self._log(f"Bot started — {mode_str}", mode_col)
        dual = self.dual_tf_var.get() if hasattr(self,"dual_tf_var") else False
        tf_desc = f"Min5→Min1 (dual)" if dual else self.tf_cb.get()
        self._log(f"Scanning {len(self._active_pairs())} pairs  |  Leverage: {self._lev()}x  TF: {tf_desc}", GREEN)
        self._log(f"Margin ${self.margin_e.get()}  SL {self.sl_cb.get()}  TP {self.tp_cb.get()}"
                  f"  MaxTrades {self.max_trades_cb.get()}"
                  f"  Hedge {'ON' if self.hedge_var.get() else 'OFF'}", BLUE)
        self.nb.select(len(PAIRS))
        self.bot_thread = threading.Thread(target=self._loop, daemon=True)
        self.bot_thread.start()

    def _stop(self):
        self.bot_running = False; self._stop_event.set()
        self.start_btn.config(text="▶  START BOT", bg=GREEN, fg=BG, activebackground="#00b85a")
        self.status_dot.config(fg=DIM)
        self._log("Bot stopped.", AMBER)
        self._save()

    # ── BOT LOOP ──────────────────────────────────────────────────────────────
    def _loop(self):
        cycle = 0
        while self.bot_running and not self._stop_event.is_set():
            cycle += 1
            try:
                lev  = self._lev()
                mg   = float(self.margin_e.get())
                sl   = self._sl(); tp = self._tp()
                thr  = self._thresh()
                dry  = self.dry_var.get()
                dual_mode = self.dual_tf_var.get() if hasattr(self,"dual_tf_var") else False
                tf = self.tf_cb.get()
                if dual_mode and tf == "Min1":
                    tf = "Min5"
                    self.root.after(0, lambda: self.tf_cb.set("Min5"))
                ak   = self.mexc_key_e.get().strip()
                asc  = self.mexc_sec_e.get().strip()
                ck   = self.claude_entry.get().strip() if self.claude_enabled.get() else ""
                maxt       = self._max_trades()
                hedge_on   = self.hedge_var.get()
                hedge_thr  = float(self.hedge_thresh_cb.get().replace("%","")) / 100
                stack_on   = self.stack_var.get()
                stack_thr  = self._stack_thresh()
                stack_max  = self._stack_max()
                overnight  = self.overnight_var.get() if hasattr(self, "overnight_var") else False

                # ── Scan ALL pairs in parallel, pick best signal ──────────
                self._cycles_run += 1
                _scan_pairs = self._active_pairs()
                self._log(f"Cycle {cycle} — scanning {len(_scan_pairs)} pairs ({tf})…", DIM)

                all_sigs = {}   # pair -> sig dict
                scan_errors = []

                def _scan_pair(p):
                    if p in self._dead_pairs:
                        return
                    try:
                        tkr_ = get_ticker(p)
                        can_ = get_klines(p, tf, 60)

                        if dual_mode and tf != "Min1":
                            # ── Sequential dual TF (only when Dual TF enabled) ──────
                            # Step 1: Min5 trend confirmation
                            sig5_ = compute_signals(can_, tkr_, _thr_eff)

                            if sig5_["direction"] in ("LONG", "SHORT"):
                                # Step 2: Min1 entry timing confirmation
                                try:
                                    can1_ = get_klines(p, "Min1", 30)
                                    sig1_ = compute_signals(can1_, tkr_, _thr_eff)

                                    # Entry confirmed only if Min1 agrees with Min5 direction
                                    # AND Min1 is not overbought/oversold against the trade
                                    d5 = sig5_["direction"]
                                    rsi1 = sig1_["rsi"]
                                    sr1  = sig1_.get("srsi", 50)

                                    entry_ok = False
                                    if d5 == "LONG":
                                        # For LONG: want Min1 RSI not overbought (room to run up)
                                        rsi_limit = self._overnight_rsi_limit()
                                        entry_ok = (rsi1 < rsi_limit and sr1 < rsi_limit + 5)
                                    else:
                                        # For SHORT: Min1 RSI must be at least neutral-bearish (>50)
                                        # RSI 35-45 on M1 means oversold bounce risk — not a good short entry
                                        # Old check (rsi1 > 35) was too loose and allowed neutral entries
                                        short_rsi_min = 50  # require bearish territory, not just "not oversold"
                                        entry_ok = (rsi1 > short_rsi_min and sr1 > 45)

                                    if entry_ok:
                                        # Merge: Min5 for direction/score, Min1 for price/entry indicators
                                        sig_ = {
                                            **sig5_,
                                            "price":    sig1_["price"],
                                            "rsi":      sig1_["rsi"],
                                            "srsi":     sig1_.get("srsi", sig5_.get("srsi", 50)),
                                            "macd_h":   sig1_["macd_h"],
                                            "pct_b":    sig1_.get("pct_b",  sig5_.get("pct_b",  0.5)),
                                            "atr_pct":  sig1_.get("atr_pct",sig5_.get("atr_pct",0)),
                                            "obv_slope":sig1_.get("obv_slope",sig5_.get("obv_slope",0)),
                                            "dual_confirmed": True,
                                        }
                                    else:
                                        # Min5 trend found but Min1 entry timing is bad — hold
                                        sig_ = {**sig5_, "direction": "HOLD",
                                                "dual_waiting": True,
                                                "price": sig1_["price"]}
                                except Exception:
                                    # Min1 fetch failed — fall back to Min5 only
                                    sig_ = sig5_
                            else:
                                # Min5 says HOLD — no need to check Min1
                                sig_ = sig5_
                        else:
                            # Single TF mode — compute normally
                            sig_ = compute_signals(can_, tkr_, _thr_eff)

                        all_sigs[p] = sig_
                        self.current_prices[p] = sig_["price"]
                        self.pair_candles[p]   = can_
                        self.pair_signals[p]   = sig_
                        self.root.after(0, lambda _p=p, _px=sig_["price"]: self._set_price(_p, _px))
                        cp = self.chart_panels.get(p)
                        if cp:
                            op = [pos for pos in self.state.positions.values() if pos.symbol == p]
                            self.root.after(0, lambda _c=can_, _s=sig_, _op=op: cp.update(_c, _s, _op))
                    except Exception as e:
                        err_str = str(e)
                        # Code 1001 = contract doesn't exist on MEXC — skip permanently
                        if "1001" in err_str or "Contract does not exist" in err_str:
                            if p not in self._dead_pairs:
                                self._dead_pairs.add(p)
                                lbl = pair_label(p)
                                # Try alternate symbol formats
                                alt = None
                                if p == "PEPE_USDT": alt = "PEPEUSDT"
                                elif p == "XAU_USDT":   alt = "XAU_USDT"
                                hint = f" — try symbol '{alt}'" if alt else " — removing from scan"
                                scan_errors.append(f"⚠ {lbl} not found on MEXC{hint}")
                        else:
                            scan_errors.append(f"{pair_label(p)}: {err_str[:60]}")

                _thr_eff = self._adaptive_thr if self._adaptive_thr else thr
                # Stagger launches to avoid MEXC rate limit
                threads = []
                for p in _scan_pairs:
                    t = threading.Thread(target=_scan_pair, args=(p,), daemon=True)
                    threads.append(t)
                    t.start()
                    time.sleep(0.45)
                for t in threads: t.join(timeout=15)

                if scan_errors:
                    for err in scan_errors:
                        self._log(err, AMBER)

                if not all_sigs:
                    self._log("No data from any pair — skipping cycle", RED)
                else:
                    # Log scan summary — show score for each pair
                    summary = "  ".join(
                        (f"{pair_label(p)}: {s['direction'][0]}{s['score']}"
                         + ("~" if s.get("dual_waiting") else "+" if s.get("dual_confirmed") else ""))
                        for p, s in sorted(all_sigs.items(),
                                           key=lambda x: x[1]['score'], reverse=True))
                    active_n = len(_scan_pairs)
                    self._log(f"Scores → {summary}", DIM)

                # ── Refresh prices for any open positions whose pair may have errored
                open_syms = set(p.symbol for p in self.state.positions.values())
                for osym in open_syms:
                    if osym not in all_sigs:  # wasn't scanned successfully
                        try:
                            _tkr = get_ticker(osym)
                            if _tkr["last"] > 0:
                                self.current_prices[osym] = _tkr["last"]
                        except Exception:
                            pass

                # ── Check exits on all open positions (use latest price) ───────
                for pid in list(self.state.positions.keys()):
                    if pid not in self.state.positions: continue
                    pos = self.state.positions[pid]
                    cur_px = self.current_prices.get(pos.symbol, pos.entry_price)
                    closed, status, pnl = self._check_exit(pos, cur_px, pos.leverage, dry, ak, asc)
                    if closed:
                        col = GREEN if status == "WIN" else (PURPLE if status == "LIQUIDATED" else RED)
                        self._log(f"CLOSED [{status}] {pos.direction} {pos.symbol} "
                                  f"@ ${cur_px:,.4f}  PnL ${pnl:+.2f}", col)
                        self._refresh_metrics(); self._save()
                        # Force balance refresh after closing position
                        self._balance_fetch = 0
                        self._fetch_live_balance(); self.root.after(0, self._refresh_trades_tab)
                        self.root.after(0, self._refresh_ai_tab)
                        self._price_history.pop(pid, None)  # clean up history
                        self._price_peak.pop(pid, None)
                        self._stale_checked.discard(pid)
                        for attr in [f"near_tp_{pid}", f"stale_{pid}"]:
                            try: delattr(self, attr)
                            except AttributeError: pass

                # ── Dynamic SL: ask Claude to tighten SL if trade going bad fast ──
                if ck and self.claude_enabled.get():
                    for pid in list(self.state.positions.keys()):
                        if pid not in self.state.positions: continue
                        pos = self.state.positions[pid]
                        cur_px = self.current_prices.get(pos.symbol, pos.entry_price)

                        # Track price history for this position (keep last 5 data points)
                        hist = self._price_history.setdefault(pid, [])
                        hist.append((time.time(), cur_px))
                        if len(hist) > 5:
                            hist.pop(0)

                        # Calculate current drawdown on margin
                        if pos.direction == "LONG":
                            raw_chg = (cur_px - pos.entry_price) / pos.entry_price
                        else:
                            raw_chg = (pos.entry_price - cur_px) / pos.entry_price
                        drawdown_pct = raw_chg * pos.leverage * 100  # negative = losing

                        # Calculate velocity: price move per cycle over last 3 points
                        velocity_pct = 0.0
                        if len(hist) >= 3:
                            oldest_px = hist[-3][1]
                            if pos.direction == "LONG":
                                velocity_pct = (cur_px - oldest_px) / pos.entry_price * 100
                            else:
                                velocity_pct = (oldest_px - cur_px) / pos.entry_price * 100
                            # velocity_pct < 0 means moving against us

                        # Trigger Claude if: losing AND moving against us fast
                        # Threshold: drawdown > -1% on margin AND velocity < -0.05% per cycle
                        trigger_drawdown  = drawdown_pct < -1.0
                        trigger_velocity  = velocity_pct < -0.05
                        if trigger_drawdown and trigger_velocity:
                            sig = self.pair_signals.get(pos.symbol) or {}
                            def _bg_sl(p=pos, px=cur_px, dd=drawdown_pct,
                                       vel=velocity_pct, s=sig, c=ck):
                                result = claude_sl_update(p, px, dd, vel, s, c)
                                if not result:
                                    return
                                action = result["action"]
                                reason = result["reason"]
                                tok    = result.get("tokens_used", 0)
                                cost   = tok * 0.000001 * 1.5
                                self._claude_tokens += tok
                                self._claude_cost    = round(self._claude_cost + cost, 6)
                                self._claude_calls  += 1
                                self.root.after(0, lambda: (
                                    self._cost_lbl.config(
                                        text=f"${self._claude_cost:.4f}",
                                        fg=AMBER if self._claude_cost > 0.01 else DIM),
                                    self._calls_lbl.config(
                                        text=f"{self._claude_calls} calls")
                                ) if hasattr(self, "_cost_lbl") else None)

                                if action == "TIGHTEN":
                                    new_sl = result["new_sl_price"]
                                    if p.id in self.state.positions:
                                        old_sl = p.stop_loss
                                        self.state.positions[p.id].stop_loss = new_sl
                                        self._log(
                                            f"AI SL TIGHTENED: {p.direction} "
                                            f"{pair_label(p.symbol)} "
                                            f"SL ${old_sl:,.4f} → ${new_sl:,.4f}  "
                                            f"({reason})", AMBER)
                                        self._ai_log_event(p.id, "🔒 SL TIGHTENED",
                                            f"${old_sl:,.4f} → ${new_sl:,.4f}\n{reason}", AMBER)
                                        self._save()
                                elif action == "CLOSE":
                                    # Force immediate close by setting SL = current price
                                    if p.id in self.state.positions:
                                        self._log(
                                            f"AI CLOSE SIGNAL: {p.direction} "
                                            f"{pair_label(p.symbol)} — {reason}", RED)
                                        self._ai_log_event(p.id, "🚨 AI CLOSE",
                                            f"Adverse momentum — closing now @ ${cur_px:,.4f}\n{reason}", RED)
                                        if p.direction == "LONG":
                                            self.state.positions[p.id].stop_loss = cur_px * 1.0001
                                        else:
                                            self.state.positions[p.id].stop_loss = cur_px * 0.9999
                                else:
                                    self._log(
                                        f"AI SL HOLD: {p.direction} "
                                        f"{pair_label(p.symbol)} — {reason}", DIM)
                                    self._ai_log_event(p.id, "✋ SL HOLD",
                                        reason, DIM)
                            threading.Thread(target=_bg_sl, daemon=True).start()

                # ── Near-TP early exit + stale trade checks ──────────────────
                if ck and self.claude_enabled.get():
                    for pid in list(self.state.positions.keys()):
                        if pid not in self.state.positions: continue
                        pos    = self.state.positions[pid]
                        if pos.hedge_of: continue
                        cur_px = self.current_prices.get(pos.symbol, pos.entry_price)
                        sig    = self.pair_signals.get(pos.symbol) or {}

                        # Track best (most profitable) price seen for this position
                        d = pos.direction
                        peak = self._price_peak.get(pid, pos.entry_price)
                        if d == "LONG":
                            if cur_px > peak: self._price_peak[pid] = cur_px
                        else:
                            if cur_px < peak: self._price_peak[pid] = cur_px

                        tp_total = abs(pos.take_profit - pos.entry_price)
                        tp_left  = abs(pos.take_profit - cur_px)
                        pct_to_tp = (tp_left / tp_total * 100) if tp_total else 100

                        # ── Near-TP: within 20% of TP gap remaining ───────────
                        in_profit = ((cur_px > pos.entry_price) if d=="LONG"
                                     else (cur_px < pos.entry_price))
                        near_tp_key = f"near_tp_{pid}"
                        already_checked_near = getattr(self, near_tp_key, 0)
                        if (in_profit and pct_to_tp <= 20.0
                                and time.time() - already_checked_near > 120):
                            setattr(self, near_tp_key, time.time())
                            def _bg_near_tp(p=pos, px=cur_px, ptt=pct_to_tp,
                                            s=sig, c=ck):
                                result = claude_near_tp_check(p, px, ptt, s, c)
                                if not result: return
                                tok  = result.get("tokens_used", 0)
                                cost = tok * 0.000001 * 1.5
                                self._claude_tokens += tok
                                self._claude_cost    = round(self._claude_cost + cost, 6)
                                self._claude_calls  += 1
                                action = result["action"]
                                reason = result["reason"]
                                if action == "TAKE":
                                    self._log(
                                        f"AI TAKE PROFIT: {p.direction} "
                                        f"{pair_label(p.symbol)} @ ${px:,.4f} "
                                        f"({ptt:.0f}% from TP) — {reason}", GREEN)
                                    self._ai_log_event(p.id, "💰 TAKE PROFIT EARLY",
                                        f"{ptt:.0f}% gap remaining — taking profit now @ ${px:,.4f}\n{reason}", GREEN)
                                    if p.id in self.state.positions:
                                        if p.direction == "LONG":
                                            self.state.positions[p.id].stop_loss = px * 0.9999
                                        else:
                                            self.state.positions[p.id].stop_loss = px * 1.0001
                                else:
                                    self._log(
                                        f"AI TP HOLD: {p.direction} "
                                        f"{pair_label(p.symbol)} — {reason}", DIM)
                                    self._ai_log_event(p.id, "⏳ NEAR-TP HOLD",
                                        f"{ptt:.0f}% gap remaining — holding for full TP\n{reason}", CYAN)
                            threading.Thread(target=_bg_near_tp, daemon=True).start()

                        # ── Stale trade: open > 45min with <0.15% drift ───────
                        try:
                            from datetime import datetime, timezone as _tz
                            opened = datetime.fromisoformat(
                                pos.opened_at.replace("Z", "+00:00"))
                            mins_open = (datetime.now(_tz.utc) - opened
                                         ).total_seconds() / 60
                        except Exception:
                            mins_open = 0

                        max_drift = abs(self._price_peak.get(pid, pos.entry_price)
                                        - pos.entry_price) / pos.entry_price * 100

                        stale_key = f"stale_{pid}"
                        already_stale = getattr(self, stale_key, 0)
                        if (mins_open >= 45 and max_drift < 0.15
                                and pid not in self._stale_checked
                                and time.time() - already_stale > 1800):
                            setattr(self, stale_key, time.time())
                            self._stale_checked.add(pid)
                            def _bg_stale(p=pos, px=cur_px, mo=mins_open,
                                          md=max_drift, s=sig, c=ck,
                                          _dry=dry, _ak=ak, _asc=asc):
                                result = claude_stale_trade_check(p, px, mo, md, s, c)
                                if not result: return
                                tok  = result.get("tokens_used", 0)
                                cost = tok * 0.000001 * 1.5
                                self._claude_tokens += tok
                                self._claude_cost    = round(self._claude_cost + cost, 6)
                                self._claude_calls  += 1
                                action = result["action"]
                                reason = result["reason"]
                                if action == "CLOSE":
                                    self._log(
                                        f"AI STALE CLOSE: {p.direction} "
                                        f"{pair_label(p.symbol)} open {mo:.0f}min "
                                        f"drift only {md:.3f}% — {reason}", AMBER)
                                    self._ai_log_event(p.id, "⌛ STALE — CLOSING",
                                        f"Open {mo:.0f}min, only {md:.3f}% drift — freeing margin\n{reason}", AMBER)
                                    if p.id in self.state.positions:
                                        if p.direction == "LONG":
                                            self.state.positions[p.id].stop_loss = px * 0.9999
                                        else:
                                            self.state.positions[p.id].stop_loss = px * 1.0001
                                else:
                                    self._log(
                                        f"AI stale HOLD: {p.direction} "
                                        f"{pair_label(p.symbol)} {mo:.0f}min — {reason}", DIM)
                                    self._ai_log_event(p.id, "⌛ STALE HOLD",
                                        f"Open {mo:.0f}min — holding longer\n{reason}", DIM)
                            threading.Thread(target=_bg_stale, daemon=True).start()

                # ── Claude trade monitoring log (every 5 cycles with open positions) ─
                if ck and self.claude_enabled.get() and self.state.positions:
                    if cycle % 5 == 0:
                        for pid, pos in list(self.state.positions.items()):
                            if pos.hedge_of: continue
                            cur_px = self.current_prices.get(pos.symbol, pos.entry_price)
                            sig    = self.pair_signals.get(pos.symbol) or {}
                            if not sig: continue
                            raw_chg = ((cur_px - pos.entry_price)/pos.entry_price
                                       if pos.direction=="LONG"
                                       else (pos.entry_price - cur_px)/pos.entry_price)
                            margin_pct = raw_chg * pos.leverage * 100
                            col = GREEN if margin_pct >= 0 else RED
                            self._log(
                                f"📊 {pos.direction} {pair_label(pos.symbol)} "
                                f"entry ${pos.entry_price:,.4f} → now ${cur_px:,.4f}  "
                                f"margin {margin_pct:+.1f}%  "
                                f"SL ${pos.stop_loss:,.4f}  TP ${pos.take_profit:,.4f}", col)
                            self._ai_log_event(pid, "📊 MONITOR",
                                f"Price ${cur_px:,.4f}  margin {margin_pct:+.1f}%  "
                                f"SL ${pos.stop_loss:,.4f}  TP ${pos.take_profit:,.4f}  "
                                f"RSI {sig.get('rsi',0):.0f}  {sig.get('trend','—')}",
                                col)

                # ── Hedge checks across all open positions ────────────────────
                # Rule-based hedge: fires when hedge toggle ON and drawdown exceeds threshold
                # AI hedge: fires independently when Claude is enabled, regardless of toggle
                for pid, pos in list(self.state.positions.items()):
                    if pos.hedge_of: continue
                    cur_px = self.current_prices.get(pos.symbol, pos.entry_price)
                    d = pos.direction
                    raw = (cur_px - pos.entry_price) / pos.entry_price
                    if d == "SHORT": raw = -raw
                    lev_chg = raw * pos.leverage
                    already_hedged = any(p.hedge_of == pid
                                          for p in self.state.positions.values())
                    if already_hedged:
                        continue

                    hedge_opened = False

                    # ── Rule-based hedge (toggle must be ON) ──────────────────
                    if hedge_on and lev_chg <= hedge_thr:
                        hedge_dir = "SHORT" if d == "LONG" else "LONG"
                        hid = self._open_position(
                            pos.symbol, hedge_dir, cur_px, mg * 0.5, lev,
                            sl, tp, dry, ak, asc, hedge_of=pid)
                        if hid:
                            self._log(f"HEDGE opened: {hedge_dir} {pos.symbol} "
                                      f"(rule-based  drawdown {lev_chg*100:.1f}%)", AMBER)
                            self._refresh_metrics(); self._save()
                            self.root.after(0, self._refresh_trades_tab)
                            hedge_opened = True

                    # ── AI hedge (Claude enabled, toggle OFF, drawdown meaningful) ──
                    # Only run if rule-based hedge didn't already fire,
                    # and drawdown is at least -2% on margin (not just noise)
                    if not hedge_opened and ck and self.claude_enabled.get() and not hedge_on:
                        if lev_chg * 100 <= -2.0:
                            sig = self.pair_signals.get(pos.symbol) or {}
                            drawdown_pct = lev_chg * 100
                            def _bg_hedge(p=pos, px=cur_px, dd=drawdown_pct,
                                          s=sig, c=ck, _sl=sl, _tp=tp,
                                          _mg=mg, _lev=lev, _dry=dry,
                                          _ak=ak, _asc=asc):
                                result = claude_hedge_check(p, px, dd, s, c)
                                if not result:
                                    return
                                tok  = result.get("tokens_used", 0)
                                cost = tok * 0.000001 * 1.5
                                self._claude_tokens += tok
                                self._claude_cost    = round(self._claude_cost + cost, 6)
                                self._claude_calls  += 1
                                self.root.after(0, lambda: (
                                    self._cost_lbl.config(
                                        text=f"${self._claude_cost:.4f}",
                                        fg=AMBER if self._claude_cost > 0.01 else DIM),
                                    self._calls_lbl.config(
                                        text=f"{self._claude_calls} calls")
                                ) if hasattr(self, "_cost_lbl") else None)

                                if result["action"] == "HEDGE":
                                    conf   = result["confidence"]
                                    reason = result["reason"]
                                    # Re-check not already hedged (race condition guard)
                                    if p.id not in self.state.positions: return
                                    still_hedged = any(x.hedge_of == p.id
                                                       for x in self.state.positions.values())
                                    if still_hedged: return
                                    hedge_dir = "SHORT" if p.direction == "LONG" else "LONG"
                                    hid = self._open_position(
                                        p.symbol, hedge_dir, px, _mg * 0.5, _lev,
                                        _sl, _tp, _dry, _ak, _asc, hedge_of=p.id)
                                    if hid:
                                        self._log(
                                            f"AI HEDGE [{conf}%]: {hedge_dir} "
                                            f"{pair_label(p.symbol)} — {reason}", AMBER)
                                        self._ai_log_event(p.id, f"⇄ AI HEDGE [{conf}%]",
                                            f"Opened {hedge_dir} hedge @ ${px:,.4f}\n{reason}", AMBER)
                                        self._refresh_metrics(); self._save()
                                        self.root.after(0, self._refresh_trades_tab)
                                else:
                                    self._log(
                                        f"AI hedge HOLD: {p.direction} "
                                        f"{pair_label(p.symbol)} — {result['reason']}", DIM)
                            threading.Thread(target=_bg_hedge, daemon=True).start()

                # ── Refresh H1 trend every 10 cycles ─────────────────────────
                if cycle % 10 == 1 or not self._h1_trends:
                    def _fetch_h1():
                        for pair in self._active_pairs():
                            try:
                                h1c = get_klines(pair, "Hour1", 30)
                                if h1c:
                                    h1_cl = [c["close"] for c in h1c]
                                    h1_e9  = ema(h1_cl, 9)
                                    h1_e21 = ema(h1_cl, 21)
                                    self._h1_trends[pair] = "BULL" if h1_e9[-1] > h1_e21[-1] else "BEAR"
                            except Exception:
                                pass
                    threading.Thread(target=_fetch_h1, daemon=True).start()

                # ── Pick best signal across all scanned pairs ─────────────────
                n_open = len(self.state.positions)
                now = time.time()
                COOLDOWN_SECS = 90  # 3 cycles at 30s after a loss on a pair

                # Apply filters to candidates before scoring:
                # 1. H1 trend alignment  2. Pair cooldown  3. RSI divergence
                # 4. Volume hard filter  5. Funding rate block  6. Time-of-day
                gmt_hour = __import__("datetime").datetime.utcnow().hour
                dead_zone = (4 <= gmt_hour < 7)  # 04:00-07:00 GMT lowest volume

                def _passes_filters(pair, sig):
                    d = sig["direction"]
                    reasons = []
                    # H1 trend alignment
                    h1 = self._h1_trends.get(pair)
                    if h1 and d == "LONG"  and h1 == "BEAR": reasons.append(f"H1 BEAR vs LONG")
                    if h1 and d == "SHORT" and h1 == "BULL": reasons.append(f"H1 BULL vs SHORT")
                    # Pair cooldown after loss
                    last_loss = self._pair_cooldown.get(pair, 0)
                    if now - last_loss < COOLDOWN_SECS:
                        remaining = int(COOLDOWN_SECS - (now - last_loss))
                        reasons.append(f"cooldown {remaining}s")
                    # RSI divergence: bearish divergence → block LONG; bullish → block SHORT
                    div = sig.get("rsi_divergence")
                    if div == "BEARISH" and d == "LONG":  reasons.append("bearish RSI divergence")
                    if div == "BULLISH" and d == "SHORT": reasons.append("bullish RSI divergence")
                    # Volume hard filter: require vol_ratio > 1.1
                    if sig.get("vol_ratio", 1.0) < 1.1: reasons.append(f"low volume {sig.get('vol_ratio',0):.1f}x")
                    # Funding rate block
                    fn = sig.get("funding", 0)
                    if d == "LONG"  and fn >  5.0: reasons.append(f"funding {fn:+.2f}% vs LONG")
                    if d == "SHORT" and fn < -5.0: reasons.append(f"funding {fn:+.2f}% vs SHORT")
                    # Dead zone
                    if dead_zone: reasons.append("dead zone 04-07 GMT")
                    # Flat market: EMA9 and EMA21 too close = no real trend = unreliable signal
                    ema_gap = sig.get("ema_gap_pct", 1.0)
                    if ema_gap < 0.05:
                        reasons.append(f"flat market EMA gap {ema_gap:.3f}%")
                    # MACD momentum check: histogram must be building in signal direction
                    # A negative/positive but shrinking histogram = fading momentum = weak entry
                    mh = sig.get("macd_h", 0)
                    if d == "SHORT" and mh < 0 and not sig.get("macd_building_short", True):
                        reasons.append("MACD momentum fading (histogram shrinking)")
                    if d == "LONG"  and mh > 0 and not sig.get("macd_building_long",  True):
                        reasons.append("MACD momentum fading (histogram shrinking)")
                    if reasons:
                        return False, reasons[0]
                    return True, None

                # Rank: prefer LONG/SHORT over HOLD, then by score descending
                raw_candidates = [(p, s) for p, s in all_sigs.items()
                                   if s["direction"] in ("LONG", "SHORT")]
                raw_candidates.sort(key=lambda x: x[1]["score"], reverse=True)

                # Apply filters
                candidates = []
                for p, s in raw_candidates:
                    ok, reason = _passes_filters(p, s)
                    if ok:
                        candidates.append((p, s))
                    else:
                        self._log(f"  ↷ {pair_label(p)} {s['direction']} filtered: {reason}", DIM)

                # Update claude panel with best signal found (or top pair if all HOLD)
                top_pair, top_sig = candidates[0] if candidates else                     sorted(all_sigs.items(), key=lambda x: x[1]["score"], reverse=True)[0]
                self.root.after(0, lambda s={**top_sig,"symbol":top_pair}: self._update_claude_panel(s))

                if n_open >= maxt:
                    self._log(f"Max trades ({maxt}) reached — monitoring only", DIM)
                    self._hold_streak = 0

                elif candidates:
                    # Signal found — update tracking and reset adaptive threshold
                    best_pair, best_sig = candidates[0]
                    self._last_signal_pair = best_pair
                    self._last_signal_time = time.time()
                    self._last_signal_dir  = best_sig["direction"]
                    self._hold_streak      = 0
                    self._adaptive_thr     = None  # signal found, restore normal threshold
                    self.root.after(0, lambda: self._adaptive_info.config(text="Relaxes after 20cy / 40cy", fg=DIM) if hasattr(self,"_adaptive_info") else None)
                    best_px = self.current_prices.get(best_pair, 0)

                    # Check we don't already have this pair+direction (unless stacking)
                    existing_same = [p for p in self.state.positions.values()
                                     if p.symbol == best_pair
                                     and p.direction == best_sig["direction"]
                                     and not p.hedge_of]
                    is_long   = best_sig["direction"] == "LONG"
                    can_stack = (stack_on and is_long
                                 and best_sig["score"] >= stack_thr
                                 and len(existing_same) < stack_max)

                    if not existing_same or can_stack:
                        contract_n = len(existing_same) + 1
                        stack_tag  = f" [#{contract_n}]" if contract_n > 1 else ""
                        conf_tag   = f"  ⚡ HIGH CONF" if can_stack else ""
                        # Use pair-specific leverage if available
                        pair_lev = min(lev, PAIR_MAX_LEV.get(best_pair, lev))
                        self._log(
                            f"BEST SIGNAL: {best_sig['direction']}{stack_tag} "
                            f"{best_pair.replace('_USDT','')}  "
                            f"score {best_sig['score']}/9  RSI {best_sig['rsi']:.1f}  "
                            f"{best_sig['trend']}{conf_tag}",
                            BLUE if not can_stack else CYAN)

                        # Runner-up for info
                        if len(candidates) > 1:
                            ru_p, ru_s = candidates[1]
                            self._log(
                                f"Runner-up: {ru_s['direction']} "
                                f"{ru_p.replace('_USDT','')} {ru_s['score']}/9", DIM)

                        # ── Claude decision engine ────────────────────────────
                        final_sl, final_tp = sl, tp
                        reason = None

                        # Warn Claude about any existing position on the same pair
                        existing_on_pair = [p for p in self.state.positions.values()
                                            if p.symbol == best_pair and not p.hedge_of]
                        if existing_on_pair:
                            ep = existing_on_pair[0]
                            raw_epnl = ((best_px - ep.entry_price)/ep.entry_price
                                        if ep.direction=="LONG"
                                        else (ep.entry_price - best_px)/ep.entry_price)
                            existing_note = (f"⚠ EXISTING {ep.direction} on {pair_label(best_pair)}: "
                                             f"entry ${ep.entry_price:,.4f}  "
                                             f"PnL {raw_epnl*ep.leverage*100:+.1f}% margin. "
                                             f"New signal is {best_sig['direction']} — "
                                             f"VETO if this contradicts existing trade; "
                                             f"only allow if clearly a different setup.")
                            self._log(existing_note, AMBER)
                            # Inject into signals so claude_decision sees it
                            best_sig = {**best_sig, "_existing_note": existing_note}

                        if ck and self.claude_enabled.get():
                            _last3 = "  |  ".join(
                                f"{t['direction'][0]} {pair_label(t['symbol'])} "
                                f"{'+'if t['pnl_usdt']>=0 else ''}{t['pnl_usdt']:.2f}"
                                for t in self.state.trades[-3:]
                            ) if self.state.trades else "no trades yet"
                            decision = claude_decision(
                                best_sig, self.state, best_pair,
                                pair_lev, mg, sl, tp, ck, last3=_last3)
                            if decision:
                                # Track cost (Haiku: ~$0.80/1M input, $4/1M output)
                                tok = decision.get("tokens_used", 0)
                                cost = tok * 0.000001 * 1.5  # blended rate estimate
                                self._claude_tokens += tok
                                self._claude_cost   = round(self._claude_cost + cost, 6)
                                self._claude_calls  += 1
                                self._last_claude_call = time.time()
                                self.root.after(0, lambda: (
                                    self._cost_lbl.config(
                                        text=f"${self._claude_cost:.4f}",
                                        fg=AMBER if self._claude_cost > 0.01 else DIM),
                                    self._calls_lbl.config(
                                        text=f"{self._claude_calls} calls")
                                ) if hasattr(self, "_cost_lbl") else None)

                                action = decision["action"]
                                conf   = decision["confidence"]
                                reason = decision["reason"]
                                final_sl = decision["sl_pct"]
                                final_tp = decision["tp_pct"]

                                if action == "VETO":
                                    self._log(
                                        f"AI VETO [{conf}% conf]: {reason}", RED)
                                    self._update_claude_panel(best_sig,
                                        reasoning=f"⛔ VETOED ({conf}%): {reason}")
                                    # Log veto to AI tab under a synthetic key
                                    import time as _vt
                                    veto_key = f"VETO_{int(_vt.time())}"
                                    self._ai_log_event(veto_key, f"⛔ VETO — {pair_label(best_pair)}",
                                        f"{best_sig['direction']} signal blocked [{conf}% conf]\n{reason}", RED)
                                    # Skip the trade
                                    reason = None  # prevent open_position call
                                    best_pair = None
                                elif action == "TRADE":
                                    tp_change = ""
                                    sl_change = ""
                                    if abs(final_tp - tp) > 0.0001:
                                        tp_change = (f" TP {'▲' if final_tp>tp else '▼'}"
                                                     f"{final_tp*100:.2f}%")
                                    if abs(final_sl - sl) > 0.0001:
                                        sl_change = (f" SL {'▲' if final_sl>sl else '▼'}"
                                                     f"{final_sl*100:.2f}%")
                                    self._log(
                                        f"AI TRADE [{conf}% conf]{tp_change}{sl_change}: "
                                        f"{reason}", CYAN)
                                else:
                                    self._log(f"AI: {reason}", PURPLE)
                            else:
                                # Claude failed — fall back to indicator decision
                                self._log("AI unavailable — using indicators", MUTED)

                        self._update_claude_panel(best_sig, reasoning=reason)

                        pid = None  # ensure defined even if vetoed or open_position skipped
                        if best_pair:  # not vetoed
                            pid = self._open_position(best_pair, best_sig["direction"],
                                                       best_px, mg, pair_lev,
                                                       final_sl, final_tp, dry, ak, asc)
                        if pid:
                            pos = self.state.positions[pid]
                            pc  = GREEN if pos.direction == "LONG" else RED
                            self._log(
                                f"OPENED {pos.direction}{stack_tag} "
                                f"{pair_label(best_pair)} {pair_lev}x  "
                                f"@ ${best_px:,.4f}  "
                                f"LIQ ${pos.liq_price:,.4f}", pc)
                            open_reason = reason or f"Score {best_sig['score']}/9  RSI {best_sig['rsi']:.0f}  {best_sig['trend']} — indicators only (Claude not available)"
                            sl_used = f"SL {final_sl*100:.2f}%  TP {final_tp*100:.2f}%"
                            self._ai_log_event(pid, "TRADE OPENED",
                                f"{pos.direction} {pair_label(best_pair)} @ ${best_px:,.4f}  {sl_used}  conf {decision['confidence'] if decision else '—'}%\n{open_reason}",
                                GREEN if pos.direction=="LONG" else RED)
                            self._refresh_metrics(); self._save()
                            # Force balance refresh after opening position
                            self._balance_fetch = 0
                            self._fetch_live_balance(); self.root.after(0, self._refresh_trades_tab)
                    else:
                        self._log(
                            f"Already in {best_sig['direction']} {best_pair.replace('_USDT','')} "
                            f"— waiting for exit or different pair", DIM)
                else:
                    # All pairs HOLD
                    self._hold_streak += 1
                    # Adaptive threshold — only if toggle is enabled
                    if self.adaptive_var.get():
                        # Adaptive drops: -1.0 at trigger_cy, -1.5 at 2x trigger_cy
                        # Overnight: triggers at 10cy instead of 20cy, floor 3.5 not 4.0
                        base        = self._thresh()
                        trigger_cy  = self._adaptive_trigger_cycle()
                        floor_thr   = self._adaptive_floor()
                        if self._hold_streak == trigger_cy * 2:
                            new_thr = max(floor_thr, round(base - 1.5, 1))
                        elif self._hold_streak == trigger_cy:
                            new_thr = max(floor_thr, round(base - 1.0, 1))
                        else:
                            new_thr = None

                        if new_thr is not None and self._adaptive_thr != new_thr:
                            self._adaptive_thr = new_thr
                            icon = "⚡" if self._hold_streak >= trigger_cy * 2 else "↓"
                            self._log(f"{icon} Adaptive threshold → {new_thr}/9 "
                                      f"(HOLD streak: {self._hold_streak} cycles"
                                      f"{' · overnight' if overnight else ''})", AMBER)
                            self.root.after(0, lambda t=new_thr, s=self._hold_streak, cy=trigger_cy: (
                                self._adaptive_info.config(
                                    text=f"{icon} Active → {t}/9  streak {s}cy  (triggers @{cy}cy)",
                                    fg=AMBER)))
                    else:
                        self._adaptive_thr = None
                    thr_eff = self._adaptive_thr or thr
                    # Re-rank with relaxed threshold
                    if self._adaptive_thr:
                        candidates = [(p, s) for p, s in all_sigs.items()
                                       if s["direction"] in ("LONG","SHORT")
                                       and s["score"] >= thr_eff]
                        candidates.sort(key=lambda x: x[1]["score"], reverse=True)
                        if candidates:
                            bp, bs = candidates[0]
                            self._log(f"Adaptive entry: {bs['direction']} "
                                      f"{pair_label(bp)} score {bs['score']}/9", CYAN)
                            self._last_signal_pair = bp
                            self._last_signal_time = time.time()
                            self._last_signal_dir  = bs["direction"]
                    eff_now = self._adaptive_thr if self._adaptive_thr else thr
                    self._log(f"All pairs HOLD — no signal above threshold {eff_now}/9" + (" (adaptive)" if self._adaptive_thr else ""), DIM)
                    if ck and (time.time() - self._last_claude_call) > 60:
                        def _bg_claude(s=top_sig, c=ck, st=self.state,
                                       sy=top_pair, lv=lev, mg_=mg):
                            reason = claude_reasoning(s, st, sy, lv, mg_, c)
                            if reason:
                                self._log(f"AI (all HOLD): {reason}", PURPLE)
                                self._update_claude_panel(s, reasoning=reason)
                            self._last_claude_call = time.time()
                        threading.Thread(target=_bg_claude, daemon=True).start()

            except Exception as e:
                self._log(f"ERROR: {e}", RED)

            for _ in range(self._ivl()):
                if self._stop_event.is_set(): break
                time.sleep(1)

    def _open_position(self, sym, direction, px, mg, lev, sl_pct, tp_pct,
                        dry, ak, asc, hedge_of=""):
        # Always re-read dry_var to ensure live/paper is respected
        dry = self.dry_var.get()

        # ── ATR-based SL minimum: SL must be outside normal wick noise ────────
        # If the configured SL is tighter than 1.5x ATR, widen it to 1.5x ATR.
        # This prevents SL landing inside the range of normal candle wicks —
        # which causes premature stop-outs before price has a chance to move.
        try:
            candles_for_atr = self.pair_candles.get(sym, [])
            if candles_for_atr:
                atr_raw = atr(candles_for_atr, 14)
                atr_as_pct = atr_raw / px if px > 0 else 0
                atr_min_sl = atr_as_pct * 1.5   # SL must be at least 1.5x ATR from entry
                if sl_pct < atr_min_sl:
                    self._log(
                        f"SL widened {sl_pct*100:.3f}% → {atr_min_sl*100:.3f}% "
                        f"(1.5x ATR {atr_as_pct*100:.3f}%) to clear wick noise", AMBER)
                    sl_pct = atr_min_sl
        except Exception:
            pass  # ATR check is advisory only; never block a trade over it

        # ── Minimum TP enforcement: TP must cover round-trip fee + small profit ──
        # Fee = 0.2% of position notional = 0.2% price move
        # Minimum TP = fee + 0.1% extra = 0.3% price move minimum
        FEE_PCT = 0.002   # 0.2% round-trip taker fee as a price-move fraction
        MIN_TP  = FEE_PCT + 0.001   # fee + 0.1% minimum profit above fees
        if tp_pct < MIN_TP:
            old_tp = tp_pct
            tp_pct = MIN_TP
            self._log(f"TP raised {old_tp*100:.2f}% → {tp_pct*100:.2f}% to cover fees", AMBER)

        if direction == "LONG":
            SL  = round(px * (1 - sl_pct), 6)
            TP  = round(px * (1 + tp_pct), 6)
            LIQ = round(px * (1 - 1 / lev), 6)
        else:
            SL  = round(px * (1 + sl_pct), 6)
            TP  = round(px * (1 - tp_pct), 6)
            LIQ = round(px * (1 + 1 / lev), 6)

        oid = f"DRY-{int(time.time())}"
        if not dry:
            side = 1 if direction == "LONG" else 3
            raw_vol = (mg * lev) / px
            vol     = round_vol(sym, raw_vol)

            # Sanity check — MEXC rejects absurdly large volumes
            if vol > 100_000_000:
                self._log(f"Order skipped: {sym} vol={vol:,.0f} is too large "
                          f"(price too small for margin size)", AMBER)
                return None
            if vol == 0:
                self._log(f"Order skipped: {sym} vol=0 after rounding "
                          f"(margin too small for one contract)", AMBER)
                return None

            self._log(f"Sending order: {sym} {direction} vol={vol} side={side} "
                      f"type=5 openType=1 px={px:.4f}", DIM)

            # ── Try limit order first (0.03% better price = maker fee = 0%) ──────
            LIMIT_OFFSET = 0.0003
            limit_px = round(px * (1 - LIMIT_OFFSET) if direction == "LONG"
                             else px * (1 + LIMIT_OFFSET), 6)
            try:
                lresp = mexc_private("POST", "/api/v1/private/order/submit",
                                     {"symbol": sym, "price": limit_px, "vol": vol,
                                      "side": side, "type": 1, "openType": 1,
                                      "leverage": lev}, ak, asc, dry)
                limit_oid = str(lresp.get("data","")) if lresp.get("success") else None
            except Exception:
                limit_oid = None

            if limit_oid:
                self._log(f"Limit order placed @ ${limit_px:,.6g} — waiting up to 60s", CYAN)
                filled = False
                for _ in range(6):
                    time.sleep(10)
                    try:
                        chk = mexc_private("GET", "/api/v1/private/order/get_order_context",
                                           {"symbol": sym, "orderId": limit_oid}, ak, asc, dry)
                        st  = (chk or {}).get("data", {}).get("state")
                        if st == 2:
                            filled = True
                            fill_px = (chk.get("data",{}).get("dealAvgPrice") or limit_px)
                            px = float(fill_px)
                            break
                        elif st in (4, 5):
                            break
                    except Exception:
                        break
                if filled:
                    oid = limit_oid
                    self._log(f"✓ Limit filled @ ${px:,.6g} (maker fee 0%)", GREEN)
                    # Recompute SL/TP/LIQ at actual fill price
                    if direction == "LONG":
                        SL  = round(px * (1 - sl_pct), 6)
                        TP  = round(px * (1 + tp_pct), 6)
                        LIQ = round(px * (1 - 1/lev),  6)
                    else:
                        SL  = round(px * (1 + sl_pct), 6)
                        TP  = round(px * (1 - tp_pct), 6)
                        LIQ = round(px * (1 + 1/lev),  6)
                else:
                    # Cancel and fall back to market
                    try:
                        mexc_private("POST", "/api/v1/private/order/cancel",
                                     {"symbol": sym, "orderId": limit_oid}, ak, asc, dry)
                    except Exception:
                        pass
                    self._log(f"Limit unfilled — falling back to market", AMBER)
                    limit_oid = None   # fall through to market below
            
            if not limit_oid:
                # Market order (original logic with retry)
                pass  # fall through to existing market order block below

            if not limit_oid:
              try:
                resp = mexc_private("POST", "/api/v1/private/order/submit",
                                    {"symbol": sym, "price": 0, "vol": vol,
                                     "side": side, "type": 5,
                                     "openType": 1, "leverage": lev},
                                    ak, asc, dry)
                # Log full response so we can diagnose rejections
                if resp.get("success"):
                    oid = str(resp.get("data", oid))
                    self._log(f"Order accepted: {oid}", GREEN)
                else:
                    code = resp.get("code", "?")
                    msg  = resp.get("message", resp.get("msg", str(resp)))
                    if code == 2015:
                        # Precision error — try with one fewer decimal place
                        cur_prec = _learned_precision.get(sym, PAIR_VOL_PRECISION.get(sym, 2))
                        # If already at 0, this pair might need no decimals
                        new_prec = max(0, cur_prec - 1)
                        _learned_precision[sym] = new_prec
                        vol2 = round_vol(sym, (mg * lev) / px)
                        self._log(f"Precision retry: {sym} {cur_prec}dp → {new_prec}dp  vol={vol2}", AMBER)
                        resp2 = mexc_private("POST", "/api/v1/private/order/submit",
                                            {"symbol": sym, "price": 0, "vol": vol2,
                                             "side": side, "type": 5,
                                             "openType": 1, "leverage": lev},
                                            ak, asc, dry)
                        if resp2.get("success"):
                            oid = str(resp2.get("data", oid))
                            self._log(f"Order accepted on retry: {oid}", GREEN)
                        else:
                            code2 = resp2.get("code","?")
                            msg2  = resp2.get("message", resp2.get("msg", str(resp2)))
                            self._log(f"Order REJECTED again: code={code2} msg={msg2}", RED)
                            return None
                    else:
                        self._log(f"Order REJECTED: code={code} msg={msg}", RED)
                        self._log(f"  vol={vol} sym={sym} side={side}", RED)
                        return None
              except Exception as e:
                self._log(f"Order exception: {e}", RED)
                return None

        pid = str(uuid.uuid4())[:8]
        pos = Position(id=pid, symbol=sym, direction=direction,
                       entry_price=px, margin=mg, leverage=lev,
                       size_usdt=mg * lev, stop_loss=SL,
                       take_profit=TP, liq_price=LIQ,
                       opened_at=datetime.now(timezone.utc).isoformat(),
                       hedge_of=hedge_of, order_id=oid)
        self.state.positions[pid] = pos
        # Deduct margin from paper balance on open (returned + pnl on close)
        if dry:
            self.state.balance = round(self.state.balance - mg, 4)
        return pid

    def _check_exit(self, pos, px, lev, dry, ak, asc):
        dry = self.dry_var.get()  # always re-read
        d = pos.direction

        # ── Trailing stop: move SL up as trade profits ────────────────────────
        # Trail distance = half the original SL distance from entry
        # Only trail once in profit by at least that same distance (avoids premature triggers)
        sl_dist = abs(pos.entry_price - pos.stop_loss)   # original SL distance in price
        trail_dist = sl_dist * 0.5                        # trail at 50% of SL distance
        if d == "LONG":
            profit_dist = px - pos.entry_price
            if profit_dist >= sl_dist:                   # only trail once meaningfully in profit
                new_trail_sl = px - sl_dist              # trail SL = current price minus original SL gap
                if new_trail_sl > pos.stop_loss:
                    pos.stop_loss = round(new_trail_sl, 8)
        else:  # SHORT
            profit_dist = pos.entry_price - px
            if profit_dist >= sl_dist:
                new_trail_sl = px + sl_dist
                if new_trail_sl < pos.stop_loss:
                    pos.stop_loss = round(new_trail_sl, 8)

        # ── Partial TP: at 75% of TP distance, lock in half and move SL to breakeven
        tp_total = abs(pos.take_profit - pos.entry_price)
        if tp_total > 0:
            if d == "LONG":
                tp_progress = (px - pos.entry_price) / tp_total
            else:
                tp_progress = (pos.entry_price - px) / tp_total
            partial_key = f"_partial_tp_{pos.id}"
            if tp_progress >= 0.75 and not getattr(self, partial_key, False):
                setattr(self, partial_key, True)
                # Move SL to breakeven + fee buffer (0.25% to cover round-trip fee)
                fee_buffer = pos.entry_price * 0.0025
                if d == "LONG":
                    new_be_sl = pos.entry_price + fee_buffer
                    if new_be_sl > pos.stop_loss:
                        pos.stop_loss = round(new_be_sl, 8)
                        self._log(f"🔒 Partial TP {pair_label(pos.symbol)}: "
                                  f"SL moved to breakeven+fee @ ${pos.stop_loss:,.4f}", CYAN)
                else:
                    new_be_sl = pos.entry_price - fee_buffer
                    if new_be_sl < pos.stop_loss:
                        pos.stop_loss = round(new_be_sl, 8)
                        self._log(f"🔒 Partial TP {pair_label(pos.symbol)}: "
                                  f"SL moved to breakeven+fee @ ${pos.stop_loss:,.4f}", CYAN)
                self._ai_log_event(pos.id, "🔒 BREAKEVEN LOCK",
                    f"75% to TP reached — SL moved to ${pos.stop_loss:,.4f} (breakeven+fee)", CYAN)

        htp  = (px >= pos.take_profit) if d == "LONG" else (px <= pos.take_profit)
        hsl  = (px <= pos.stop_loss)   if d == "LONG" else (px >= pos.stop_loss)
        hliq = (px <= pos.liq_price)   if d == "LONG" else (px >= pos.liq_price)
        if not (htp or hsl or hliq): return False, None, 0

        if hliq:
            pnl = -pos.margin; status = "LIQUIDATED"; ep = pos.liq_price
            self.state.liqs += 1
        else:
            raw = (px - pos.entry_price) / pos.entry_price if d == "LONG" \
                  else (pos.entry_price - px) / pos.entry_price
            gross_pnl = raw * pos.leverage * pos.margin
            # Deduct round-trip fees: 0.1% taker open + 0.1% taker close = 0.2% of position size
            fee = pos.size_usdt * 0.002   # 0.2% of notional position
            pnl = round(gross_pnl - fee, 4); ep = px
            status = "WIN" if pnl >= 0 else "LOSS"
            if pnl >= 0: self.state.wins   += 1
            else:        self.state.losses += 1

        if not dry:
            side = 4 if d == "LONG" else 2
            vol  = round_vol(pos.symbol, pos.size_usdt / pos.entry_price)
            try:
                mexc_private("POST", "/api/v1/private/order/submit",
                             {"symbol": pos.symbol, "price": 0, "vol": vol,
                              "side": side, "type": 5, "openType": 1},
                             ak, asc, dry)
            except Exception: pass

        self.state.total_pnl  = round(self.state.total_pnl + pnl, 4)
        # Return margin + pnl to balance (margin was deducted on open in paper mode)
        if self.dry_var.get():
            self.state.balance = round(self.state.balance + pos.margin + pnl, 4)
        else:
            self.state.balance = round(self.state.balance + pnl, 4)
        self.state.trades.append({
            "symbol": pos.symbol, "direction": d,
            "entry_price": pos.entry_price, "exit_price": ep,
            "margin": pos.margin, "leverage": pos.leverage,
            "pnl_usdt": pnl, "status": status, "hedge": bool(pos.hedge_of),
            "opened_at": pos.opened_at,
            "closed_at": datetime.now(timezone.utc).isoformat()})

        # ── Pair cooldown + losing streak tracking ───────────────────────────
        if pnl < 0:
            self._pair_cooldown[pos.symbol] = time.time()
            self._losing_streak = getattr(self, "_losing_streak", 0) + 1
            # Reduce leverage after 3 consecutive losses
            if self._losing_streak == 3:
                try:
                    cur_lev = self._lev()
                    if self._peak_leverage is None:
                        self._peak_leverage = cur_lev
                    opts = self._lev_opts(self.pair_cb.get())
                    cur_idx = next((i for i,o in enumerate(opts) if o == f"{cur_lev}x"), -1)
                    if cur_idx > 0:
                        new_lev = opts[cur_idx - 1]
                        self.root.after(0, lambda l=new_lev: (
                            self.lev_cb.set(l), self._on_lev()))
                        self._log(f"⚠ 3 consecutive losses — leverage reduced to {new_lev}", AMBER)
                except Exception:
                    pass
        else:
            prev_streak = getattr(self, "_losing_streak", 0)
            self._losing_streak = 0
            # Restore leverage after 3 consecutive wins following a reduction
            if prev_streak == 0 and self._peak_leverage is not None:
                wins_since = sum(1 for t in self.state.trades[-3:] if t.get("pnl_usdt",0) >= 0)
                if wins_since >= 3:
                    try:
                        self.root.after(0, lambda l=f"{self._peak_leverage}x": (
                            self.lev_cb.set(l), self._on_lev()))
                        self._log(f"✓ 3 wins — leverage restored to {self._peak_leverage}x", GREEN)
                        self._peak_leverage = None
                    except Exception:
                        pass

        del self.state.positions[pos.id]
        return True, status, pnl

# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY
# ══════════════════════════════════════════════════════════════════════════════
def main():
    import subprocess, sys
    for pkg in ["anthropic", "matplotlib"]:
        try: __import__(pkg)
        except ImportError:
            print(f"Installing {pkg}…")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

    root = tk.Tk()
    try:
        from ctypes import windll, c_int, byref, sizeof
        windll.dwmapi.DwmSetWindowAttribute(
            windll.user32.GetParent(root.winfo_id()), 20, byref(c_int(1)), sizeof(c_int))
    except Exception: pass

    app = HermesBotApp(root)

    def _close():
        if app.bot_running:
            if not messagebox.askyesno("Bot running", "Stop bot and exit?"): return
            app._stop()
        for t in [app._chart_timer, app._dock_timer]:
            if t: root.after_cancel(t)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _close)
    root.mainloop()

if __name__ == "__main__":
    main()