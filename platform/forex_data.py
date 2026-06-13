"""
forex_data.py — multi-asset (forex / indices / stocks) daily data for Ascent
Terminal. Crypto stays on exchanges.py (ccxt); THIS covers everything ccxt
can't, so the terminal becomes truly multi-asset.

Providers (auto-selected):
  - yfinance  — free, no API key, covers forex/indices/stocks/ETFs/crypto.
                `pip install yfinance`
  - Twelve Data — robust upgrade if you set TWELVEDATA_KEY (free tier ~800/day).

Returns the SAME shape as exchanges.fetch_daily:  [{time,open,high,low,close}]
newest last, time in epoch seconds — so the rest of the app doesn't care where
data comes from.
"""

import os
import time
import requests

TD_KEY = os.environ.get("TWELVEDATA_KEY", "").strip()

# Curated universe (extend freely). Internal symbol -> display.
FOREX = [
    # majors
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD",
    # EUR crosses
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD", "EUR_CAD", "EUR_NZD",
    # GBP crosses
    "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_CAD", "GBP_NZD",
    # JPY / other crosses
    "AUD_JPY", "CAD_JPY", "CHF_JPY", "NZD_JPY", "AUD_NZD", "AUD_CAD", "AUD_CHF",
    "CAD_CHF", "NZD_CAD", "NZD_CHF",
    # popular exotics
    "USD_SEK", "USD_NOK", "USD_MXN", "USD_ZAR", "USD_TRY", "USD_SGD", "USD_HKD", "USD_CNH",
]
INDICES = ["SPX500", "NAS100", "US30", "RUS2000", "VIX",
           "UK100", "GER40", "FRA40", "EU50", "ESP35", "ITA40", "SWI20",
           "JPN225", "HK50", "CHINA50", "AUS200", "CAN60", "IND50"]
METALS = ["XAU_USD", "XAG_USD", "XPT_USD", "XPD_USD", "COPPER",
          "WTI_OIL", "BRENT_OIL", "NAT_GAS"]      # metals + key energy commodities
STOCKS = [
    # mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL",
    "CRM", "ADBE", "AMD", "INTC", "QCOM", "TXN", "MU", "PLTR", "SMCI",
    "NFLX", "DIS", "UBER", "SHOP", "PYPL", "COIN", "MSTR", "HOOD",
    # financials
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BRK-B", "BLK",
    # healthcare
    "LLY", "UNH", "JNJ", "PFE", "MRK", "ABBV", "TMO",
    # consumer / industrial / energy
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "KO", "PEP", "PG",
    "CAT", "BA", "GE", "LMT", "XOM", "CVX", "OXY",
    # popular ETFs
    "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "ARKK",
]

# internal -> yfinance ticker
_YF = {
    # forex — yfinance uses PAIR=X (USD-base pairs drop the USD)
    "EUR_USD": "EURUSD=X", "GBP_USD": "GBPUSD=X", "USD_JPY": "JPY=X",
    "AUD_USD": "AUDUSD=X", "USD_CAD": "CAD=X", "USD_CHF": "CHF=X",
    "NZD_USD": "NZDUSD=X",
    "EUR_GBP": "EURGBP=X", "EUR_JPY": "EURJPY=X", "EUR_CHF": "EURCHF=X",
    "EUR_AUD": "EURAUD=X", "EUR_CAD": "EURCAD=X", "EUR_NZD": "EURNZD=X",
    "GBP_JPY": "GBPJPY=X", "GBP_CHF": "GBPCHF=X", "GBP_AUD": "GBPAUD=X",
    "GBP_CAD": "GBPCAD=X", "GBP_NZD": "GBPNZD=X",
    "AUD_JPY": "AUDJPY=X", "CAD_JPY": "CADJPY=X", "CHF_JPY": "CHFJPY=X",
    "NZD_JPY": "NZDJPY=X", "AUD_NZD": "AUDNZD=X", "AUD_CAD": "AUDCAD=X",
    "AUD_CHF": "AUDCHF=X", "CAD_CHF": "CADCHF=X", "NZD_CAD": "NZDCAD=X",
    "NZD_CHF": "NZDCHF=X",
    "USD_SEK": "SEK=X", "USD_NOK": "NOK=X", "USD_MXN": "MXN=X",
    "USD_ZAR": "ZAR=X", "USD_TRY": "TRY=X", "USD_SGD": "SGD=X",
    "USD_HKD": "HKD=X", "USD_CNH": "CNY=X",
    # indices
    "SPX500": "^GSPC", "NAS100": "^IXIC", "US30": "^DJI", "RUS2000": "^RUT",
    "VIX": "^VIX", "UK100": "^FTSE", "GER40": "^GDAXI", "FRA40": "^FCHI",
    "EU50": "^STOXX50E", "ESP35": "^IBEX", "ITA40": "FTSEMIB.MI",
    "SWI20": "^SSMI", "JPN225": "^N225", "HK50": "^HSI", "CHINA50": "000001.SS",
    "AUS200": "^AXJO", "CAN60": "^GSPTSE", "IND50": "^NSEI",
    # metals & energy (futures)
    "XAU_USD": "GC=F", "XAG_USD": "SI=F", "XPT_USD": "PL=F", "XPD_USD": "PA=F",
    "COPPER": "HG=F", "WTI_OIL": "CL=F", "BRENT_OIL": "BZ=F", "NAT_GAS": "NG=F",
}
# internal -> Twelve Data symbol
_TD = {s: s.replace("_", "/") for s in FOREX + ["XAU_USD", "XAG_USD", "XPT_USD", "XPD_USD"]}
_TD.update({"SPX500": "SPX", "NAS100": "IXIC", "US30": "DJI"})


def symbols() -> dict:
    """Available non-crypto markets grouped by class (for the asset picker)."""
    return {"forex": FOREX, "indices": INDICES, "metals": METALS, "stocks": STOCKS}


_SUMMARY_CACHE = {}                               # mtype -> {"rows":.., "ts":..}
_SUMMARY_TTL = 600                                # 10 min


def bulk_summary(mtype: str) -> list:
    """Last price + 1-day % change + volume for every symbol in an asset class,
    via ONE multi-ticker yfinance download. Powers the Top Movers / Most Traded
    views for non-crypto tabs. Cached ~10 min. [] when yfinance is missing.

    Returns [{"symbol": .., "price": .., "change_pct": .., "qvol": ..}]
    (qvol is share/contract volume — None for forex where yfinance has no volume).
    """
    universe = symbols().get(mtype)
    if not universe:
        return []
    now = time.time()
    hit = _SUMMARY_CACHE.get(mtype)
    if hit and now - hit["ts"] < _SUMMARY_TTL:
        return hit["rows"]
    try:
        import yfinance as yf
    except ImportError:
        return []
    tickers = {s: _YF.get(s, s) for s in universe}
    rows = []
    try:
        df = yf.download(list(tickers.values()), period="5d", interval="1d",
                         progress=False, auto_adjust=False, group_by="ticker",
                         threads=True)
        if df is None or df.empty:
            return hit["rows"] if hit else []
        multi = hasattr(df.columns, "levels")     # MultiIndex when >1 ticker
        for internal, yft in tickers.items():
            try:
                sub = df[yft] if multi else df
                closes = sub["Close"].dropna()
                if closes.empty:
                    continue
                last = float(closes.iloc[-1])
                prev = float(closes.iloc[-2]) if len(closes) > 1 else None
                chg = round((last - prev) / prev * 100, 2) if prev else None
                vol = None
                if "Volume" in sub:
                    vols = sub["Volume"].dropna()
                    if not vols.empty and float(vols.iloc[-1]) > 0:
                        vol = float(vols.iloc[-1])
                rows.append({"symbol": internal, "price": round(last, 6),
                             "change_pct": chg, "qvol": vol})
            except Exception:
                continue
    except Exception:
        return hit["rows"] if hit else []
    if rows:
        _SUMMARY_CACHE[mtype] = {"rows": rows, "ts": now}
    return rows


def fetch_daily(symbol: str, limit: int = 400) -> list:
    if TD_KEY:
        rows = _twelvedata(symbol, limit)
        if rows:
            return rows
    return _yfinance(symbol, limit)


def _yfinance(symbol, limit):
    try:
        import yfinance as yf
    except ImportError:
        return []
    ticker = _YF.get(symbol, symbol)            # passthrough for raw tickers (e.g. "AAPL")
    try:
        period = "2y" if limit <= 500 else "5y"
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            return []
        out = []
        for ts, row in df.tail(limit).iterrows():
            out.append({"time": int(ts.timestamp()),
                        "open": float(row["Open"]), "high": float(row["High"]),
                        "low": float(row["Low"]), "close": float(row["Close"])})
        return out
    except Exception:
        return []


def _twelvedata(symbol, limit):
    sym = _TD.get(symbol, symbol.replace("_", "/"))
    try:
        r = requests.get("https://api.twelvedata.com/time_series", timeout=15, params={
            "symbol": sym, "interval": "1day", "outputsize": min(limit, 5000),
            "apikey": TD_KEY, "order": "ASC"})
        vals = r.json().get("values", [])
        out = []
        for v in vals:
            t = int(time.mktime(time.strptime(v["datetime"][:10], "%Y-%m-%d")))
            out.append({"time": t, "open": float(v["open"]), "high": float(v["high"]),
                        "low": float(v["low"]), "close": float(v["close"])})
        return out
    except Exception:
        return []
