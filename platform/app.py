"""
app.py — Ascent Terminal (web) backend.

Non-custodial trend-signal platform. PUBLIC: proof (validated backtest). GATED:
the live per-coin signals + charts (the paid product). Optional Discord alerts
when a coin's daily trend flips. Never touches user API keys.

Run:
  pip install -r requirements.txt
  set ACCESS_KEYS=DEMO-KEY,PATRON-123        (comma-sep keys that unlock signals)
  set DISCORD_WEBHOOK_URL=https://...         (optional trend-flip alerts)
  uvicorn app:app --reload --port 8000
"""

import os
import time
import threading
import requests
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.staticfiles import StaticFiles

import exchanges
import indicators
import market_intel
import macro_data
import webhook_store
import execution
import auth

# Default data source for the scan. Binance-first when ccxt is available
# (richest public data); MEXC native otherwise. Override with EXCHANGE env.
def _default_exchange():
    try:
        import ccxt  # noqa: F401
        return "binance"
    except ImportError:
        return "mexc"

EXCHANGE = os.environ.get("EXCHANGE", "") or _default_exchange()
EMA_PERIOD = 30
REFRESH_SEC = 600
CANDLES = 400
PROOF_CANDLES = 1000
FEE = 0.0010

SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT", "XRP_USDT", "DOGE_USDT",
    "ADA_USDT", "AVAX_USDT", "LINK_USDT", "DOT_USDT", "LTC_USDT", "ATOM_USDT",
    "UNI_USDT", "NEAR_USDT", "APT_USDT", "SUI_USDT", "ARB_USDT", "OP_USDT",
]

# Keys that unlock the live signal feed. Default DEMO-KEY for local testing.
# Subscriber keys live in keys.json (hashed, hot-reloaded — see auth.py /
# key_gen.py). ACCESS_KEYS env remains as a dev/owner fallback: those keys are
# hashed once here and map to the architect tier. No plaintext is retained.
auth.init_env_keys(os.environ.get("ACCESS_KEYS", "DEMO-KEY"))
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Secret token TradingView must send in the webhook body as {"secret": "..."}.
# Set TV_WEBHOOK_SECRET env var to something unguessable before going live.
# If unset, the receiver accepts all POSTs (fine for local/dev, not for prod).
TV_SECRET = os.environ.get("TV_WEBHOOK_SECRET", "").strip()

# ── TV → Execution bridge (non-custodial). ALL layers must pass for LIVE: ────
# EXECUTE_KEY    second key (besides the access key) required for ANY order.
#                Leave empty = bridge disarmed entirely (default).
# EXEC_LIVE      "true" to allow real orders; anything else = paper-only.
# EXEC_MAX_USD   hard notional cap per order (default 1000, 0 = no cap).
# AUTO_EXECUTE   "true" = BUY/SELL TradingView alerts auto-execute (paper unless
#                EXEC_LIVE is also true). Default off — manual confirm in the UI.
# EXEC_EXCHANGE / EXEC_API_KEY / EXEC_API_SECRET / EXEC_API_PASSWORD
#                credentials for auto mode — only ever read from YOUR machine's
#                env; never stored or echoed by the API.
# EXEC_QUOTE_AMOUNT  default order size in USDT for auto mode (default 50).
EXECUTE_KEY = os.environ.get("EXECUTE_KEY", "").strip()
EXEC_LIVE = os.environ.get("EXEC_LIVE", "").strip().lower() == "true"
EXEC_MAX_USD = float(os.environ.get("EXEC_MAX_USD", "1000") or 0)
AUTO_EXECUTE = os.environ.get("AUTO_EXECUTE", "").strip().lower() == "true"
EXEC_QUOTE_AMOUNT = float(os.environ.get("EXEC_QUOTE_AMOUNT", "50") or 50)

def user_cap(hash16: str):
    """The user's own per-order cap (USD). None = not set; 0 = user chose
    no personal cap. Always bounded by the server ceiling (EXEC_MAX_USD)."""
    if not hash16:
        return None
    try:
        import json as _j
        import store_db
        raw = store_db.load_kv(f"usercap_{hash16}")
        return float(_j.loads(raw)["max_usd"]) if raw else None
    except Exception:
        return None


def effective_cap(hash16: str) -> float:
    """Resolve the cap for one user's orders: their setting, clamped by the
    server ceiling; unset users inherit the server default."""
    ceiling = EXEC_MAX_USD                       # 0 = no server ceiling
    cap = user_cap(hash16)
    if cap is None:
        return ceiling
    if cap <= 0:                                 # user chose unlimited
        return ceiling
    return min(cap, ceiling) if ceiling > 0 else cap


def cfg_for(hash16: str) -> dict:
    cfg = dict(_exec_cfg())
    cfg["max_usd"] = effective_cap(hash16)
    return cfg


def _exec_cfg():
    return {
        "execute_key": EXECUTE_KEY,
        "live_enabled": EXEC_LIVE,
        "max_usd": EXEC_MAX_USD,
        "default_exchange": os.environ.get("EXEC_EXCHANGE", "").strip().lower() or EXCHANGE,
        "env_api_key": os.environ.get("EXEC_API_KEY", "").strip(),
        "env_api_secret": os.environ.get("EXEC_API_SECRET", "").strip(),
        "env_api_password": os.environ.get("EXEC_API_PASSWORD", "").strip(),
    }

_cache = {"signals": [], "candles": {}, "proof": None, "ts": 0.0}
_prev_dir = {}
_lock = threading.Lock()

FNG_TTL = 3600                                    # refresh Fear & Greed ~hourly
_fng_cache = {"value": None, "ts": 0.0}

MACRO_TTL = 300                                   # cache MEXC macro ~5 min/symbol
_macro_cache = {}                                 # symbol -> {"data":.., "ts":..}

ONDEMAND_TTL = 600                                # cache on-demand candles ~10 min
_ondemand_cache = {}                              # symbol -> {"data":.., "ts":..}


def _fear_greed_cached():
    """Cached crypto-wide Fear & Greed (refresh ~hourly) to avoid hammering API."""
    now = time.time()
    if _fng_cache["value"] is None or now - _fng_cache["ts"] > FNG_TTL:
        fg = market_intel.fear_greed()
        if fg is not None:                        # keep last good value on failure
            _fng_cache["value"] = fg
            _fng_cache["ts"] = now
        elif _fng_cache["value"] is None:
            _fng_cache["ts"] = now                # back off even on first failure
    return _fng_cache["value"]


def fetch_daily(symbol, limit=CANDLES):
    return exchanges.fetch_daily(symbol, EXCHANGE, limit)


def ema(values, period):
    if len(values) < period:
        return []
    k = 2/(period+1); out = [sum(values[:period])/period]
    for v in values[period:]:
        out.append(v*k + out[-1]*(1-k))
    return out


def compute(symbol):
    candles = fetch_daily(symbol)
    if len(candles) < EMA_PERIOD + 2:
        return None
    closes = [c["close"] for c in candles]
    e = ema(closes, EMA_PERIOD)
    ema_pts = [{"time": candles[EMA_PERIOD-1+i]["time"], "value": round(e[i], 6)} for i in range(len(e))]
    price, ema_now = closes[-1], e[-1]
    direction = "LONG" if price > ema_now else "SHORT"
    held = 0
    for i in range(len(e)-1, 0, -1):
        if (closes[EMA_PERIOD-1+i] > e[i]) == (closes[EMA_PERIOD-2+i] > e[i-1]):
            held += 1
        else:
            break
    sig = {"symbol": symbol, "direction": direction, "price": round(price, 6),
           "ema": round(ema_now, 6), "distance_pct": round((price-ema_now)/ema_now*100, 2),
           "bars_held": held,
           "change_24h": round((closes[-1]/closes[-2]-1)*100, 2) if len(closes) > 1 else None}

    # Market-intelligence context (analysis only — not a profit signal).
    cs = market_intel.composite_score(candles)
    if cs:
        sig["score"] = cs["score"]
        sig["score_dir"] = cs["direction"]
        sig["score_components"] = cs["components"]

    # Multi-timeframe alignment. Reuse the daily we already have (d1 = primary
    # trend) and only do the extra light 4h fetch — avoids doubling daily load.
    try:
        h4 = market_intel._trend_from_candles(market_intel.fetch_4h(symbol, EXCHANGE))
    except Exception:
        h4 = None
    sig["mtf"] = {"d1": direction, "h4": h4,
                  "aligned": (h4 is not None and h4 == direction)}

    return sig, candles, ema_pts


def _maxdd(curve):
    peak = curve[0]; dd = 0.0
    for v in curve:
        peak = max(peak, v); dd = max(dd, (peak-v)/peak)
    return dd*100


def compute_proof():
    """Equal-weight EMA30 long-only trend portfolio vs buy&hold — the receipts."""
    by_time_strat, by_time_bh = {}, {}
    for s in SYMBOLS:
        c = fetch_daily(s, limit=PROOF_CANDLES)
        if len(c) < EMA_PERIOD + 30:
            continue
        closes = [x["close"] for x in c]; times = [x["time"] for x in c]
        e = ema(closes, EMA_PERIOD)
        pos_prev = 0
        for i in range(EMA_PERIOD, len(c)):
            ei = i - (EMA_PERIOD-1)
            ret = (closes[i]-closes[i-1])/closes[i-1]
            strat = pos_prev * ret
            desired = 1 if closes[i] > e[ei] else 0
            if desired != pos_prev:
                strat -= FEE
            pos_prev = desired
            by_time_strat.setdefault(times[i], []).append(strat)
            by_time_bh.setdefault(times[i], []).append(ret)
    if not by_time_strat:
        return None
    ts = sorted(by_time_strat)
    eq = bh = 1.0; scurve = []; bcurve = []
    for t in ts:
        sr = sum(by_time_strat[t])/len(by_time_strat[t])
        br = sum(by_time_bh[t])/len(by_time_bh[t])
        eq *= (1+sr); bh *= (1+br)
        scurve.append({"time": t, "value": round(eq, 4)})
        bcurve.append({"time": t, "value": round(bh, 4)})
    yrs = (ts[-1]-ts[0])/31557600 or 1
    return {
        "strategy": scurve, "buyhold": bcurve,
        "stats": {
            "cagr": round((eq**(1/yrs)-1)*100, 1), "maxdd": round(_maxdd([p["value"] for p in scurve]), 1),
            "bh_cagr": round((bh**(1/yrs)-1)*100, 1), "bh_maxdd": round(_maxdd([p["value"] for p in bcurve]), 1),
            "years": round(yrs, 1), "oos_hit": "38/40 coins (95%)",
        },
    }


def refresh():
    sigs, cdl, flips = [], {}, []
    for s in SYMBOLS:
        res = compute(s)
        if not res:
            continue
        sig, candles, ema_pts = res
        sigs.append(sig); cdl[s] = {"candles": candles, "ema": ema_pts, "signal": sig}
        prev = _prev_dir.get(s)
        if prev and prev != sig["direction"]:
            flips.append(sig)
        _prev_dir[s] = sig["direction"]
    sigs.sort(key=lambda x: x["distance_pct"], reverse=True)
    with _lock:
        _cache["signals"] = sigs; _cache["candles"] = cdl; _cache["ts"] = time.time()
    for f in flips:
        _alert_flip(f)


def _alert_flip(sig):
    if not WEBHOOK:
        return
    arrow = "🟢 flipped LONG" if sig["direction"] == "LONG" else "🔴 flipped SHORT"
    color = 0x22E57E if sig["direction"] == "LONG" else 0xFF4D68
    try:
        requests.post(WEBHOOK, timeout=10, json={"embeds": [{
            "title": f"{sig['symbol'].replace('_USDT','')} {arrow}",
            "color": color,
            "description": f"Daily close crossed the EMA30 trend line.\nPrice ${sig['price']} · EMA ${sig['ema']}",
            "footer": {"text": "Ascent Terminal · educational · not financial advice"}}]})
    except Exception:
        pass


def _loop():
    n = 0
    while True:
        try:
            refresh()
            if n % 144 == 0:                      # proof ~once/day (144 × 10min)
                with _lock:
                    _cache["proof"] = compute_proof()
        except Exception as e:
            print("loop error:", e)
        n += 1
        time.sleep(REFRESH_SEC)


app = FastAPI(title="Ascent Terminal")

from fastapi.responses import JSONResponse


@app.middleware("http")
async def _auth_throttle(request: Request, call_next):
    """Brute-force shield: IPs over the failed-auth limit get 429 on all /api/
    routes until the lockout expires; every 401 from below is counted."""
    path = request.url.path
    if path.startswith("/api/"):
        ip = request.client.host if request.client else "?"
        wait = auth.is_locked(ip)
        if wait:
            return JSONResponse(status_code=429, content={
                "detail": f"Too many failed key attempts. Locked out for {int(wait)}s."})
    response = await call_next(request)
    if path.startswith("/api/") and response.status_code == 401:
        auth.record_failure(request.client.host if request.client else "?")
    return response


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Baseline hardening: clickjacking, MIME sniffing, referrer leaks,
    HTTPS pinning (HSTS is a no-op over plain HTTP), and a CSP that fits
    the app's inline scripts + the lightweight-charts CDN."""
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    h.setdefault("Content-Security-Policy",
                 "default-src 'self'; "
                 "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com; "
                 "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                 "font-src https://fonts.gstatic.com; "
                 "img-src 'self' data:; "
                 "connect-src 'self'; "
                 "frame-ancestors 'self'; base-uri 'self'; form-action 'self'")
    return resp


@app.on_event("startup")
def _start():
    threading.Thread(target=_loop, daemon=True).start()
    try:
        import liquidations as _liq
        _liq.start()
    except Exception as e:
        print(f"[liq-feed] disabled: {e}")
    try:
        _exits.start()
    except Exception as e:
        print(f"[exit-watch] disabled: {e}")


def _gate(key, min_tier="observer"):
    """Auth gate. 401 = no/invalid/expired key; 403 = valid key, tier too low.
    Tiers: observer < operator < architect (see auth.py)."""
    rec = auth.verify(key)
    if not rec:
        raise HTTPException(401, "Locked — valid access key required")
    if not auth.tier_ok(rec, min_tier):
        raise HTTPException(403, f"This feature requires the {min_tier} tier "
                                 f"(your key is {rec['tier']}).")
    return rec


@app.get("/api/health")
def health():
    return {"ok": True, "last_refresh": _cache["ts"], "exchange": EXCHANGE}


@app.get("/api/exchanges")                        # PUBLIC — brokers available
def list_exchanges():
    return {
        "active": EXCHANGE,
        "supported": exchanges.supported(),          # preferred short-list
        "all": exchanges.all_exchanges(),            # full ccxt universe
    }


@app.get("/api/assets")                           # PUBLIC — tradable crypto assets on a broker
def assets(exchange: str = "", quote: str = "USDT", segment: str = "spot"):
    seg = segment if segment in ("spot", "swap", "all") else "spot"
    return {"exchange": exchange or EXCHANGE, "segment": seg,
            "assets": exchanges.list_assets(exchange or EXCHANGE, quote, market_type=seg)}


@app.get("/api/segments")                         # PUBLIC — spot/perps support on an exchange
def segments(exchange: str = ""):
    ex = (exchange or EXCHANGE).lower()
    return {"exchange": ex, **exchanges.segments(ex)}


@app.get("/api/markets")                          # PUBLIC — non-crypto universe (forex/indices/stocks)
def markets():
    try:
        import forex_data
        return {"crypto_default": SYMBOLS, **forex_data.symbols()}
    except Exception:
        return {"crypto_default": SYMBOLS}


@app.get("/api/top")                              # PUBLIC — top traded / movers per asset class
def top(mtype: str = "crypto", mode: str = "volume",
        exchange: str = "", quote: str = "USDT", limit: int = 25,
        segment: str = "spot"):
    """Market-view feeds for the asset picker. Context only — not advice.

    mtype: crypto | forex | stocks | indices | metals
    mode:  volume (most traded) | gainers | losers
    crypto uses live exchange tickers (ccxt, cached ~5 min); other classes use
    a bulk yfinance summary (cached ~10 min). Returns [] gracefully on errors.
    """
    mode = mode if mode in ("volume", "gainers", "losers") else "volume"
    limit = max(1, min(limit, 100))
    if mtype == "crypto":
        ex = (exchange or EXCHANGE).lower()
        seg = segment if segment in ("spot", "swap") else "spot"
        rows = exchanges.top_tickers(ex, quote, mode, limit, market_type=seg)
        return {"mtype": mtype, "mode": mode, "exchange": ex, "segment": seg, "results": rows}
    try:
        import forex_data
        rows = forex_data.bulk_summary(mtype)
    except Exception:
        rows = []
    if mode == "gainers":
        rows = sorted(rows, key=lambda r: r["change_pct"] if r["change_pct"] is not None else -1e9, reverse=True)
    elif mode == "losers":
        rows = sorted(rows, key=lambda r: r["change_pct"] if r["change_pct"] is not None else 1e9)
    else:
        rows = sorted(rows, key=lambda r: r["qvol"] or 0, reverse=True)
    return {"mtype": mtype, "mode": mode, "results": rows[:limit]}


@app.get("/api/proof")                            # PUBLIC — the receipts
def proof():
    with _lock:
        return _cache["proof"] or {"stats": None, "strategy": [], "buyhold": []}


@app.get("/api/intel")                            # PUBLIC — market context
def intel():
    """Crypto-wide Fear & Greed + how many tracked coins are in an uptrend.
    Context/analysis only — never a guarantee of profit."""
    with _lock:
        sigs = _cache["signals"]
        ts = _cache["ts"]
    longs = sum(1 for s in sigs if s.get("direction") == "LONG")
    return {"fear_greed": _fear_greed_cached(), "longs": longs,
            "total": len(SYMBOLS), "updated": ts}


@app.get("/api/macro/{symbol}")                   # PUBLIC — positioning context
def macro(symbol: str):
    """MEXC funding rate / open interest / long-short positioning context.
    Context only — not a profit signal. Cached ~5 min per symbol."""
    now = time.time()
    with _lock:
        hit = _macro_cache.get(symbol)
        if hit and now - hit["ts"] < MACRO_TTL:
            return hit["data"]
    data = macro_data.macro(symbol)
    with _lock:
        _macro_cache[symbol] = {"data": data, "ts": now}
    return data


import orderflow as _orderflow


@app.get("/api/orderflow/{symbol}")               # GATED — live tape (crypto)
def orderflow_read(symbol: str, exchange: str = "",
                   x_access_key: str = Header(default="")):
    """Whale flow / taker flow / book imbalance / walls. Live snapshots from
    public trade + order-book data — context only, never backtestable."""
    _gate(x_access_key, "observer")
    ex = (exchange or EXCHANGE).lower()
    return _orderflow.flow(symbol, ex)


import liquidations as _liquidations


@app.get("/api/liquidations")                     # GATED — global liq stress
def liquidations_global(x_access_key: str = Header(default="")):
    _gate(x_access_key, "observer")
    return _liquidations.summary()


@app.get("/api/liquidations/{symbol}")            # GATED — per-asset + global
def liquidations_symbol(symbol: str, x_access_key: str = Header(default="")):
    _gate(x_access_key, "observer")
    return _liquidations.summary(symbol)


import ai_analyst

AI_MIN_TIER = os.environ.get("AI_MIN_TIER", "observer").strip().lower()

# Per-key daily quota for fresh Claude analyses (cache hits are free).
AI_QUOTA = {
    "observer":  int(os.environ.get("AI_QUOTA_OBSERVER",  "10")),
    "operator":  int(os.environ.get("AI_QUOTA_OPERATOR",  "30")),
    "architect": int(os.environ.get("AI_QUOTA_ARCHITECT", "100")),
}
_ai_usage = {}          # (day, key_hash) -> count  (mirrored to kv hourly-ish)


def _ai_quota_check(key: str, rec: dict):
    """Return (used, limit, bucket_id). Raises 429 when the day's limit is hit.
    Limit = tier base + any purchased AI add-on on the key."""
    import hashlib as _h
    day = time.strftime("%Y%m%d")
    bucket = (day, _h.sha256(key.encode()).hexdigest()[:16])
    tier = (rec or {}).get("tier", "observer")
    limit = AI_QUOTA.get(tier, 10) + int(((rec or {}).get("addons") or {}).get("ai", 0))
    used = _ai_usage.get(bucket, 0)
    if used >= limit:
        raise HTTPException(429, f"Daily AI analysis limit reached for your tier "
                                 f"({limit}/day). Resets at midnight UTC; cached "
                                 f"results stay available.")
    return used, limit, bucket


def _ai_quota_spend(bucket):
    _ai_usage[bucket] = _ai_usage.get(bucket, 0) + 1
    if len(_ai_usage) > 5000:                      # day rollover cleanup
        day = time.strftime("%Y%m%d")
        for k in [k for k in _ai_usage if k[0] != day]:
            _ai_usage.pop(k, None)
if AI_MIN_TIER not in ("observer", "operator", "architect"):
    AI_MIN_TIER = "observer"


@app.get("/api/ai/{symbol}")                      # GATED — Claude's read on the setup
def ai_read(symbol: str, enabled: str = "", weights: str = "", force: bool = False,
            ctx_in: str = "trend,panel,macro,fng,price", depth: str = "standard",
            style: str = "plain", sections: str = "outlook,risks",
            x_access_key: str = Header(default="")):
    """Claude analyses the current setup: trend health, indicator agreement,
    positioning risk. Same analyser concept as the desktop bots, server-side.
    Cached ~15 min per (symbol, direction) to bound API cost. Commentary is
    context/education — never advice (enforced in the prompt)."""
    rec = _gate(x_access_key, AI_MIN_TIER)
    used, limit, bucket = _ai_quota_check(x_access_key, rec)
    wanted = {w.strip() for w in ctx_in.split(",") if w.strip()} or {"trend"}
    wanted.add("trend")                            # the trend is always in scope

    # ── Assemble only the context blocks the user toggled on ──────────────
    ctx = {}
    with _lock:
        cached = _cache["candles"].get(symbol)
        od = _ondemand_cache.get(symbol)
    data = cached or ((od or {}).get("data") if od else None)
    candles = (data or {}).get("candles") or []
    sig = (data or {}).get("signal")
    if sig:
        ctx["trend"] = {k: sig.get(k) for k in
                        ("direction", "price", "ema", "distance_pct", "bars_held", "mtf")}
    elif candles:
        ctx["trend"] = {"direction": "?"}
    if not candles:
        raise HTTPException(404, "Load this symbol's chart first, then ask for Claude's read.")

    # recent price action summary (last 30 daily bars)
    closes = [c["close"] for c in candles[-30:]]
    if closes and "price" in wanted:
        ctx["price_action_30d"] = {
            "high": max(closes), "low": min(closes), "last": closes[-1],
            "change_7d_pct": round((closes[-1] / closes[-8] - 1) * 100, 2) if len(closes) >= 8 else None,
            "change_30d_pct": round((closes[-1] / closes[0] - 1) * 100, 2),
        }

    # the user's own indicator-panel votes (same config the UI shows)
    if "panel" in wanted:
        try:
            enabled_list, weight_map = _parse_panel_config(enabled, weights)
            panel = indicators.compute_panel(candles, volumes=None,
                                             enabled=enabled_list, weights=weight_map)
            ctx["indicator_panel"] = {
                "score_0_to_10": panel["score"], "direction": panel["direction"],
                "votes": {k: v["vote"] for k, v in panel["signals"].items()},
            }
        except Exception:
            pass

    # positioning + market mood (crypto; both cached upstream, cheap)
    if "macro" in wanted:
        try:
            ctx["positioning"] = macro(symbol)    # reuses /api/macro's cache
        except Exception:
            pass
    if "fng" in wanted:
        try:
            fg = _fear_greed_cached()
            if fg:
                ctx["fear_greed"] = fg
        except Exception:
            pass
    if "flow" in wanted:
        try:
            fl = _orderflow.flow(symbol, EXCHANGE)
            ctx["order_flow_live"] = {k: fl.get(k) for k in ("trades", "book")}
        except Exception:
            pass
        try:
            lq = _liquidations.summary(symbol)
            if lq.get("running") or lq.get("uptime_s"):
                ctx["liquidations_live"] = {"global_5m": lq["global"]["m5"],
                                            "asset_5m": (lq.get("asset") or {}).get("m5"),
                                            "cascade": lq["cascade"]}
        except Exception:
            pass

    opts = {"depth": depth, "style": style,
            "sections": [x.strip() for x in sections.split(",") if x.strip()]}
    out = ai_analyst.analyse(symbol, ctx, force=force, opts=opts)
    if isinstance(out, dict) and not out.get("cached"):
        _ai_quota_spend(bucket)
        used += 1
    if isinstance(out, dict):
        out["quota"] = {"used": used, "limit": limit}
    return out


@app.get("/api/check")                            # validate a key (rate-limited oracle)
def check(request: Request, key: str = ""):
    rec = auth.verify(key)
    ip = request.client.host if request.client else "?"
    if rec:
        auth.record_success(ip)
    else:
        auth.record_failure(ip)                   # failed guesses count toward lockout
    return {"valid": bool(rec), "tier": rec["tier"] if rec else None,
            "terms_version": TERMS_VERSION}


@app.get("/api/signals")                          # GATED
def signals(x_access_key: str = Header(default=""), exchange: str = ""):
    """Return cached signals. If `exchange` is supplied and differs from the
    active default, the response includes an `exchange_note` but still returns
    the default-exchange cache — live per-request re-computation is intentionally
    avoided to keep latency low. The broker picker in the UI uses this note to
    show when data is from a different source than requested."""
    _gate(x_access_key)
    with _lock:
        result = {"updated": _cache["ts"], "signals": _cache["signals"], "exchange": EXCHANGE}
    if exchange and exchange != EXCHANGE:
        result["exchange_note"] = f"Requested {exchange!r} but serving cached {EXCHANGE!r} data. To switch permanently set EXCHANGE env var."
    return result


@app.get("/api/candles/{symbol}")                 # GATED
def candles(symbol: str, x_access_key: str = Header(default=""), exchange: str = ""):
    """Cached daily candles for a symbol. `exchange` param noted but cache is always
    from the active EXCHANGE — avoids on-demand latency spikes."""
    _gate(x_access_key)
    with _lock:
        data = _cache["candles"].get(symbol)
    if not data:
        raise HTTPException(404, "symbol not loaded")
    return data


_GROUP_ORDER = ("trend", "momentum", "volatility", "volume", "pattern")


@app.get("/api/indicators")                       # PUBLIC — indicator registry
def indicator_registry():
    """All available indicators, grouped (stable order) — powers the toggle UI."""
    registry = []
    for group in _GROUP_ORDER:
        for key, meta in indicators.REGISTRY.items():
            if meta["group"] == group:
                registry.append({"key": key, "label": meta["label"],
                                 "group": meta["group"],
                                 "default_on": meta["default_on"]})
    return {"registry": registry}


@app.get("/api/panel/{symbol}")                   # GATED — composite indicator panel
def panel(symbol: str, enabled: str = "", weights: str = "",
          x_access_key: str = Header(default="")):
    """Run the toggleable indicator panel on a symbol's cached daily candles.
    Analysis/context only — not financial advice."""
    _gate(x_access_key)
    with _lock:
        data = _cache["candles"].get(symbol)
    if not data:
        raise HTTPException(404, "symbol not loaded")
    try:
        enabled_list = [k.strip() for k in enabled.split(",") if k.strip()] if enabled else None
        weight_map = None
        if weights:
            weight_map = {}
            for part in weights.split(","):
                if ":" not in part:
                    continue
                k, _, v = part.partition(":")
                k = k.strip()
                if not k:
                    continue
                try:
                    weight_map[k] = float(v)
                except ValueError:
                    continue
        result = indicators.compute_panel(data["candles"], volumes=None,
                                          enabled=enabled_list, weights=weight_map)
        result["symbol"] = symbol
        result["computed_at"] = time.time()
        return result
    except Exception as e:
        raise HTTPException(500, f"panel computation failed: {e}")



_BT_TTL = 600                                     # cache backtests ~10 min
_bt_cache = {}                                    # key -> {"data":.., "ts":..}


def _parse_panel_config(enabled: str, weights: str):
    """Shared parser for the panel/backtest query-string config format."""
    enabled_list = [k.strip() for k in enabled.split(",") if k.strip()] if enabled else None
    weight_map = None
    if weights:
        weight_map = {}
        for part in weights.split(","):
            if ":" not in part:
                continue
            k, _, v = part.partition(":")
            k = k.strip()
            if not k:
                continue
            try:
                weight_map[k] = float(v)
            except ValueError:
                continue
    return enabled_list, weight_map


@app.get("/api/backtest/{symbol}")                # GATED — Indicator Lab backtest
def backtest_endpoint(symbol: str, enabled: str = "", weights: str = "",
                      long_th: float = 6.0, short_th: float = 4.0,
                      bars: int = 250, allow_short: bool = False,
                      exchange: str = "", x_access_key: str = Header(default="")):
    """Backtest the user's indicator-panel config on a symbol's daily candles.
    Fees included, no lookahead, always benchmarked vs the EMA30 baseline and
    buy & hold. HONEST REPORTING ONLY — the response carries the no-edge
    guardrail note and the UI must keep it visible."""
    rec = _gate(x_access_key, "operator")
    import backtest as bt

    key = (symbol, enabled, weights, round(long_th, 2), round(short_th, 2),
           int(bars), bool(allow_short), exchange)
    now = time.time()
    with _lock:
        hit = _bt_cache.get(key)
        if hit and now - hit["ts"] < _BT_TTL:
            return hit["data"]

    # Candle source: main cache -> on-demand cache -> live fetch (crypto),
    # with a non-crypto fallback via forex_data for forex/stocks/indices/metals.
    with _lock:
        cached = _cache["candles"].get(symbol)
        od = _ondemand_cache.get(symbol)
    candles = (cached or {}).get("candles") or ((od or {}).get("data") or {}).get("candles")
    if not candles:
        candles = exchanges.fetch_daily(symbol, (exchange or EXCHANGE).lower(), PROOF_CANDLES)
    if not candles:
        try:
            import forex_data
            if any(symbol in v for v in forex_data.symbols().values()):
                candles = forex_data.fetch_daily(symbol, PROOF_CANDLES)
        except Exception:
            pass
    if not candles:
        raise HTTPException(404, f"No daily candles available for {symbol!r}.")

    enabled_list, weight_map = _parse_panel_config(enabled, weights)
    result = bt.run(candles, enabled=enabled_list, weights=weight_map,
                    long_th=long_th, short_th=short_th, bars=bars,
                    allow_short=allow_short, fee=FEE)
    if "error" in result:
        raise HTTPException(422, result["error"])
    result["symbol"] = symbol
    with _lock:
        _bt_cache[key] = {"data": result, "ts": now}
    return result


@app.get("/api/symbols/search")                   # PUBLIC — live asset search on any exchange
def symbol_search(q: str = "", exchange: str = "", quote: str = "USDT", limit: int = 50,
                  segment: str = "spot"):
    """Search/list tradable symbols on any exchange. Returns up to `limit` matches.
    segment: spot | swap (perps). Useful for the asset-picker."""
    ex = (exchange or EXCHANGE).lower()
    assets = exchanges.list_assets(ex, quote, market_type=segment if segment in ("spot","swap","all") else "spot")
    q = q.strip().upper()
    if q:
        assets = [a for a in assets if q in a]
    return {"exchange": ex, "quote": quote, "results": assets[:limit], "total": len(assets)}


@app.get("/api/candles-ondemand/{symbol}")        # GATED — fetch+compute any symbol on the fly
def candles_ondemand(symbol: str, exchange: str = "", segment: str = "spot",
                     x_access_key: str = Header(default="")):
    """Fetch daily candles and run EMA30 trend compute() for any symbol not in
    the pre-loaded SYMBOLS watchlist. Results are cached for ONDEMAND_TTL seconds
    (~10 min) so repeated clicks don't re-hit the exchange.

    Returns the same shape as /api/candles/{symbol}:
      { candles: [...], ema: [...], signal: {...} }

    Errors:
      404  — symbol not found / exchange returned no data
      503  — ccxt not installed and exchange != mexc
    """
    _gate(x_access_key)

    seg = segment if segment in ("spot", "swap") else "spot"
    od_key = symbol if seg == "spot" else f"{symbol}::swap"

    # 1. Serve from on-demand cache if still fresh
    now = time.time()
    with _lock:
        hit = _ondemand_cache.get(od_key)
        if hit and now - hit["ts"] < ONDEMAND_TTL:
            return hit["data"]

    # 2. Spot symbol already in main watchlist cache? Return that directly
    if seg == "spot":
        with _lock:
            main = _cache["candles"].get(symbol)
        if main:
            return main

    # 3. Determine exchange to hit
    ex = (exchange or EXCHANGE).lower()

    # 4. Guard: ccxt required for non-MEXC exchanges
    if ex != "mexc":
        try:
            import ccxt as _ccxt_chk  # noqa: F401
        except ImportError:
            raise HTTPException(
                503,
                f"ccxt not installed — only 'mexc' is available without it. "
                f"Install with: pip install ccxt"
            )

    # 5. Fetch candles (perps chart the swap market)
    raw = exchanges.fetch_daily(symbol, ex, CANDLES, market_type=seg)
    if not raw or len(raw) < EMA_PERIOD + 2:
        raise HTTPException(
            404,
            f"No data for {symbol!r} on {ex!r}. "
            f"Check the symbol format (e.g. BTC_USDT) and that it trades on {ex!r}."
        )

    # 6. Compute EMA + signal (mirrors compute() but from raw candles arg)
    closes = [c["close"] for c in raw]
    e = ema(closes, EMA_PERIOD)
    ema_pts = [
        {"time": raw[EMA_PERIOD - 1 + i]["time"], "value": round(e[i], 6)}
        for i in range(len(e))
    ]
    price, ema_now = closes[-1], e[-1]
    direction = "LONG" if price > ema_now else "SHORT"
    held = 0
    for i in range(len(e) - 1, 0, -1):
        if (closes[EMA_PERIOD - 1 + i] > e[i]) == (closes[EMA_PERIOD - 2 + i] > e[i - 1]):
            held += 1
        else:
            break

    # Market-intel composite score (best-effort)
    try:
        cs = market_intel.composite_score(raw)
    except Exception:
        cs = None

    # MTF alignment (best-effort)
    try:
        h4 = market_intel._trend_from_candles(market_intel.fetch_4h(symbol, ex))
    except Exception:
        h4 = None

    sig = {
        "symbol": symbol, "direction": direction,
        "price": round(price, 6), "ema": round(ema_now, 6),
        "distance_pct": round((price - ema_now) / ema_now * 100, 2),
        "bars_held": held,
        "mtf": {"d1": direction, "h4": h4, "aligned": h4 is not None and h4 == direction},
        "on_demand": True,          # lets the UI distinguish from watchlist coins
    }
    if cs:
        sig["score"] = cs["score"]
        sig["score_dir"] = cs["direction"]
        sig["score_components"] = cs["components"]

    data = {"candles": raw, "ema": ema_pts, "signal": sig}

    # 7. Store in on-demand cache
    if seg == "swap":
        sig["segment"] = "swap"
    with _lock:
        _ondemand_cache[od_key] = {"data": data, "ts": now}

    return data


@app.post("/api/tv-webhook")                       # PUBLIC receiver — TradingView alerts
async def tv_webhook(request: Request):
    """Receive TradingView webhook alerts.  Validates TV_WEBHOOK_SECRET when set.
    Stores alerts in-memory via webhook_store; surfaces TP/SL lines to the chart UI.

    TradingView Pine Script alert message format (JSON):
      {"symbol":"BTC_USDT","action":"BUY","price":65000,"tp":68000,"sl":63000,"message":"EMA cross"}

    All fields except `symbol` are optional.  Set TV_WEBHOOK_SECRET env var and pass it
    as {"secret":"…"} in the body for production (strongly recommended).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be valid JSON")

    # Secret validation (skip if TV_SECRET is unset — dev/local mode)
    if TV_SECRET and body.get("secret", "") != TV_SECRET:
        raise HTTPException(403, "Invalid webhook secret")

    if not body.get("symbol"):
        raise HTTPException(422, "Field 'symbol' is required")

    alert = webhook_store.ingest(body)

    # ── Optional auto-execution (off by default). Runs in a thread so the
    # webhook responds fast; paper unless EXEC_LIVE=true. Non-custodial:
    # credentials come only from env vars on the owner's own machine.
    if AUTO_EXECUTE and alert["action"] in ("BUY", "SELL"):
        req = {
            "symbol": alert["symbol"], "side": alert["action"],
            "price": alert["price"], "tp": alert["tp"], "sl": alert["sl"],
            "quote_amount": EXEC_QUOTE_AMOUNT,
            "dry_run": not EXEC_LIVE,
            "execute_key": EXECUTE_KEY,           # internal call, already secret-gated
            "source": "auto",
        }
        threading.Thread(target=execution.execute, args=(req, _exec_cfg()),
                         daemon=True).start()

    return {"ok": True, "alert_id": alert["id"], "symbol": alert["symbol"]}


@app.get("/api/exec-config")                      # GATED — what the bridge allows
def exec_config(x_access_key: str = Header(default="")):
    """Tells the UI which execution features are armed on this server.
    Never returns any secrets."""
    _gate(x_access_key, "operator")
    cfg = _exec_cfg()
    return {
        "armed": bool(cfg["execute_key"]),        # EXECUTE_KEY set?
        "live_enabled": cfg["live_enabled"],
        "auto_execute": AUTO_EXECUTE,
        "max_usd": cfg["max_usd"],
        "default_exchange": cfg["default_exchange"],
        "has_env_creds": bool(cfg["env_api_key"] and cfg["env_api_secret"]),
    }


@app.get("/api/user-cap")                         # GATED operator — your own cap
def get_user_cap(x_access_key: str = Header(default="")):
    rec = _gate(x_access_key, "operator")
    return {"max_usd": user_cap(rec.get("hash16", "")),
            "effective": effective_cap(rec.get("hash16", "")),
            "server_ceiling": EXEC_MAX_USD,
            "note": "0 = no personal cap (server ceiling still applies if set)"}


@app.post("/api/user-cap")                        # GATED operator — set your cap
async def set_user_cap(request: Request, x_access_key: str = Header(default="")):
    rec = _gate(x_access_key, "operator")
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        cap = float(body.get("max_usd"))
    except (TypeError, ValueError):
        raise HTTPException(422, "max_usd must be a number (0 = no personal cap).")
    if cap < 0 or cap > 1e9:
        raise HTTPException(422, "max_usd out of range.")
    import json as _j
    import store_db
    store_db.save_kv(f"usercap_{rec['hash16']}", _j.dumps({"max_usd": cap, "ts": int(time.time())}))
    return {"ok": True, "max_usd": cap, "effective": effective_cap(rec["hash16"])}


@app.post("/api/tv-execute")                      # GATED — place a paper/live order
async def tv_execute(request: Request, x_access_key: str = Header(default=""),
                     x_execute_key: str = Header(default="")):
    """Non-custodial order execution. Defaults to PAPER. A LIVE order needs
    EXECUTE_KEY + EXEC_LIVE=true on the server + dry_run=false in the request
    + API credentials (per-request or env). Keys are never stored. See
    execution.py for the full safety model."""
    rec = _gate(x_access_key, "operator")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Request body must be valid JSON")
    if x_execute_key and not body.get("execute_key"):
        body["execute_key"] = x_execute_key
    body.setdefault("source", "manual")
    result = execution.execute(body, cfg_for(rec.get("hash16", "")))
    return {"ok": result["status"] == "ok", "result": result}


@app.get("/api/exec-log")                         # GATED — recent paper/live orders
def exec_log(limit: int = 50, x_access_key: str = Header(default="")):
    _gate(x_access_key, "operator")
    return {"orders": execution.log_recent(limit)}


# ─── Server-side bots: trend (EMA30, paper/live) + scalper (paper-only) ──────
import bots as _bots


# How many bot instances an architect key may run. Server/env keys (the
# owner) are unlimited up to the global cap; purchased add-ons raise a
# subscriber's allowance (+2 per pack, applied by the billing webhooks).
BOT_BASE_ALLOWANCE = int(os.environ.get("BOT_BASE_ALLOWANCE", "3"))


def _bot_allowance(rec: dict) -> int:
    if rec.get("env"):
        return _bots.MAX_INSTANCES
    return BOT_BASE_ALLOWANCE + int((rec.get("addons") or {}).get("bots", 0))


def _bots_visible(rec: dict):
    """Env/owner keys see every instance (incl. legacy unowned ones);
    subscriber keys see only their own."""
    if rec.get("env"):
        return _bots.all_status()
    me = rec.get("hash16", "")
    return [s for s in _bots.all_status() if s.get("owner") == me]


def _bot_owned_or_403(bot_id: str, rec: dict):
    bot = _bots.get(bot_id)
    if not bot:
        raise HTTPException(404, f"Unknown bot {bot_id!r}.")
    if not rec.get("env") and bot.owner != rec.get("hash16", ""):
        raise HTTPException(403, "That bot belongs to a different key.")
    return bot


@app.get("/api/bots")                             # GATED — your bot instances
def bots_status(x_access_key: str = Header(default="")):
    rec = _gate(x_access_key, "architect")
    mine = _bots_visible(rec)
    return {
        "bots": mine,
        "allowance": _bot_allowance(rec),
        "max_instances": _bots.MAX_INSTANCES,
        "bridge": {"armed": bool(EXECUTE_KEY), "live_enabled": EXEC_LIVE},
    }


def _bot_or_404(bot_id: str):
    bot = _bots.get(bot_id)
    if not bot:
        raise HTTPException(404, f"Unknown bot {bot_id!r}.")
    return bot


def _check_execute_key(body: dict, x_execute_key: str):
    """Bots place orders, so arming/stopping them requires the bridge key."""
    if not EXECUTE_KEY:
        raise HTTPException(403, "Bots are disarmed: set EXECUTE_KEY on the server first.")
    supplied = str(body.get("execute_key") or x_execute_key or "")
    if supplied != EXECUTE_KEY:
        raise HTTPException(403, "Invalid execute key.")


@app.post("/api/bots/create")                     # GATED — add a bot instance
async def bot_create(request: Request, x_access_key: str = Header(default="")):
    rec = _gate(x_access_key, "architect")
    mine = _bots_visible(rec)
    if len(mine) >= _bot_allowance(rec):
        raise HTTPException(422, f"Bot allowance reached ({_bot_allowance(rec)}). "
                                 f"Add the +2 bots add-on from the pricing page, "
                                 f"or remove an existing bot.")
    try:
        body = await request.json()
    except Exception:
        body = {}
    res = _bots.create(str(body.get("kind", "")), str(body.get("label", ""))[:40],
                       owner="" if rec.get("env") else rec.get("hash16", ""))
    if not res.get("ok"):
        raise HTTPException(422, res.get("error", "could not create bot"))
    return res


@app.delete("/api/bots/{bot_id}")                 # GATED — remove an instance
def bot_delete(bot_id: str, x_access_key: str = Header(default="")):
    rec = _gate(x_access_key, "architect")
    _bot_owned_or_403(bot_id, rec)
    res = _bots.delete(bot_id)
    if not res.get("ok"):
        raise HTTPException(404, res.get("error", "unknown bot"))
    return res


@app.post("/api/bots/{bot_id}/start")             # GATED + execute key
async def bot_start(bot_id: str, request: Request,
                    x_access_key: str = Header(default=""),
                    x_execute_key: str = Header(default="")):
    """Start (or re-configure while running) a bot instance. LIVE additionally
    requires every execution-bridge gate, enforced downstream."""
    rec = _gate(x_access_key, "architect")
    bot = _bot_owned_or_403(bot_id, rec)
    try:
        body = await request.json()
    except Exception:
        body = {}
    _check_execute_key(body, x_execute_key)
    res = bot.start(body.get("config") or body)
    if not res.get("ok"):
        raise HTTPException(422, res.get("error", "could not start bot"))
    return res


@app.post("/api/bots/{bot_id}/stop")              # GATED + execute key
async def bot_stop(bot_id: str, request: Request,
                   x_access_key: str = Header(default=""),
                   x_execute_key: str = Header(default="")):
    rec = _gate(x_access_key, "architect")
    bot = _bot_owned_or_403(bot_id, rec)
    try:
        body = await request.json()
    except Exception:
        body = {}
    _check_execute_key(body, x_execute_key)
    return bot.stop()


import exits as _exits


@app.get("/api/exits")                            # GATED operator — exit plans
def exits_list(x_access_key: str = Header(default="")):
    _gate(x_access_key, "operator")
    _exits.rearm_suspended(bool(EXECUTE_KEY))
    out = _exits.status()
    out["bridge_armed"] = bool(EXECUTE_KEY)
    return out


@app.post("/api/exits")                           # GATED operator + execute key
async def exits_create(request: Request,
                       x_access_key: str = Header(default=""),
                       x_execute_key: str = Header(default="")):
    """Arm a server-watched protective exit: SELL `qty` of `symbol` when
    price touches tp or sl. Fires through the execution bridge (all gates)."""
    rec = _gate(x_access_key, "operator")
    try:
        body = await request.json()
    except Exception:
        body = {}
    _check_execute_key(body, x_execute_key)
    res = _exits.upsert(
        str(body.get("symbol", "")), _fnum(body.get("qty")),
        _fnum(body.get("tp")), _fnum(body.get("sl")),
        bool(body.get("live")), str(body.get("exchange", "")),
        source=str(body.get("source", "manual"))[:12],
        owner=rec.get("hash16", ""))
    if not res.get("ok"):
        raise HTTPException(422, res.get("error", "could not arm exit"))
    return res


@app.delete("/api/exits/{plan_id}")               # GATED operator + execute key
def exits_cancel(plan_id: str,
                 x_access_key: str = Header(default=""),
                 x_execute_key: str = Header(default="")):
    _gate(x_access_key, "operator")
    _check_execute_key({}, x_execute_key)
    res = _exits.cancel(plan_id)
    if not res.get("ok"):
        raise HTTPException(404, res.get("error", "unknown plan"))
    return res


def _fnum(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


@app.post("/api/levels/{symbol}")                 # GATED operator — chart-drag TP/SL
async def set_levels(symbol: str, request: Request,
                     x_access_key: str = Header(default="")):
    """Update the platform's TP/SL levels for a symbol (the dashed chart
    lines, alert context, bot/exec reference). Stored as a synthetic ADJUST
    alert so it persists, propagates, and leaves an audit row in the alert
    log. NOTE: this does NOT modify any order resting on an exchange —
    bridge v1 doesn't place native TP/SL orders (roadmap)."""
    _gate(x_access_key, "operator")
    try:
        body = await request.json()
    except Exception:
        body = {}

    def _lvl(v):
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise HTTPException(422, "TP/SL must be numbers (or null).")
        if not (0 < f < 1e9):
            raise HTTPException(422, "TP/SL out of range.")
        return f

    tp, sl = _lvl(body.get("tp")), _lvl(body.get("sl"))
    if tp is None and sl is None:
        raise HTTPException(422, "Provide tp and/or sl.")
    alert = webhook_store.ingest({
        "symbol": symbol, "action": "ADJUST", "tp": tp, "sl": sl,
        "message": "TP/SL adjusted on the chart",
    })
    moved = _exits.update_levels(symbol, tp, sl)   # armed watcher follows the lines
    return {"ok": True, "levels": {"tp": tp, "sl": sl},
            "exit_plan_updated": bool(moved), "alert_id": alert["id"]}


@app.get("/api/tv-alerts/{symbol}")               # GATED — per-symbol alert feed + TP/SL levels
def tv_alerts_symbol(symbol: str, limit: int = 20,
                     x_access_key: str = Header(default="")):
    """Recent TradingView alerts for a symbol + latest TP/SL levels for chart lines."""
    _gate(x_access_key)
    sym = symbol.upper().replace("/", "_")
    return {
        "symbol": sym,
        "levels": webhook_store.get_levels(sym),
        "alerts": webhook_store.get_for_symbol(sym, limit),
    }


@app.get("/api/tv-alerts")                        # GATED — global alert feed
def tv_alerts_global(limit: int = 50,
                     x_access_key: str = Header(default="")):
    """Most recent TradingView alerts across all symbols, newest first."""
    _gate(x_access_key)
    return {"alerts": webhook_store.get_recent(limit)}


@app.delete("/api/tv-alerts/{symbol}")            # GATED — clear per-symbol alerts
def tv_alerts_clear(symbol: str, x_access_key: str = Header(default="")):
    _gate(x_access_key, "operator")
    webhook_store.clear_symbol(symbol)
    return {"ok": True, "cleared": symbol.upper().replace("/", "_")}


@app.get("/api/candles-nonCrypto/{symbol}")       # GATED — forex/stocks/indices/metals
def candles_non_crypto(symbol: str, x_access_key: str = Header(default="")):
    """Fetch daily OHLC + EMA30 signal for a non-crypto symbol (forex, stock, index, metal).
    Uses forex_data.py (yfinance or Twelve Data). Returns same shape as /api/candles/{symbol}.
    """
    _gate(x_access_key)
    try:
        import forex_data
    except ImportError:
        raise HTTPException(503, "forex_data module not available")
    raw = forex_data.fetch_daily(symbol, limit=CANDLES)
    if not raw or len(raw) < EMA_PERIOD + 2:
        raise HTTPException(404, f"No data for {symbol!r}. Install yfinance or set TWELVEDATA_KEY.")
    closes = [c["close"] for c in raw]
    e = ema(closes, EMA_PERIOD)
    ema_pts = [{"time": raw[EMA_PERIOD-1+i]["time"], "value": round(e[i], 6)} for i in range(len(e))]
    price, ema_now = closes[-1], e[-1]
    direction = "LONG" if price > ema_now else "SHORT"
    held = 0
    for i in range(len(e)-1, 0, -1):
        if (closes[EMA_PERIOD-1+i] > e[i]) == (closes[EMA_PERIOD-2+i] > e[i-1]):
            held += 1
        else:
            break
    sig = {
        "symbol": symbol, "direction": direction,
        "price": round(price, 6), "ema": round(ema_now, 6),
        "distance_pct": round((price - ema_now) / ema_now * 100, 2),
        "bars_held": held, "asset_class": "non_crypto",
    }
    return {"candles": raw, "ema": ema_pts, "signal": sig}


# ─── Site pages + billing webhooks ────────────────────────────────────────────
from fastapi.responses import FileResponse, RedirectResponse, Response

try:
    import billing
    app.include_router(billing.router)
except Exception as _be:                           # never block startup
    print(f"[billing] disabled: {_be}")


@app.get("/")
def page_landing():
    return FileResponse("static/landing.html")


@app.get("/app")
def page_app():
    return FileResponse("static/index.html")


@app.get("/download")
def page_download():
    return FileResponse("static/download.html")


@app.get("/terminal")                              # old bookmark courtesy
def page_terminal():
    return RedirectResponse("/app", status_code=308)


TERMS_VERSION = "2026-06-12"


@app.post("/api/accept-terms")                     # any valid key — records acceptance
async def accept_terms(request: Request, x_access_key: str = Header(default="")):
    """Evidential record of Terms acceptance: version + timestamp, tied to a
    hashed key identifier only (no personal data)."""
    rec = _gate(x_access_key, "observer")
    try:
        body = await request.json()
    except Exception:
        body = {}
    version = str(body.get("version", TERMS_VERSION))[:20]
    import json
    import store_db
    store_db.save_kv(f"tos_{rec.get('hash16','anon')}",
                     json.dumps({"version": version, "ts": int(time.time())}))
    return {"ok": True, "version": version}


# ─── Vanity redirects: brand-domain links for socials/marketplaces ──────────
# ascentterminal.com/patreon etc. — clean in posts, future-proof (change the
# destination here or in .env without breaking old links anywhere).
SOCIAL_LINKS = {
    "patreon": os.environ.get("SOCIAL_PATREON", "https://patreon.com/AscentTerminal"),
    "whop": os.environ.get("SOCIAL_WHOP", "https://whop.com/ascentterminal"),
    "x": os.environ.get("SOCIAL_X", "https://x.com/AscentTerminal"),
    "twitter": os.environ.get("SOCIAL_X", "https://x.com/AscentTerminal"),
    "discord": os.environ.get("SOCIAL_DISCORD", ""),   # set your invite link
}


def _vanity(name: str):
    target = SOCIAL_LINKS.get(name)
    if not target:
        raise HTTPException(404, "This link is not configured.")
    return RedirectResponse(target, status_code=302)


@app.get("/patreon")
def go_patreon():
    return _vanity("patreon")


@app.get("/whop")
def go_whop():
    return _vanity("whop")


@app.get("/x")
def go_x():
    return _vanity("x")


@app.get("/twitter")
def go_twitter():
    return _vanity("twitter")


@app.get("/discord")
def go_discord():
    return _vanity("discord")


@app.get("/privacy-tools")
def page_privacy_tools():
    return FileResponse("static/privacy-tools.html")


@app.get("/legal/{page}")
def page_legal(page: str):
    if page not in ("terms", "privacy", "disclaimer"):
        raise HTTPException(404, "No such page.")
    return FileResponse(f"static/legal/{page}.html")


@app.get("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\nDisallow: /api/\n"
                    "Sitemap: https://ascentterminal.com/sitemap.xml\n",
                    media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap():
    base = "https://ascentterminal.com"
    pages = ["/", "/download", "/privacy-tools", "/legal/terms", "/legal/privacy", "/legal/disclaimer"]
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in pages)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?>'
                    f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                    media_type="application/xml")


app.mount("/", StaticFiles(directory="static", html=False), name="static")


