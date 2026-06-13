#!/usr/bin/env python3
"""
MEXC Futures Daily Trend Bot
Strategy: EMA30 on Day1 candles — long above, short below, hold until EMA flips.
Requires: pip install PyQt5 pyqtgraph websocket-client anthropic requests
"""

# ─── STDLIB ──────────────────────────────────────────────────────────────────
import sys, os, json, time, hmac, hashlib, threading, queue, logging
import ssl, math, traceback
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import deque

# ─── THIRD PARTY ─────────────────────────────────────────────────────────────
try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QTabWidget, QLabel, QPushButton, QLineEdit,
        QComboBox, QCheckBox, QGroupBox, QScrollArea, QFrame,
        QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
        QTextEdit, QDoubleSpinBox, QSizePolicy,
        QMessageBox, QAbstractItemView
    )
    from PyQt5.QtCore import (
        Qt, QTimer, QThread, pyqtSignal, QObject, QRunnable,
        QThreadPool, pyqtSlot
    )
    from PyQt5.QtGui import (
        QFont, QColor, QPalette, QTextCursor
    )
    import pyqtgraph as pg
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False
    print("ERROR: PyQt5 / pyqtgraph not found.\n"
          "Run: pip install PyQt5 pyqtgraph websocket-client anthropic requests")
    sys.exit(1)

try:
    import websocket as ws_lib
    HAS_WS = True
except ImportError:
    HAS_WS = False

try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

APP_NAME = "MEXC Trend Bot"
APP_VER  = "2.0.0"
MEXC_WS  = "wss://contract.mexc.com/edge"
MEXC_REST = "https://contract.mexc.com"

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")

TOP_ASSETS = [
    "BTC_USDT","ETH_USDT","SOL_USDT","BNB_USDT","XRP_USDT",
    "DOGE_USDT","ADA_USDT","AVAX_USDT","LINK_USDT","DOT_USDT",
    "LTC_USDT","ATOM_USDT","UNI_USDT","NEAR_USDT","APT_USDT"
]

ASSET_MAX_LEV = {
    "BTC_USDT":200,"ETH_USDT":200,"SOL_USDT":100,"BNB_USDT":100,
    "XRP_USDT":100,"DOGE_USDT":75,"ADA_USDT":75,"AVAX_USDT":75,
    "LINK_USDT":75,"DOT_USDT":75,"LTC_USDT":75,"ATOM_USDT":50,
    "UNI_USDT":50,"NEAR_USDT":50,"APT_USDT":50
}

LEVERAGE_OPTIONS = [1,2,3,4,5,6,7,8,9,10,15,20,25,30,40,50,
                    60,75,100,150,200]
MARGIN_OPTIONS   = [5,10,15,20,25,30,50,75,100,150,200,300,500,750,1000]

# EMA30 daily — the one filter
EMA_PERIOD    = 30
SCAN_INTERVAL_MS = 60_000   # 1 min (daily bar only changes once a day; no need to hammer)

MAKER_FEE     = 0.0004
TAKER_FEE     = 0.0006
ROUND_TRIP_FEE = MAKER_FEE + TAKER_FEE

PAPER_START_BALANCE = 1000.0
MAX_OPEN_POSITIONS  = 5

# ─── COLOUR PALETTE ──────────────────────────────────────────────────────────

DARK_BG     = "#0e1117"
DARK_PANEL  = "#151926"
DARK_CARD   = "#1c2130"
DARK_BORDER = "#323a4d"
GREEN_HI    = "#22e57e"
RED_HI      = "#ff4d68"
AMBER_HI    = "#ffc83d"
BLUE_HI     = "#52ccff"
TEXT_PRI    = "#eef1fa"
TEXT_SEC    = "#c0c8da"
TEXT_DIM    = "#94a0b8"

STYLE_SHEET = f"""
QMainWindow, QWidget {{ background:{DARK_BG}; color:{TEXT_PRI};
    font-family:'Consolas','Courier New',monospace; font-size:12px; }}
QTabWidget::pane {{ border:1px solid {DARK_BORDER}; background:{DARK_PANEL}; }}
QTabBar::tab {{ background:{DARK_CARD}; color:{TEXT_SEC}; padding:6px 14px;
    border:1px solid {DARK_BORDER}; margin-right:2px; }}
QTabBar::tab:selected {{ background:{DARK_PANEL}; color:{TEXT_PRI};
    border-bottom:2px solid {BLUE_HI}; }}
QTabBar::tab:hover {{ color:{TEXT_PRI}; }}
QGroupBox {{ border:1px solid {DARK_BORDER}; border-radius:4px; margin-top:8px;
    padding-top:8px; color:{TEXT_SEC}; font-size:11px; }}
QGroupBox::title {{ subcontrol-origin:margin; left:8px; color:{BLUE_HI}; }}
QPushButton {{ background:{DARK_CARD}; color:{TEXT_PRI}; border:1px solid {DARK_BORDER};
    border-radius:3px; padding:4px 10px; }}
QPushButton:hover {{ background:#1e2435; border-color:{BLUE_HI}; }}
QPushButton:pressed {{ background:#252b3b; }}
QPushButton:checked {{ background:#13344a; border:1px solid {BLUE_HI};
    color:{BLUE_HI}; font-weight:bold; }}
QPushButton:disabled {{ color:{TEXT_DIM}; }}
QPushButton#btnStart {{ background:#0a3d1f; border-color:{GREEN_HI};
    color:{GREEN_HI}; font-weight:bold; }}
QPushButton#btnStart:hover {{ background:#0d5229; }}
QPushButton#btnStop {{ background:#3d0a0a; border-color:{RED_HI};
    color:{RED_HI}; font-weight:bold; }}
QPushButton#btnStop:hover {{ background:#5c1010; }}
QLineEdit, QComboBox, QDoubleSpinBox {{
    background:{DARK_CARD}; color:{TEXT_PRI}; border:1px solid {DARK_BORDER};
    border-radius:3px; padding:3px 6px; }}
QComboBox::drop-down {{ border:none; }}
QComboBox QAbstractItemView {{ background:{DARK_CARD}; color:{TEXT_PRI};
    selection-background-color:#1e2435; }}
QCheckBox {{ color:{TEXT_PRI}; spacing:6px; }}
QCheckBox::indicator {{ width:14px; height:14px; border:1px solid {DARK_BORDER};
    border-radius:2px; background:{DARK_CARD}; }}
QCheckBox::indicator:checked {{ background:{BLUE_HI}; border-color:{BLUE_HI}; }}
QTableWidget {{ background:{DARK_PANEL}; gridline-color:{DARK_BORDER}; border:none; }}
QTableWidget::item {{ padding:3px 6px; border:none; }}
QTableWidget::item:selected {{ background:#1e2435; }}
QHeaderView::section {{ background:{DARK_CARD}; color:{TEXT_SEC}; border:none;
    border-bottom:1px solid {DARK_BORDER}; padding:4px 6px; font-size:11px; }}
QScrollBar:vertical {{ background:{DARK_PANEL}; width:8px; }}
QScrollBar::handle:vertical {{ background:{DARK_BORDER}; border-radius:4px; min-height:20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0px; }}
QScrollBar:horizontal {{ background:{DARK_PANEL}; height:8px; }}
QScrollBar::handle:horizontal {{ background:{DARK_BORDER}; border-radius:4px; }}
QTextEdit {{ background:{DARK_PANEL}; color:{TEXT_SEC}; border:1px solid {DARK_BORDER};
    font-family:'Consolas','Courier New',monospace; font-size:11px; }}
QToolTip {{ background:{DARK_CARD}; color:{TEXT_PRI}; border:1px solid {BLUE_HI}; }}
QSplitter::handle {{ background:{DARK_BORDER}; }}
"""

# ─── UTILITIES ────────────────────────────────────────────────────────────────

def now_ms() -> int:
    return int(time.time() * 1000)

def fmt_pnl(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}"

def fmt_pct(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"

# ─── EMA30 DAILY SIGNAL ENGINE ────────────────────────────────────────────────

class TrendEngine:
    """
    Computes EMA30 on Day1 candles.
    Signal:
      LONG  — close > EMA30 (price above the daily trend line)
      SHORT — close < EMA30 (price below the daily trend line)
      NONE  — not enough data
    Exit: when the daily close crosses the EMA from the other side.
    """

    @staticmethod
    def ema(series: list, period: int) -> list:
        if len(series) < period:
            return []
        k = 2 / (period + 1)
        result = [sum(series[:period]) / period]
        for v in series[period:]:
            result.append(v * k + result[-1] * (1 - k))
        return result

    def compute(self, daily_candles: list) -> dict:
        """
        daily_candles: list of {t, o, h, l, c, v} — newest last.
        Returns {direction, ema_val, price, distance_pct, candle_count}
        """
        if len(daily_candles) < EMA_PERIOD + 1:
            return {"direction": "NONE", "ema_val": 0, "price": 0,
                    "distance_pct": 0, "candle_count": len(daily_candles)}

        closes = [c["c"] for c in daily_candles]
        ema_vals = self.ema(closes, EMA_PERIOD)
        if not ema_vals:
            return {"direction": "NONE", "ema_val": 0, "price": 0,
                    "distance_pct": 0, "candle_count": len(daily_candles)}

        price   = closes[-1]
        ema_val = ema_vals[-1]
        dist    = (price - ema_val) / ema_val * 100   # + = above, - = below
        direction = "LONG" if price > ema_val else "SHORT"

        return {
            "direction":    direction,
            "ema_val":      round(ema_val, 6),
            "price":        round(price, 6),
            "distance_pct": round(dist, 3),
            "candle_count": len(daily_candles),
            "ema_series":   ema_vals,   # used by chart overlay
        }

# ─── MEXC REST CLIENT ─────────────────────────────────────────────────────────

class MexcClient:
    """
    MEXC Futures REST client (stdlib urllib, no third-party dep).
    Signing: HMAC-SHA256(secret, apiKey + timestamp_ms + paramString)
    """
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key    = api_key
        self.api_secret = api_secret

    def _sign(self, ts_str: str, param_str: str) -> str:
        target = self.api_key + ts_str + param_str
        return hmac.new(self.api_secret.encode("utf-8"),
                        target.encode("utf-8"), hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict = None,
                 signed: bool = True, timeout: int = 12) -> dict:
        url    = MEXC_REST + path
        method = method.upper()

        if method == "GET":
            p  = dict(sorted((params or {}).items()))
            qs = "&".join(
                f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in p.items()
            ) if p else ""
            body_bytes   = None
            sign_payload = qs
            full_url     = url + ("?" + qs if qs else "")
        else:
            body_str     = json.dumps(params or {}, separators=(",", ":"))
            body_bytes   = body_str.encode("utf-8")
            sign_payload = body_str
            full_url     = url

        headers = {"Content-Type": "application/json", "User-Agent": "MexcTrendBot/2.0"}
        if signed:
            if not self.api_key or not self.api_secret:
                return {"success": False, "error": "API key/secret not set"}
            ts_str = str(int(time.time() * 1000))
            headers.update({"ApiKey": self.api_key, "Request-Time": ts_str,
                            "Signature": self._sign(ts_str, sign_payload)})

        req  = urllib.request.Request(full_url, data=body_bytes,
                                      headers=headers, method=method)
        last_exc = None
        raw  = b""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                break
            except urllib.error.HTTPError as e:
                try:    raw = e.read()
                except: raw = b""
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(0.5 * (2 ** attempt)); last_exc = e; continue
                try:    return json.loads(raw.decode("utf-8", errors="replace"))
                except: return {"success": False, "code": e.code,
                                "msg": raw.decode("utf-8", errors="replace")[:300]}
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_exc = e
                if attempt < 2: time.sleep(0.5 * (2 ** attempt)); continue
                return {"success": False, "error": str(e)}

        if not raw:
            return {"success": False, "error": f"Empty response (last: {last_exc})"}
        try:    return json.loads(raw.decode("utf-8"))
        except: return {"success": False, "error": "Unparseable response"}

    def get(self, path, params=None, signed=False):
        return self._request("GET", path, params, signed=signed)

    def post(self, path, body=None, signed=True):
        return self._request("POST", path, body, signed=signed)

    def klines(self, symbol: str, interval: str, limit: int = 60) -> list:
        """interval: Min1, Min5, Min15, Min30, Min60, Hour4, Day1"""
        data = self.get(f"/api/v1/contract/kline/{symbol}",
                        {"interval": interval, "limit": limit})
        if "data" not in data:
            return []
        raw = data["data"]
        candles = []
        for i in range(len(raw.get("time", []))):
            try:
                candles.append({
                    "t": float(raw["time"][i]),
                    "o": float(raw["open"][i]),
                    "h": float(raw["high"][i]),
                    "l": float(raw["low"][i]),
                    "c": float(raw["close"][i]),
                    "v": float(raw["vol"][i]),
                })
            except Exception:
                pass
        return candles

    def ticker(self, symbol: str) -> dict:
        return self.get("/api/v1/contract/ticker", {"symbol": symbol}).get("data", {})

    def contract_detail(self, symbol: str = None) -> list:
        params = {"symbol": symbol} if symbol else {}
        data   = self.get("/api/v1/contract/detail", params)
        d      = data.get("data", [])
        if isinstance(d, dict): d = [d]
        return d if isinstance(d, list) else []

    def get_balance(self) -> dict:
        return self.get("/api/v1/private/account/assets", signed=True)

    def get_positions(self) -> list:
        r = self.get("/api/v1/private/position/open_positions", signed=True)
        return r.get("data", [])

    def place_order(self, symbol, side, price, vol, leverage,
                    open_type=1, order_type=1,
                    take_profit=None, stop_loss=None) -> dict:
        body = {"symbol": symbol, "side": side, "openType": open_type,
                "type": order_type, "vol": vol, "leverage": leverage}
        if order_type == 1 and price:
            body["price"] = round(price, 6)
        if take_profit: body["takeProfitPrice"] = take_profit
        if stop_loss:   body["stopLossPrice"]   = stop_loss
        return self.post("/api/v1/private/order/submit", body)

    def market_close(self, symbol: str, direction: str,
                     vol: float, pos_id: str = "") -> dict:
        side = 4 if direction == "LONG" else 2
        body = {"symbol": symbol, "price": 0, "vol": vol,
                "side": side, "type": 5, "openType": 1}
        if pos_id: body["positionId"] = pos_id
        return self.post("/api/v1/private/order/submit", body)

    def set_leverage(self, symbol: str, leverage: int,
                     position_type: int = 1) -> dict:
        return self.post("/api/v1/private/position/change_leverage",
                         {"symbol": symbol, "leverage": leverage,
                          "positionType": position_type})

# ─── WEBSOCKET MANAGER ────────────────────────────────────────────────────────

class WsManager(QThread):
    tick_received = pyqtSignal(str, dict)
    ws_status     = pyqtSignal(bool)
    ws_error      = pyqtSignal(str)

    def __init__(self, symbols: list, api_key: str = "", api_secret: str = ""):
        super().__init__()
        self.symbols    = symbols
        self.api_key    = api_key
        self.api_secret = api_secret
        self._ws        = None
        self._running   = False

    def _on_open(self, ws):
        self.ws_status.emit(True)
        if self.api_key and self.api_secret:
            ts  = str(now_ms())
            sig = hmac.new(self.api_secret.encode(),
                           (self.api_key + ts).encode(),
                           hashlib.sha256).hexdigest()
            ws.send(json.dumps({"method": "login", "param": {
                "apiKey": self.api_key, "reqTime": ts, "signature": sig}}))
        for sym in self.symbols[:28]:
            ws.send(json.dumps({"method": "sub.deal", "param": {"symbol": sym}}))
        self._start_ping(ws)

    def _start_ping(self, ws):
        def loop():
            while self._running:
                try:
                    if ws.sock and ws.sock.connected:
                        ws.send(json.dumps({"method": "ping"}))
                    else:
                        break
                except Exception:
                    break
                time.sleep(15)
        threading.Thread(target=loop, daemon=True).start()

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return
        ch  = data.get("channel", "")
        if "pong" in ch or ch.startswith("rs."):
            return
        sym = data.get("symbol", "")
        d   = data.get("data")
        if not sym or d is None:
            return
        self.tick_received.emit(sym, {"channel": ch, "data": d})

    def _on_error(self, ws, error):
        try:   self.ws_error.emit(str(error)[:160])
        except Exception: pass

    def _on_close(self, ws, *args):
        self.ws_status.emit(False)
        if self._running:
            self.ws_error.emit("connection closed — reconnecting in 3s")
            time.sleep(3)
            self._connect()

    def _connect(self):
        if not HAS_WS: return
        self._ws = ws_lib.WebSocketApp(
            MEXC_WS,
            on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close)
        self._ws.run_forever(ping_interval=20, ping_timeout=10,
                             sslopt={"cert_reqs": ssl.CERT_NONE})

    def run(self):
        self._running = True
        self._connect()

    def stop(self):
        self._running = False
        if self._ws:
            try: self._ws.close()
            except: pass

# ─── BALANCE WORKER ───────────────────────────────────────────────────────────

def _parse_usdt_balance(resp: dict):
    if not isinstance(resp, dict): return None
    data = resp.get("data")
    def _from(a):
        for k in ("equity", "availableBalance", "cashBalance"):
            if a.get(k) is not None:
                try:    return float(a[k])
                except: pass
        return None
    if isinstance(data, list):
        for a in data:
            if isinstance(a, dict) and a.get("currency") == "USDT":
                return _from(a)
    elif isinstance(data, dict):
        if data.get("currency") in (None, "USDT"):
            return _from(data)
    return None

def _parse_usdt_avail(resp: dict):
    if not isinstance(resp, dict): return None
    data   = resp.get("data")
    assets = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for a in assets:
        if isinstance(a, dict) and a.get("currency") in (None, "USDT"):
            v = a.get("availableBalance")
            if v is not None:
                try:    return float(v)
                except: return None
    return None


class BalanceWorker(QRunnable):
    class Signals(QObject):
        done  = pyqtSignal(float, float)
        error = pyqtSignal(str)

    def __init__(self, client: MexcClient):
        super().__init__()
        self.client  = client
        self.signals = BalanceWorker.Signals()

    def run(self):
        try:
            resp = self.client.get_balance()
            if isinstance(resp, dict) and resp.get("error"):
                self.signals.error.emit(str(resp["error"])[:160]); return
            bal = _parse_usdt_balance(resp)
            if bal is not None:
                avail = _parse_usdt_avail(resp)
                self.signals.done.emit(bal, avail if avail is not None else bal)
            else:
                self.signals.error.emit(f"USDT not found: {str(resp)[:120]}")
        except Exception as e:
            self.signals.error.emit(str(e))

# ─── DAILY SIGNAL WORKER ─────────────────────────────────────────────────────

class DailySignalWorker(QRunnable):
    """
    Fetches Day1 klines for one symbol and computes the EMA30 trend signal.
    Replaces the old ScanWorker entirely — no 1m/5m, no multi-indicator scoring.
    """
    class Signals(QObject):
        done = pyqtSignal(str, dict)

    def __init__(self, symbol: str, client: MexcClient,
                 engine: TrendEngine, candle_cache: dict):
        super().__init__()
        self.symbol       = symbol
        self.client       = client
        self.engine       = engine
        self.candle_cache = candle_cache
        self.signals      = DailySignalWorker.Signals()

    def run(self):
        try:
            # Fetch enough daily bars for a solid EMA30 (50 gives warm-up)
            daily = self.client.klines(self.symbol, "Day1", 50)
            if daily:
                self.candle_cache[self.symbol] = {"Day1": daily}
            result = self.engine.compute(daily or [])
            result["symbol"] = self.symbol
            result["ts"]     = time.time()
            self.signals.done.emit(self.symbol, result)
        except Exception as e:
            self.signals.done.emit(self.symbol, {
                "symbol": self.symbol, "direction": "NONE",
                "ema_val": 0, "price": 0, "distance_pct": 0,
                "candle_count": 0, "error": str(e)
            })

# ─── CHART WORKER (daily, display only) ──────────────────────────────────────

class ChartWorker(QRunnable):
    class Signals(QObject):
        done = pyqtSignal(str, list)   # symbol, daily_candles

    def __init__(self, symbol: str, client: MexcClient):
        super().__init__()
        self.symbol  = symbol
        self.client  = client
        self.signals = ChartWorker.Signals()

    def run(self):
        try:
            candles = self.client.klines(self.symbol, "Day1", 50)
            self.signals.done.emit(self.symbol, candles or [])
        except Exception:
            self.signals.done.emit(self.symbol, [])

# ─── DAILY CANDLE CHART WIDGET ────────────────────────────────────────────────

class TimeAxisItem(pg.AxisItem):
    """Day timestamps as YYYY-MM-DD on the x-axis."""
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            try:
                out.append(datetime.fromtimestamp(float(v), tz=timezone.utc)
                           .strftime("%m-%d"))
            except Exception:
                out.append("")
        return out


class DailyCandleChart(QWidget):
    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self.symbol   = symbol
        self._candles = []
        self._levels  = []
        self._levels_key = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        top = QHBoxLayout()
        lbl = QLabel(f"{symbol.replace('_USDT','')}  Day1 · EMA{EMA_PERIOD}")
        lbl.setStyleSheet(f"color:{BLUE_HI}; font-weight:bold;")
        top.addWidget(lbl)
        top.addStretch()
        self._ema_lbl = QLabel("EMA —")
        self._ema_lbl.setStyleSheet(f"color:{AMBER_HI}; font-size:11px;")
        top.addWidget(self._ema_lbl)
        layout.addLayout(top)

        pg.setConfigOptions(antialias=False, useOpenGL=False)
        self.plot_widget = pg.PlotWidget(
            background=DARK_PANEL,
            axisItems={"bottom": TimeAxisItem(orientation="bottom")})
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis("left").setTextPen(TEXT_SEC)
        self.plot_widget.getAxis("bottom").setTextPen(TEXT_SEC)
        layout.addWidget(self.plot_widget)

    def update_candles(self, candles: list):
        self._candles = candles
        self.refresh()

    def set_levels(self, levels: list):
        key = [(round(l["entry"], 8), round(l["sl"], 8)) for l in levels]
        if key == self._levels_key:
            return
        self._levels_key = key
        self._levels     = levels
        self.refresh()

    def _hline(self, y: float, text: str, color: str):
        line = pg.InfiniteLine(
            pos=y, angle=0,
            pen=pg.mkPen(color, width=1, style=Qt.DashLine),
            label=f"{text} {y:.4f}",
            labelOpts={"color": color, "position": 0.04,
                       "fill": (10, 14, 20, 160)})
        self.plot_widget.addItem(line)

    def refresh(self):
        if not self._candles:
            return
        self.plot_widget.clear()
        eng    = TrendEngine()
        closes = [c["c"] for c in self._candles]
        ema_v  = eng.ema(closes, EMA_PERIOD)
        times  = [c["t"] for c in self._candles]
        n      = len(self._candles)
        w      = (times[-1] - times[0]) / n * 0.4 if n > 1 else 86400 * 0.4

        for c in self._candles:
            color = GREEN_HI if c["c"] >= c["o"] else RED_HI
            self.plot_widget.plot([c["t"], c["t"]], [c["l"], c["h"]],
                                  pen=pg.mkPen(color, width=1))
            rect = pg.QtWidgets.QGraphicsRectItem(
                c["t"] - w / 2, min(c["o"], c["c"]),
                w, abs(c["c"] - c["o"]))
            rect.setPen(pg.mkPen(color, width=0))
            rect.setBrush(pg.mkBrush(color))
            self.plot_widget.addItem(rect)

        if ema_v:
            offset = len(times) - len(ema_v)
            t_ema  = times[offset:]
            self.plot_widget.plot(t_ema, ema_v,
                                  pen=pg.mkPen(AMBER_HI, width=2))
            self._ema_lbl.setText(f"EMA{EMA_PERIOD} {ema_v[-1]:.4f}")

        for lv in self._levels:
            self._hline(lv["entry"], f"Entry {lv['direction']}", TEXT_SEC)
            if lv.get("sl"):
                self._hline(lv["sl"], "SL", RED_HI)

# ─── PAPER TRADE ENGINE (simple — hold until EMA flip or manual close) ────────

class PaperEngine:
    """Simplified paper engine: no partials, no breakeven, no trailing.
    Entry on EMA30 cross, exit when EMA flips the other way or manual close."""

    def __init__(self):
        self.balance   = PAPER_START_BALANCE
        self.positions: list = []
        self.history:  list = []
        self._id       = 0

    def _nid(self) -> str:
        self._id += 1
        return f"PAPER-{self._id}"

    def place(self, symbol, direction, price, margin, leverage, sl_pct, vol=None):
        if margin > self.balance:
            return None
        qty     = vol if vol is not None else (margin * leverage) / price
        sl_price = price * (1 - sl_pct / 100) if direction == "LONG" \
                   else price * (1 + sl_pct / 100)
        pos = {
            "id": self._nid(), "symbol": symbol, "direction": direction,
            "entry": price, "qty": qty, "vol": vol,
            "margin": margin, "leverage": leverage,
            "sl": sl_price, "sl_pct": sl_pct,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self.balance -= margin
        self.positions.append(pos)
        return pos

    def _pnl(self, pos, price):
        pnl_pct = ((price - pos["entry"]) / pos["entry"] * 100
                   * (1 if pos["direction"] == "LONG" else -1)
                   * pos["leverage"])
        net_pct = pnl_pct - ROUND_TRIP_FEE * 100 * pos["leverage"]
        return pos["margin"] * net_pct / 100, net_pct

    def check_sl(self, prices: dict) -> list:
        """Check server-side SL only (no trailing/partial)."""
        events = []
        for pos in list(self.positions):
            price = prices.get(pos["symbol"])
            if not price:
                continue
            hit = None
            if pos["direction"] == "LONG"  and price <= pos["sl"]: hit = "SL"
            if pos["direction"] == "SHORT" and price >= pos["sl"]: hit = "SL"
            if hit:
                pnl_usd, pnl_pct = self._pnl(pos, price)
                self.balance += pos["margin"] + pnl_usd
                ev = {**pos, "exit": price,
                      "exit_at": datetime.now(timezone.utc).isoformat(),
                      "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                      "reason": hit}
                events.append(ev)
                self.history.append(ev)
                self.positions.remove(pos)
        return events

    def close_ema_flip(self, symbol: str, prices: dict) -> list:
        """Close all positions on symbol when the daily EMA flips direction."""
        events = []
        price  = prices.get(symbol, 0)
        for pos in [p for p in list(self.positions) if p["symbol"] == symbol]:
            if not price:
                continue
            pnl_usd, pnl_pct = self._pnl(pos, price)
            self.balance += pos["margin"] + pnl_usd
            ev = {**pos, "exit": price,
                  "exit_at": datetime.now(timezone.utc).isoformat(),
                  "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                  "reason": "EMA_FLIP"}
            events.append(ev)
            self.history.append(ev)
            self.positions.remove(pos)
        return events

    def close_manual(self, pos_id: str, price: float) -> dict | None:
        pos = next((p for p in self.positions if p["id"] == pos_id), None)
        if not pos:
            return None
        pnl_usd, pnl_pct = self._pnl(pos, price)
        self.balance += pos["margin"] + pnl_usd
        ev = {**pos, "exit": price,
              "exit_at": datetime.now(timezone.utc).isoformat(),
              "pnl_usd": pnl_usd, "pnl_pct": pnl_pct, "reason": "MANUAL"}
        self.history.append(ev)
        self.positions = [p for p in self.positions if p["id"] != pos_id]
        return ev

# ─── LIVE POSITION MANAGER (daily hold — no scalp lifecycle) ─────────────────

class LiveManager:
    """
    Tracks live MEXC positions. Exits when:
      1. Server-side SL is hit (exchange handles it)
      2. Daily EMA flips direction (bot fires a reduce-only market close)
      3. Manual close from UI
    No partials, no breakeven, no trailing.
    """

    def __init__(self, client: MexcClient, log):
        self._client = client
        self._log    = log
        self.state   = {}   # symbol → management record

    def set_client(self, client):
        self._client = client

    def register(self, symbol, direction, entry, sl_pct, leverage):
        if symbol not in self.state:
            sl = entry * (1 - sl_pct / 100) if direction == "LONG" \
                 else entry * (1 + sl_pct / 100)
            self.state[symbol] = {
                "symbol": symbol, "direction": direction,
                "entry": entry, "sl": sl, "sl_pct": sl_pct,
                "leverage": leverage, "margin": 0, "vol": 0,
                "pos_id": "", "be_armed": False,
                "opened_at": datetime.now(timezone.utc).isoformat(),
            }

    def sync(self, prices: dict):
        """Re-read live positions from exchange; return normalized list for UI."""
        try:
            live = self._client.get_positions() or []
        except Exception as e:
            self._log(f"  ⚠ positions fetch failed: {e}", AMBER_HI)
            return []

        seen, norm = set(), []
        for p in live:
            sym = p.get("symbol")
            if not sym: continue
            entry  = float(p.get("holdAvgPrice") or p.get("openAvgPrice") or 0)
            vol    = float(p.get("holdVol") or 0)
            if entry <= 0 or vol <= 0: continue
            seen.add(sym)
            direction = "LONG" if p.get("positionType") == 1 else "SHORT"
            lev       = int(p.get("leverage") or 1)
            margin    = float(p.get("im") or p.get("oim") or 0)
            pos_id    = str(p.get("positionId") or "")

            rec = self.state.get(sym)
            if rec:
                rec.update(vol=vol, margin=margin, pos_id=pos_id, leverage=lev)
            else:
                sl_pct = 5.0   # default SL if entered outside this session
                sl     = entry * (1 - sl_pct / 100) if direction == "LONG" \
                         else entry * (1 + sl_pct / 100)
                self.state[sym] = dict(
                    symbol=sym, direction=direction, entry=entry,
                    vol=vol, leverage=lev, margin=margin, pos_id=pos_id,
                    sl=sl, sl_pct=sl_pct, be_armed=False,
                    opened_at=datetime.now(timezone.utc).isoformat())

            norm.append({"id": pos_id, "symbol": sym, "direction": direction,
                         "entry": entry, "margin": margin, "leverage": lev})

        for sym in list(self.state):
            if sym not in seen:
                self.state.pop(sym, None)
        return norm

    def close_ema_flip(self, symbol: str, prices: dict) -> bool:
        """Fire a market close on EMA flip. Returns True if sent successfully."""
        rec = self.state.get(symbol)
        if not rec: return False
        price = prices.get(symbol, 0)
        if not price: return False
        try:
            r = self._client.market_close(symbol, rec["direction"],
                                          int(rec["vol"]), rec.get("pos_id", ""))
        except Exception as e:
            self._log(f"  ⚠ EMA flip close error {symbol}: {e}", AMBER_HI)
            return False
        ok = isinstance(r, dict) and (r.get("success") or r.get("code") == 0)
        if ok:
            self.state.pop(symbol, None)
        else:
            msg = r.get("message", r) if isinstance(r, dict) else r
            self._log(f"  ⚠ EMA flip close rejected {symbol}: {msg}", AMBER_HI)
        return ok

# ─── CLAUDE TREND ANALYSER ────────────────────────────────────────────────────

class ClaudeAnalyser(QThread):
    analysis_done = pyqtSignal(str, str)   # symbol, json_text

    def __init__(self, api_key: str = ""):
        super().__init__()
        self._api_key = api_key.strip()
        self._queue   = queue.Queue()
        self._running = False

    def set_key(self, key: str):
        self._api_key = key.strip()

    def enqueue(self, symbol: str, context: dict):
        self._queue.put((symbol, context))

    def run(self):
        self._running = True
        while self._running:
            try:
                symbol, ctx = self._queue.get(timeout=1)
                self._analyse(symbol, ctx)
            except queue.Empty:
                pass

    def stop(self):
        self._running = False

    def _analyse(self, symbol: str, ctx: dict):
        if not self._api_key or not HAS_REQUESTS:
            self.analysis_done.emit(symbol, json.dumps({
                "verdict": "NO_KEY", "confidence": 0,
                "reasoning": "Claude API key not set.",
                "outlook": "—", "exit_signal": False
            }))
            return

        prompt = f"""You are a crypto trend analyst reviewing a MEXC futures position managed by the EMA{EMA_PERIOD} daily strategy.

Strategy rule: hold LONG above EMA{EMA_PERIOD}, hold SHORT below EMA{EMA_PERIOD}. Exit when the daily close crosses the EMA.

Current state:
{json.dumps(ctx, indent=2)}

Analyse:
1. Is the daily trend intact or weakening?
2. Is the EMA holding as support/resistance?
3. Should we exit early (momentum breakdown, high-risk macro event) or hold?
4. What is the likely near-term direction?

Respond ONLY in this exact JSON (no markdown, no preamble):
{{"verdict":"HOLD",
  "confidence":7,
  "reasoning":"Brief step-by-step read of the daily trend.",
  "outlook":"1-2 sentences on near-term direction.",
  "exit_signal":false,
  "exit_reason":""}}"""

        try:
            resp = req_lib.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self._api_key,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": CLAUDE_MODEL, "max_tokens": 500,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=25)
        except Exception as e:
            self.analysis_done.emit(symbol, json.dumps({
                "verdict": "ERROR", "confidence": 0,
                "reasoning": f"Network error: {e}", "outlook": "—",
                "exit_signal": False, "exit_reason": ""}))
            return

        if resp.status_code != 200:
            self.analysis_done.emit(symbol, json.dumps({
                "verdict": "ERROR", "confidence": 0,
                "reasoning": f"API {resp.status_code}: {resp.text[:200]}",
                "outlook": "—", "exit_signal": False, "exit_reason": ""}))
            return

        try:
            text = resp.json()["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"): text = text[4:]
            parsed = json.loads(text.strip())
            self.analysis_done.emit(symbol, json.dumps(parsed))
        except Exception as e:
            self.analysis_done.emit(symbol, json.dumps({
                "verdict": "PARSE_ERROR", "confidence": 0,
                "reasoning": f"Parse error: {e}\n\n{resp.text[:400]}",
                "outlook": "—", "exit_signal": False, "exit_reason": ""}))

# ─── SETTINGS PANEL ──────────────────────────────────────────────────────────

class SettingsPanel(QWidget):
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        ml = QVBoxLayout(self); ml.setContentsMargins(0,0,0,0); ml.addWidget(scroll)
        layout = QVBoxLayout(inner); layout.setSpacing(12)

        # API keys
        grp = QGroupBox("API Keys")
        f   = QWidget(); fl = QGridLayout(f); fl.setSpacing(6)
        fl.addWidget(QLabel("MEXC API Key:"), 0, 0)
        self.mexc_key = QLineEdit(); self.mexc_key.setEchoMode(QLineEdit.Password)
        fl.addWidget(self.mexc_key, 0, 1)
        fl.addWidget(QLabel("MEXC Secret:"), 1, 0)
        self.mexc_secret = QLineEdit(); self.mexc_secret.setEchoMode(QLineEdit.Password)
        fl.addWidget(self.mexc_secret, 1, 1)
        fl.addWidget(QLabel("Claude API Key:"), 2, 0)
        self.claude_key = QLineEdit(); self.claude_key.setEchoMode(QLineEdit.Password)
        fl.addWidget(self.claude_key, 2, 1)
        btn_save = QPushButton("Save Keys")
        btn_save.clicked.connect(self._save)
        fl.addWidget(btn_save, 3, 1)
        vg = QVBoxLayout(grp); vg.addWidget(f)
        layout.addWidget(grp)

        # Trade parameters
        grp2 = QGroupBox("Trade Parameters")
        g    = QGridLayout(grp2); g.setSpacing(8)

        g.addWidget(QLabel("💰 Margin (USDT):"), 0, 0)
        self.cbo_margin = QComboBox(); self.cbo_margin.setEditable(True)
        for v in MARGIN_OPTIONS: self.cbo_margin.addItem(str(v))
        self.cbo_margin.setCurrentText("50")
        g.addWidget(self.cbo_margin, 0, 1)

        g.addWidget(QLabel("⚡ Leverage:"), 1, 0)
        self.cbo_leverage = QComboBox()
        for v in LEVERAGE_OPTIONS: self.cbo_leverage.addItem(str(v), v)
        self.cbo_leverage.setCurrentText("10")
        g.addWidget(self.cbo_leverage, 1, 1)

        g.addWidget(QLabel("🛡 Stop Loss %:"), 2, 0)
        self.spn_sl = QDoubleSpinBox()
        self.spn_sl.setRange(0.5, 20); self.spn_sl.setValue(5.0)
        self.spn_sl.setSingleStep(0.5)
        self.spn_sl.setToolTip(
            "Distance from entry price. For daily trend trades a wider SL "
            "(3–8%) is normal — positions are held for days, not minutes.")
        g.addWidget(self.spn_sl, 2, 1)

        g.addWidget(QLabel("Max Positions:"), 3, 0)
        self.cbo_max_pos = QComboBox()
        for v in [1,2,3,4,5]: self.cbo_max_pos.addItem(str(v), v)
        self.cbo_max_pos.setCurrentIndex(4)   # default 5
        g.addWidget(self.cbo_max_pos, 3, 1)

        layout.addWidget(grp2)

        # Assets
        grp3 = QGroupBox("Active Assets")
        ag   = QGridLayout(grp3); ag.setSpacing(4)
        self._asset_chks = {}
        COLS = 3
        for i, sym in enumerate(TOP_ASSETS):
            short = sym.replace("_USDT", "")
            chk   = QCheckBox(short)
            chk.setChecked(True)
            self._asset_chks[sym] = chk
            ag.addWidget(chk, i // COLS, i % COLS)
        layout.addWidget(grp3)

        layout.addStretch()
        btn_apply = QPushButton("⚡ Apply")
        btn_apply.clicked.connect(self._apply)
        layout.addWidget(btn_apply)

    def _save(self):
        s = QSettings("MexcTrendBot", "keys")
        s.setValue("mexc_key",    self.mexc_key.text())
        s.setValue("mexc_secret", self.mexc_secret.text())
        s.setValue("claude_key",  self.claude_key.text())
        s.setValue("margin",  self.cbo_margin.currentText())
        s.setValue("leverage", self.cbo_leverage.currentText())
        s.setValue("sl_pct",  str(self.spn_sl.value()))
        s.setValue("max_pos", str(self.cbo_max_pos.currentData()))
        self.settings_changed.emit()

    def _load(self):
        s = QSettings("MexcTrendBot", "keys")
        self.mexc_key.setText(s.value("mexc_key", ""))
        self.mexc_secret.setText(s.value("mexc_secret", ""))
        self.claude_key.setText(s.value("claude_key", ""))
        if m := s.value("margin"):    self.cbo_margin.setCurrentText(m)
        if l := s.value("leverage"):  self.cbo_leverage.setCurrentText(l)
        if sl := s.value("sl_pct"):
            try: self.spn_sl.setValue(float(sl))
            except: pass

    def _apply(self):
        self._save()

    def get_config(self) -> dict:
        return {
            "mexc_key":    self.mexc_key.text().strip(),
            "mexc_secret": self.mexc_secret.text().strip(),
            "claude_key":  self.claude_key.text().strip(),
            "margin":      float(self.cbo_margin.currentText() or 50),
            "leverage":    int(self.cbo_leverage.currentData() or 10),
            "sl_pct":      self.spn_sl.value(),
            "max_positions": int(self.cbo_max_pos.currentData() or 5),
            "active_assets": [s for s, c in self._asset_chks.items() if c.isChecked()],
        }

# ─── SCAN LOG ────────────────────────────────────────────────────────────────

class ScanLog(QWidget):
    MAX_LINES = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self._txt = QTextEdit()
        self._txt.setReadOnly(True)
        self._txt.document().setMaximumBlockCount(self.MAX_LINES)
        layout.addWidget(self._txt)
        self._pending = []
        self._timer   = QTimer()
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._flush)
        self._timer.start()

    def log(self, msg: str, color: str = TEXT_SEC):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._pending.append((ts, msg, color))

    def _flush(self):
        if not self._pending: return
        for ts, msg, color in self._pending:
            self._txt.append(f'<span style="color:{TEXT_DIM}">{ts}</span> '
                             f'<span style="color:{color}">{msg}</span>')
        self._pending.clear()
        self._txt.ensureCursorVisible()

# ─── POSITIONS PANEL ─────────────────────────────────────────────────────────

class PositionsPanel(QWidget):
    close_requested = pyqtSignal(str, str)   # pos_id, symbol
    hedge_requested = pyqtSignal(str, str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._hdr = QLabel(" Open Positions")
        self._hdr.setStyleSheet(
            f"color:{BLUE_HI}; font-weight:bold; font-size:12px; "
            f"padding:4px; background:{DARK_CARD}; border-bottom:1px solid {DARK_BORDER};")
        layout.addWidget(self._hdr)
        self._empty = QLabel("  No open positions")
        self._empty.setStyleSheet(f"color:{TEXT_DIM}; padding:12px;")
        layout.addWidget(self._empty)
        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(4)
        self._cards_layout.addStretch()
        layout.addLayout(self._cards_layout)
        layout.addStretch()
        self._cards = {}
        self._card_keys = []

    def update_positions(self, positions: list, prices: dict,
                         paper_engine=None, live_mgr=None):
        keys = [str(p.get("id") or p.get("symbol")) for p in positions]
        if keys != self._card_keys:
            for c in self._cards.values(): c["frame"].setParent(None)
            self._cards.clear()
            self._empty.setVisible(not positions)
            for pos in positions:
                card = self._build_card(pos)
                key  = str(pos.get("id") or pos.get("symbol"))
                self._cards[key] = card
                self._cards_layout.insertWidget(
                    self._cards_layout.count() - 1, card["frame"])
            self._card_keys = keys

        for pos in positions:
            key   = str(pos.get("id") or pos.get("symbol"))
            card  = self._cards.get(key)
            if not card: continue
            sym   = pos.get("symbol", "")
            entry = pos.get("entry", 0)
            price = prices.get(sym, entry)
            dirc  = pos.get("direction", "?")
            lev   = pos.get("leverage", 1)
            margin = pos.get("margin", 0)
            pnl_pct = ((price - entry) / entry * 100
                       * (1 if dirc == "LONG" else -1) * lev
                       - ROUND_TRIP_FEE * 100 * lev) if entry else 0
            pnl_usd = margin * pnl_pct / 100
            col = GREEN_HI if pnl_usd >= 0 else RED_HI
            card["pnl_usd"].setText(fmt_pnl(pnl_usd))
            card["pnl_usd"].setStyleSheet(f"color:{col}; font-weight:bold;")
            card["pnl_pct"].setText(fmt_pct(pnl_pct))
            card["pnl_pct"].setStyleSheet(f"color:{col}; font-size:11px;")

    def _build_card(self, pos: dict) -> dict:
        sym   = pos.get("symbol", "")
        dirc  = pos.get("direction", "?")
        dcol  = GREEN_HI if dirc == "LONG" else RED_HI

        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:{DARK_CARD};border:1px solid {DARK_BORDER};"
            f"border-radius:4px;}}QLabel{{border:0;}}")
        v = QVBoxLayout(frame); v.setContentsMargins(7,5,7,5); v.setSpacing(2)

        r1 = QHBoxLayout(); r1.setSpacing(4)
        head = QLabel(f"{sym.replace('_USDT','')}  "
                      f"<span style='color:{dcol}'>{dirc}</span>  "
                      f"<span style='color:{TEXT_DIM}'>{pos.get('leverage',1)}x</span>")
        head.setStyleSheet("font-weight:bold; font-size:11px;")
        pnl_usd = QLabel("—"); pnl_usd.setStyleSheet("font-weight:bold;")
        pnl_usd.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        r1.addWidget(head); r1.addStretch(); r1.addWidget(pnl_usd)
        v.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(4)
        pnl_pct = QLabel("—")
        btn = QPushButton("✕ Close"); btn.setFixedHeight(20)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{background:#3a1d24;border:1px solid #ff1744;"
            "color:#ff5a76;font-size:9px;border-radius:2px;padding:1px 6px;}"
            "QPushButton:hover{background:#ff1744;color:white;}")
        pid = str(pos.get("id") or sym)
        btn.clicked.connect(lambda _=False, p=pid, s=sym:
                            self.close_requested.emit(p, s))
        r2.addWidget(pnl_pct); r2.addStretch(); r2.addWidget(btn)
        v.addLayout(r2)

        def small(txt):
            l = QLabel(txt); l.setStyleSheet(f"color:{TEXT_SEC}; font-size:9px;")
            return l

        entry  = pos.get("entry", 0)
        margin = pos.get("margin", 0)
        v.addWidget(small(f"Entry {entry:.4f}   ·   Mgn ${margin:.1f}"))
        v.addWidget(small(f"Opened {pos.get('opened_at','')[:16]}"))

        return {"frame": frame, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct}

# ─── TRADE HISTORY TABLE ─────────────────────────────────────────────────────

class TradeHistoryTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self._tbl = QTableWidget(0, 7)
        self._tbl.setHorizontalHeaderLabels(
            ["Symbol","Dir","Entry","Exit","PnL $","PnL %","Reason"])
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        layout.addWidget(self._tbl)

        self._stats = QLabel("  No trades yet")
        self._stats.setStyleSheet(f"color:{TEXT_SEC}; font-size:10px; padding:4px;")
        layout.addWidget(self._stats)

    def add_trade(self, ev: dict):
        r   = self._tbl.rowCount()
        self._tbl.insertRow(r)
        pnl = ev.get("pnl_usd", 0)
        col = QColor(GREEN_HI if pnl >= 0 else RED_HI)

        def item(txt, align=Qt.AlignLeft):
            i = QTableWidgetItem(str(txt)); i.setTextAlignment(align); return i

        self._tbl.setItem(r, 0, item(ev.get("symbol","").replace("_USDT","")))
        self._tbl.setItem(r, 1, item(ev.get("direction","?")))
        self._tbl.setItem(r, 2, item(f"{ev.get('entry',0):.4f}"))
        self._tbl.setItem(r, 3, item(f"{ev.get('exit',0):.4f}"))
        p = item(fmt_pnl(pnl), Qt.AlignRight)
        p.setForeground(col)
        self._tbl.setItem(r, 4, p)
        pp = item(fmt_pct(ev.get("pnl_pct",0)), Qt.AlignRight)
        pp.setForeground(col)
        self._tbl.setItem(r, 5, pp)
        self._tbl.setItem(r, 6, item(ev.get("reason","?")))
        self._tbl.scrollToBottom()
        self._update_stats()

    def populate(self, trades: list):
        self._tbl.setRowCount(0)
        for ev in trades:
            self.add_trade(ev)

    def _update_stats(self):
        n = self._tbl.rowCount()
        wins  = sum(1 for r in range(n)
                    if self._tbl.item(r, 4) and
                    "+" in (self._tbl.item(r, 4).text() or ""))
        self._stats.setText(
            f"  Trades: {n}  |  Wins: {wins}  |  "
            f"Win rate: {wins/n*100:.0f}%" if n else "  No trades yet")

# ─── AI ANALYSIS TAB ─────────────────────────────────────────────────────────

VERDICT_COLORS = {
    "HOLD": GREEN_HI, "EXIT": RED_HI,
    "ERROR": RED_HI, "PARSE_ERROR": AMBER_HI, "NO_KEY": TEXT_DIM
}


class AIAnalysisTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self); layout.setContentsMargins(4,4,4,4)

        left = QWidget(); left.setMaximumWidth(260)
        lv   = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0)
        hdr  = QLabel("  📊 Trend Analyses")
        hdr.setStyleSheet(
            f"color:{BLUE_HI}; font-weight:bold; padding:4px; "
            f"background:{DARK_CARD}; border-bottom:1px solid {DARK_BORDER};")
        lv.addWidget(hdr)

        self._tbl = QTableWidget(0, 3)
        self._tbl.setHorizontalHeaderLabels(["Symbol","Verdict","Conf"])
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        lv.addWidget(self._tbl)
        layout.addWidget(left)

        right = QWidget()
        rv    = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0)
        rhdr  = QLabel("  Reasoning & Outlook")
        rhdr.setStyleSheet(f"color:{BLUE_HI}; font-weight:bold; padding:4px;")
        rv.addWidget(rhdr)
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setStyleSheet(
            f"background:{DARK_CARD}; color:{TEXT_PRI}; "
            f"border:1px solid {DARK_BORDER}; font-size:12px; "
            f"font-family:'Segoe UI','Arial',sans-serif;")
        rv.addWidget(self._detail)
        layout.addWidget(right, 1)

        self._tbl.clicked.connect(self._show_detail)
        self._data = {}   # symbol → parsed

    def add_analysis(self, symbol: str, raw: str):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"verdict": "PARSE_ERROR", "confidence": 0,
                      "reasoning": raw, "outlook": "—",
                      "exit_signal": False, "exit_reason": ""}
        self._data[symbol] = parsed

        verdict = parsed.get("verdict", "?")
        conf    = str(parsed.get("confidence", "?"))
        vcol    = QColor(VERDICT_COLORS.get(verdict, TEXT_SEC))

        existing = None
        for i in range(self._tbl.rowCount()):
            if self._tbl.item(i,0) and self._tbl.item(i,0).text() == \
                    symbol.replace("_USDT",""):
                existing = i; break

        if existing is None:
            existing = self._tbl.rowCount()
            self._tbl.insertRow(existing)

        sym_item = QTableWidgetItem(symbol.replace("_USDT",""))
        v_item   = QTableWidgetItem(verdict)
        c_item   = QTableWidgetItem(conf)
        v_item.setForeground(vcol); c_item.setForeground(vcol)
        self._tbl.setItem(existing, 0, sym_item)
        self._tbl.setItem(existing, 1, v_item)
        self._tbl.setItem(existing, 2, c_item)

        self._tbl.selectRow(existing)
        self._render_detail(symbol, parsed)

    def _show_detail(self, index):
        row  = index.row()
        item = self._tbl.item(row, 0)
        if item:
            sym = item.text() + "_USDT"
            if sym in self._data:
                self._render_detail(sym, self._data[sym])

    def _render_detail(self, symbol: str, p: dict):
        verdict = p.get("verdict", "?")
        vcol    = VERDICT_COLORS.get(verdict, TEXT_SEC)
        ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        html = f"""<div style='color:{vcol};font-size:13px;font-weight:bold;
            padding:4px 0 2px 0;'>▶ {symbol.replace('_USDT','')} — {verdict}
            &nbsp; Confidence: {p.get('confidence','?')}/10</div>
<div style='color:{TEXT_DIM};font-size:10px;margin-bottom:8px;'>{ts}</div>"""

        if p.get("exit_signal"):
            html += f"""<div style='color:{RED_HI};font-weight:bold;
                padding:6px 10px;background:#2a0a0a;border:1px solid {RED_HI};
                border-radius:3px;margin-bottom:8px;'>
                ⚠ EXIT SIGNAL: {p.get('exit_reason','')}</div>"""

        reasoning = p.get("reasoning","")
        if reasoning:
            html += f"""<div style='color:{BLUE_HI};font-weight:bold;
                margin-bottom:4px;'>⚙ Reasoning</div>
<div style='color:{TEXT_PRI};line-height:1.65;white-space:pre-wrap;
    background:{DARK_BG};padding:10px 12px;
    border-left:3px solid {BLUE_HI};border-radius:0 4px 4px 0;
    font-size:12px;'>{reasoning}</div>"""

        outlook = p.get("outlook","")
        if outlook:
            html += f"""<div style='color:{AMBER_HI};font-weight:bold;
                margin-top:12px;margin-bottom:4px;'>📈 Outlook</div>
<div style='color:{TEXT_PRI};line-height:1.65;font-style:italic;
    padding:6px 12px;border-left:3px solid {AMBER_HI};
    font-size:12px;'>{outlook}</div>"""

        self._detail.setHtml(html)

# ─── SIGNAL TABLE (left panel) ───────────────────────────────────────────────

class SignalTable(QWidget):
    """Compact table showing current EMA30 signal per asset."""
    symbol_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        hdr = QLabel("  EMA30 Signals")
        hdr.setStyleSheet(
            f"color:{BLUE_HI}; font-weight:bold; font-size:11px; "
            f"padding:4px; background:{DARK_CARD}; "
            f"border-bottom:1px solid {DARK_BORDER};")
        layout.addWidget(hdr)
        self._tbl = QTableWidget(len(TOP_ASSETS), 3)
        self._tbl.setHorizontalHeaderLabels(["Symbol","Dir","Dist%"])
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setShowGrid(False)
        for r, sym in enumerate(TOP_ASSETS):
            self._tbl.setItem(r, 0, QTableWidgetItem(sym.replace("_USDT","")))
            self._tbl.setItem(r, 1, QTableWidgetItem("—"))
            self._tbl.setItem(r, 2, QTableWidgetItem("—"))
        layout.addWidget(self._tbl)
        self._tbl.cellClicked.connect(
            lambda r, _: self.symbol_clicked.emit(TOP_ASSETS[r]))

    def update(self, symbol: str, result: dict):
        r = TOP_ASSETS.index(symbol) if symbol in TOP_ASSETS else -1
        if r < 0: return
        dirn = result.get("direction", "?")
        dist = result.get("distance_pct", 0)
        col  = QColor(GREEN_HI if dirn == "LONG"
                      else RED_HI if dirn == "SHORT" else TEXT_DIM)
        v_item = QTableWidgetItem(dirn)
        v_item.setForeground(col)
        d_item = QTableWidgetItem(f"{dist:+.2f}%")
        d_item.setForeground(col)
        self._tbl.setItem(r, 1, v_item)
        self._tbl.setItem(r, 2, d_item)

# ─── LIVE SETTINGS SIDEBAR ───────────────────────────────────────────────────

class LiveSettingsSidebar(QWidget):
    settings_changed = pyqtSignal()

    def __init__(self, settings_panel: SettingsPanel, parent=None):
        super().__init__(parent)
        self._sp = settings_panel
        self.setMinimumWidth(200); self.setMaximumWidth(230)
        self.setStyleSheet(f"background:{DARK_PANEL};")
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)

        hdr = QLabel(" ⚙  Live Settings")
        hdr.setStyleSheet(
            f"background:{DARK_CARD}; color:{BLUE_HI}; font-weight:bold; "
            f"font-size:11px; padding:6px 8px; border-bottom:1px solid {DARK_BORDER};")
        outer.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); scroll.setWidget(inner); outer.addWidget(scroll)

        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6,6,6,6); lay.setSpacing(8)

        def lbl(txt):
            l = QLabel(txt)
            l.setStyleSheet(f"color:{TEXT_SEC}; font-size:10px;")
            return l

        lay.addWidget(lbl("Margin (USDT)"))
        self._mrg = QComboBox(); self._mrg.setEditable(True)
        for v in MARGIN_OPTIONS: self._mrg.addItem(str(v))
        self._mrg.setCurrentText(self._sp.cbo_margin.currentText())
        lay.addWidget(self._mrg)

        lay.addWidget(lbl("Leverage"))
        self._lev = QComboBox()
        for v in LEVERAGE_OPTIONS: self._lev.addItem(str(v), v)
        self._lev.setCurrentText(self._sp.cbo_leverage.currentText())
        lay.addWidget(self._lev)

        lay.addWidget(lbl("Stop Loss %"))
        self._sl = QDoubleSpinBox()
        self._sl.setRange(0.5, 20); self._sl.setSingleStep(0.5)
        self._sl.setValue(self._sp.spn_sl.value())
        lay.addWidget(self._sl)

        lay.addStretch()
        btn = QPushButton("⚡ Apply")
        btn.setStyleSheet(
            f"background:#0a3d1f; border:1px solid {GREEN_HI}; "
            f"color:{GREEN_HI}; font-weight:bold; padding:5px; border-radius:3px;")
        btn.clicked.connect(self._apply)
        outer.addWidget(btn)

        self._sp.settings_changed.connect(self._pull)

    def _apply(self):
        self._sp.cbo_margin.setCurrentText(self._mrg.currentText())
        self._sp.cbo_leverage.setCurrentText(self._lev.currentText())
        self._sp.spn_sl.setValue(self._sl.value())
        self._sp._save()
        self.settings_changed.emit()

    def _pull(self):
        self._mrg.blockSignals(True)
        self._mrg.setCurrentText(self._sp.cbo_margin.currentText())
        self._mrg.blockSignals(False)
        self._lev.blockSignals(True)
        self._lev.setCurrentText(self._sp.cbo_leverage.currentText())
        self._lev.blockSignals(False)
        self._sl.blockSignals(True)
        self._sl.setValue(self._sp.spn_sl.value())
        self._sl.blockSignals(False)

# ─── MAIN WINDOW ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VER}")
        self.resize(1600, 960)
        self.setStyleSheet(STYLE_SHEET)

        # State
        self._bot_running   = False
        self._paper_mode    = True
        self._ws_connected  = False
        self._cur_prices    = {}
        self._candle_cache  = {}
        self._scan_results  = {}   # symbol → {direction, ema_val, distance_pct, …}
        self._paper_trades  = []
        self._live_trades   = []
        self._live_positions = []
        self._live_open_syms = set()
        self._live_balance  = None
        self._live_avail    = None
        self._contract_info = {}
        self._uptime_secs   = 0
        self._ws_mgr        = None

        # Engines
        self._trend_engine  = TrendEngine()
        self._paper_engine  = PaperEngine()
        self._thread_pool   = QThreadPool()
        self._thread_pool.setMaxThreadCount(8)
        self._client        = MexcClient()
        self._live_mgr      = LiveManager(self._client, self._log_risk)
        self._claude        = ClaudeAnalyser("")
        self._claude.analysis_done.connect(self._on_claude_done)

        self._build_ui()
        self._build_timers()

        QTimer.singleShot(150, self._initial_chart_load)
        QTimer.singleShot(300, self._ensure_ws)
        QTimer.singleShot(200, self._load_contract_specs)

    # ─────────────────────────── UI BUILD ────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6,6,6,6); root.setSpacing(6)
        self._build_top_bar(root)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        left = QWidget(); left.setMaximumWidth(300); left.setMinimumWidth(240)
        lv   = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(6)
        self._build_left_panel(lv)
        splitter.addWidget(left)

        self._tabs = QTabWidget()
        splitter.addWidget(self._tabs)
        splitter.setSizes([280, 1300])
        self._build_tabs()

    def _build_top_bar(self, root):
        bar = QWidget(); bar.setFixedHeight(44)
        bar.setStyleSheet(
            f"background:{DARK_PANEL}; border-bottom:1px solid {DARK_BORDER};")
        h = QHBoxLayout(bar); h.setContentsMargins(8,4,8,4); h.setSpacing(16)

        self._lbl_mode = QLabel("● PAPER")
        self._lbl_mode.setStyleSheet(f"color:{AMBER_HI}; font-weight:bold;")
        h.addWidget(self._lbl_mode)

        self._lbl_status = QLabel("● STOPPED")
        self._lbl_status.setStyleSheet(f"color:{TEXT_DIM}; font-weight:bold;")
        h.addWidget(self._lbl_status)

        self._btn_paper = QPushButton("Paper")
        self._btn_paper.setCheckable(True); self._btn_paper.setChecked(True)
        self._btn_paper.clicked.connect(lambda: self._set_mode(True))
        self._btn_live = QPushButton("Live")
        self._btn_live.setCheckable(True)
        self._btn_live.clicked.connect(lambda: self._set_mode(False))
        h.addWidget(self._btn_paper); h.addWidget(self._btn_live)
        h.addStretch()

        self._lbl_bal = QLabel("—")
        self._lbl_bal.setStyleSheet(f"color:{GREEN_HI}; font-weight:bold;")
        h.addWidget(QLabel("Equity:")); h.addWidget(self._lbl_bal)
        self._lbl_avail = QLabel("—")
        self._lbl_avail.setStyleSheet(f"color:{BLUE_HI};")
        h.addWidget(QLabel("Avail:")); h.addWidget(self._lbl_avail)

        self._lbl_ws = QLabel("◉ WS: —")
        self._lbl_ws.setStyleSheet(f"color:{TEXT_DIM};")
        h.addWidget(self._lbl_ws)

        self._lbl_uptime = QLabel("00:00:00")
        self._lbl_uptime.setStyleSheet(f"color:{TEXT_DIM};")
        h.addWidget(QLabel("Up:")); h.addWidget(self._lbl_uptime)

        root.addWidget(bar)

    def _build_left_panel(self, lv):
        # Bot controls
        ctrl = QWidget()
        ch   = QHBoxLayout(ctrl); ch.setContentsMargins(0,0,0,0); ch.setSpacing(6)
        self._btn_start = QPushButton("▶ Start"); self._btn_start.setObjectName("btnStart")
        self._btn_stop  = QPushButton("■ Stop");  self._btn_stop.setObjectName("btnStop")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._start_bot)
        self._btn_stop.clicked.connect(self._stop_bot)
        ch.addWidget(self._btn_start); ch.addWidget(self._btn_stop)
        lv.addWidget(ctrl)

        # Session stats
        stat_grp = QGroupBox("Session")
        sg = QGridLayout(stat_grp); sg.setSpacing(4)

        def stat_pair(label):
            l = QLabel(label); l.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px;")
            v = QLabel("—");   v.setStyleSheet(f"color:{GREEN_HI}; font-weight:bold;")
            return l, v

        ll, self._lbl_paper_bal = stat_pair("Paper Balance")
        sg.addWidget(ll, 0, 0); sg.addWidget(self._lbl_paper_bal, 0, 1)
        ll2, self._lbl_open     = stat_pair("Open Positions")
        sg.addWidget(ll2, 1, 0); sg.addWidget(self._lbl_open, 1, 1)
        ll3, self._lbl_trades   = stat_pair("Closed Trades")
        sg.addWidget(ll3, 2, 0); sg.addWidget(self._lbl_trades, 2, 1)
        ll4, self._lbl_pnl      = stat_pair("Session PnL")
        sg.addWidget(ll4, 3, 0); sg.addWidget(self._lbl_pnl, 3, 1)
        lv.addWidget(stat_grp)

        # Signal table
        self._sig_tbl = SignalTable()
        self._sig_tbl.symbol_clicked.connect(self._open_chart)
        lv.addWidget(self._sig_tbl)
        lv.addStretch()

    def _build_tabs(self):
        self._chart_widgets = {}
        chart_outer   = QWidget()
        chart_outer_h = QHBoxLayout(chart_outer)
        chart_outer_h.setContentsMargins(0,0,0,0); chart_outer_h.setSpacing(0)

        self._settings = SettingsPanel()
        self._settings.settings_changed.connect(self._apply_settings)

        self._live_sidebar = LiveSettingsSidebar(self._settings)
        self._live_sidebar.settings_changed.connect(self._apply_settings)

        asset_tabs = QTabWidget()
        for sym in TOP_ASSETS:
            cw = DailyCandleChart(sym)
            self._chart_widgets[sym] = cw
            asset_tabs.addTab(cw, sym.replace("_USDT",""))
        self._asset_tabs = asset_tabs
        asset_tabs.currentChanged.connect(lambda _: self._refresh_visible_chart())
        chart_outer_h.addWidget(asset_tabs, 1)
        chart_outer_h.addWidget(self._live_sidebar)
        self._tabs.addTab(chart_outer, "Charts")

        # Positions panel
        self._positions_panel = PositionsPanel()
        self._positions_panel.close_requested.connect(self._manual_close)
        self._tabs.addTab(self._positions_panel, "Positions")

        # Trade history
        self._history_tbl = TradeHistoryTable()
        self._tabs.addTab(self._history_tbl, "Trade History")

        # AI analysis
        self._ai_tab = AIAnalysisTab()
        self._tabs.addTab(self._ai_tab, "AI Analysis")

        # Scan log
        self._scan_log = ScanLog()
        self._tabs.addTab(self._scan_log, "Scan Log")

        # Settings
        self._tabs.addTab(self._settings, "Settings")

    # ─────────────────────────── TIMERS ───────────────────────────────────────

    def _build_timers(self):
        self._uptime_timer = QTimer()
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        self._scan_timer = QTimer()
        self._scan_timer.setInterval(SCAN_INTERVAL_MS)
        self._scan_timer.timeout.connect(self._run_scan)

        # UI refresh at 3 Hz
        self._ui_timer = QTimer()
        self._ui_timer.setInterval(333)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()

        # Risk tick 1 Hz (SL checks on paper, position sync on live)
        self._risk_timer = QTimer()
        self._risk_timer.setInterval(1000)
        self._risk_timer.timeout.connect(self._risk_tick)
        self._risk_timer.start()

        # Chart refresh every 60s (daily bars don't change minute-to-minute)
        self._chart_timer = QTimer()
        self._chart_timer.setInterval(60_000)
        self._chart_timer.timeout.connect(self._refresh_visible_chart)
        self._chart_timer.start()

        # Balance poll every 30s
        self._balance_timer = QTimer()
        self._balance_timer.setInterval(30_000)
        self._balance_timer.timeout.connect(self._fetch_live_balance)
        self._balance_timer.start()

    # ─────────────────────────── CONTRACT SPECS ───────────────────────────────

    def _load_contract_specs(self):
        def worker():
            try:
                details = MexcClient().contract_detail()
            except Exception:
                details = []
            info = {}
            for c in details:
                sym = c.get("symbol")
                if not sym: continue
                info[sym] = {
                    "contractSize": float(c.get("contractSize", 0) or 0),
                    "priceScale":   int(c.get("priceScale",   6) or 6),
                    "volScale":     int(c.get("volScale",     0) or 0),
                    "minVol":       float(c.get("minVol", 1) or 1),
                    "maxLeverage":  int(c.get("maxLeverage",  0) or 0),
                }
            self._contract_info = info
            self._scan_log.log(
                f"Loaded specs for {len(info)} contracts." if info
                else "Contract specs unavailable (using fallbacks).",
                BLUE_HI if info else AMBER_HI)
        threading.Thread(target=worker, daemon=True).start()

    def _calc_vol(self, symbol: str, margin: float, lev: int, price: float):
        info = self._contract_info.get(symbol)
        if not info or not price: return None
        cs = info.get("contractSize", 0)
        if not cs: return None
        raw   = (margin * lev) / (cs * price)
        scale = info.get("volScale", 0)
        vol   = round(raw, scale) if scale > 0 else float(int(raw))
        minv  = info.get("minVol", 0)
        if minv and vol < minv: vol = minv
        return vol if vol > 0 else None

    def _round_price(self, symbol: str, price: float) -> float:
        scale = self._contract_info.get(symbol, {}).get("priceScale", 6)
        return round(price, scale)

    @staticmethod
    def _order_ok(r) -> bool:
        return isinstance(r, dict) and r.get("success") is True and not r.get("error")

    @staticmethod
    def _order_err(r) -> str:
        if not isinstance(r, dict): return str(r)
        return str(r.get("message") or r.get("msg") or r.get("error")
                   or f"code={r.get('code')}" or r)

    # ─────────────────────────── CHART LOADING ────────────────────────────────

    def _initial_chart_load(self):
        self._scan_log.log("Loading daily charts…", BLUE_HI)
        for sym in TOP_ASSETS:
            w = ChartWorker(sym, self._client)
            w.signals.done.connect(self._on_chart_data)
            self._thread_pool.start(w)

    def _refresh_visible_chart(self):
        tabs = getattr(self, "_asset_tabs", None)
        if not tabs: return
        w   = tabs.currentWidget()
        sym = getattr(w, "symbol", None)
        if not sym: return
        worker = ChartWorker(sym, self._client)
        worker.signals.done.connect(self._on_chart_data)
        self._thread_pool.start(worker)

    @pyqtSlot(str, list)
    def _on_chart_data(self, symbol: str, candles: list):
        cw = self._chart_widgets.get(symbol)
        if cw and candles:
            cw.update_candles(candles)
            cw.set_levels(self._chart_levels(symbol))

    def _chart_levels(self, symbol: str) -> list:
        out = []
        if self._paper_mode:
            for p in self._paper_engine.positions:
                if p["symbol"] == symbol:
                    out.append({"entry": p["entry"], "sl": p["sl"],
                                "direction": p["direction"]})
        else:
            rec = self._live_mgr.state.get(symbol)
            if rec:
                out.append({"entry": rec["entry"], "sl": rec["sl"],
                            "direction": rec["direction"]})
        return out

    def _open_chart(self, symbol: str):
        if symbol not in self._chart_widgets: return
        self._tabs.setCurrentIndex(0)
        try:
            self._asset_tabs.setCurrentIndex(TOP_ASSETS.index(symbol))
        except ValueError:
            pass

    # ─────────────────────────── LIVE BALANCE ─────────────────────────────────

    def _fetch_live_balance(self):
        if self._paper_mode: return
        cfg = self._settings.get_config()
        if not cfg["mexc_key"] or not cfg["mexc_secret"]:
            self._lbl_bal.setText("no keys"); return
        self._client = MexcClient(cfg["mexc_key"], cfg["mexc_secret"])
        self._live_mgr.set_client(self._client)
        w = BalanceWorker(self._client)
        w.signals.done.connect(self._on_balance)
        w.signals.error.connect(self._on_balance_error)
        self._thread_pool.start(w)

    @pyqtSlot(float, float)
    def _on_balance(self, bal: float, avail: float):
        self._live_balance = bal; self._live_avail = avail
        if not self._paper_mode:
            self._lbl_bal.setText(f"${bal:.2f}")
            self._lbl_avail.setText(f"${avail:.2f}")

    @pyqtSlot(str)
    def _on_balance_error(self, msg: str):
        self._scan_log.log(f"Balance fetch: {msg}", RED_HI)
        if not self._paper_mode and self._live_balance is None:
            self._lbl_bal.setText("err")

    # ─────────────────────────── BOT CONTROL ──────────────────────────────────

    def _start_bot(self):
        cfg = self._settings.get_config()
        if not cfg["active_assets"]:
            QMessageBox.warning(self, "No Assets", "Select at least one asset.")
            return
        self._client = MexcClient(cfg["mexc_key"], cfg["mexc_secret"])
        self._live_mgr.set_client(self._client)
        self._claude.set_key(cfg["claude_key"])
        if not self._claude.isRunning():
            self._claude.start()
        self._ensure_ws()
        if self._paper_mode and not self._paper_engine.positions and not self._paper_trades:
            self._paper_engine.balance = PAPER_START_BALANCE
            self._scan_log.log(f"Paper balance reset: ${PAPER_START_BALANCE:.2f}", BLUE_HI)

        self._bot_running  = True
        self._uptime_secs  = 0
        self._uptime_timer.start()
        self._scan_timer.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lbl_status.setText("● RUNNING")
        self._lbl_status.setStyleSheet(f"color:{GREEN_HI}; font-weight:bold;")
        self._scan_log.log("Bot started — EMA30 daily trend mode.", GREEN_HI)
        self._run_scan()

    def _stop_bot(self):
        self._bot_running = False
        self._scan_timer.stop()
        self._uptime_timer.stop()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._lbl_status.setText("● STOPPED")
        self._lbl_status.setStyleSheet(f"color:{RED_HI}; font-weight:bold;")
        self._scan_log.log("Bot stopped.", AMBER_HI)

    def _set_mode(self, paper: bool):
        if paper == self._paper_mode: return
        self._paper_mode = paper
        self._btn_paper.setChecked(paper)
        self._btn_live.setChecked(not paper)
        self._history_tbl.populate(
            self._paper_trades if paper else self._live_trades)
        if paper:
            self._lbl_mode.setText("● PAPER")
            self._lbl_mode.setStyleSheet(f"color:{AMBER_HI}; font-weight:bold;")
        else:
            self._lbl_mode.setText("● LIVE")
            self._lbl_mode.setStyleSheet(f"color:{RED_HI}; font-weight:bold;")
            self._live_balance = None
            self._lbl_bal.setText("…")
            self._fetch_live_balance()

    def _apply_settings(self):
        cfg = self._settings.get_config()
        self._claude.set_key(cfg["claude_key"])
        self._client = MexcClient(cfg["mexc_key"], cfg["mexc_secret"])
        self._live_mgr.set_client(self._client)

    def _tick_uptime(self):
        self._uptime_secs += 1
        h = self._uptime_secs // 3600
        m = (self._uptime_secs % 3600) // 60
        s = self._uptime_secs % 60
        self._lbl_uptime.setText(f"{h:02d}:{m:02d}:{s:02d}")

    # ─────────────────────────── WEBSOCKET ────────────────────────────────────

    def _ensure_ws(self):
        if not HAS_WS:
            self._lbl_ws.setText("◉ WS: N/A")
            self._lbl_ws.setStyleSheet(f"color:{AMBER_HI};")
            return
        if self._ws_mgr and self._ws_mgr.isRunning(): return
        self._ws_mgr = WsManager(list(TOP_ASSETS))
        self._ws_mgr.tick_received.connect(self._on_ws_tick)
        self._ws_mgr.ws_status.connect(self._on_ws_status)
        self._ws_mgr.ws_error.connect(self._on_ws_error)
        self._ws_mgr.start()
        self._scan_log.log("Connecting market-data WebSocket…", BLUE_HI)

    @pyqtSlot(str)
    def _on_ws_error(self, msg: str):
        self._scan_log.log(f"WS: {msg}", RED_HI)

    @pyqtSlot(str, dict)
    def _on_ws_tick(self, symbol: str, data: dict):
        ch = data.get("channel",""); d = data.get("data")
        if "deal" in ch:
            deal = d[-1] if isinstance(d, list) and d else d
            if isinstance(deal, dict):
                price = deal.get("p") or deal.get("price")
                if price:
                    try: self._cur_prices[symbol] = float(price)
                    except: pass

    @pyqtSlot(bool)
    def _on_ws_status(self, connected: bool):
        self._ws_connected = connected
        if connected:
            self._lbl_ws.setText("◉ WS: ON")
            self._lbl_ws.setStyleSheet(f"color:{GREEN_HI};")
        else:
            self._lbl_ws.setText("◉ WS: OFF")
            self._lbl_ws.setStyleSheet(f"color:{RED_HI};")

    # ─────────────────────────── SCAN CYCLE ───────────────────────────────────

    def _run_scan(self):
        if not self._bot_running: return
        cfg = self._settings.get_config()
        self._scan_log.log(
            f"Daily scan — {len(cfg['active_assets'])} assets", BLUE_HI)
        for sym in cfg["active_assets"]:
            w = DailySignalWorker(sym, self._client, self._trend_engine,
                                  self._candle_cache)
            w.signals.done.connect(self._on_scan_done)
            self._thread_pool.start(w)

    @pyqtSlot(str, dict)
    def _on_scan_done(self, symbol: str, result: dict):
        prev   = self._scan_results.get(symbol, {})
        self._scan_results[symbol] = result
        dirn   = result.get("direction", "NONE")
        dist   = result.get("distance_pct", 0)
        price  = result.get("price", 0)
        cfg    = self._settings.get_config()

        # Update live price map from REST when WS isn't feeding
        if price > 0:
            self._cur_prices.setdefault(symbol, price)
            if not self._ws_connected:
                self._cur_prices[symbol] = price

        # Update signal table
        self._sig_tbl.update(symbol, result)

        self._scan_log.log(
            f"{symbol}: EMA30 {dirn}  dist={dist:+.2f}%  price={price:.4f}",
            GREEN_HI if dirn == "LONG"
            else RED_HI if dirn == "SHORT" else TEXT_DIM)

        if not self._bot_running or dirn == "NONE" or price <= 0:
            return

        # ── EMA FLIP EXIT: check if an open position should close ──────────────
        open_syms = self._open_symbols()
        if symbol in open_syms:
            prev_dir = prev.get("direction", "NONE")
            if prev_dir != "NONE" and prev_dir != dirn:
                # Daily EMA crossed — close the position
                self._scan_log.log(
                    f"  ⟳ EMA FLIP {symbol}: {prev_dir} → {dirn}, closing position",
                    AMBER_HI)
                if self._paper_mode:
                    for ev in self._paper_engine.close_ema_flip(symbol, self._cur_prices):
                        self._book_event(ev)
                else:
                    if self._live_mgr.close_ema_flip(symbol, self._cur_prices):
                        self._scan_log.log(f"  ✓ EMA flip close sent {symbol}", GREEN_HI)
            return   # don't re-enter on the same scan that closed

        # ── ENTRY GATE ─────────────────────────────────────────────────────────
        max_pos = cfg.get("max_positions", MAX_OPEN_POSITIONS)
        if len(open_syms) >= max_pos:
            self._scan_log.log(
                f"  ⊘ {symbol}: max positions ({max_pos}) reached — skipped", TEXT_DIM)
            return

        self._execute_trade(symbol, dirn, price, cfg)

    def _open_symbols(self) -> set:
        if self._paper_mode:
            return {p["symbol"] for p in self._paper_engine.positions}
        return set(self._live_open_syms) | set(self._live_mgr.state.keys())

    def _execute_trade(self, symbol: str, direction: str, price: float, cfg: dict):
        margin  = cfg["margin"]
        lev     = min(cfg["leverage"],
                      ASSET_MAX_LEV.get(symbol, 100),
                      self._contract_info.get(symbol, {}).get("maxLeverage", 999) or 999)
        sl_pct  = cfg["sl_pct"]

        if lev < cfg["leverage"]:
            self._scan_log.log(
                f"  ⚡ {symbol}: leverage capped → {lev}×", AMBER_HI)

        vol = self._calc_vol(symbol, margin, lev, price)

        sl_price = self._round_price(
            symbol,
            price * (1 - sl_pct / 100) if direction == "LONG"
            else price * (1 + sl_pct / 100))

        if self._paper_mode:
            fill_offset = price * 0.0005
            fill_price  = (price - fill_offset) if direction == "LONG" \
                          else (price + fill_offset)
            fill_price  = self._round_price(symbol, fill_price)
            pos = self._paper_engine.place(
                symbol, direction, fill_price, margin, lev, sl_pct, vol=vol)
            if pos is None:
                self._scan_log.log(
                    f"  ⊘ {symbol}: insufficient paper balance — skipped", TEXT_DIM)
                return
            trade_id = pos["id"]
        else:
            if vol is None:
                self._scan_log.log(
                    f"  ✗ {symbol}: missing contract spec — skipped", RED_HI)
                return
            if self._live_balance is not None and self._live_balance < margin:
                self._scan_log.log(
                    f"  ⊘ {symbol}: balance ${self._live_balance:.2f} < "
                    f"${margin:.2f} margin — skipped", AMBER_HI)
                return

            side = 1 if direction == "LONG" else 3
            # Limit order just inside mid (maker fee 0.04%)
            off  = max(0.01, min(0.05, 0.3 * 0.05))
            lim  = self._round_price(
                symbol,
                price * (1 - off / 100) if direction == "LONG"
                else price * (1 + off / 100))

            self._client.set_leverage(symbol, lev)
            r = self._client.place_order(
                symbol, side, lim, vol, lev,
                order_type=1, stop_loss=sl_price)
            if not self._order_ok(r):
                self._scan_log.log(
                    f"  ✗ ORDER REJECTED {symbol}: {self._order_err(r)}", RED_HI)
                return

            trade_id   = str(r.get("data", "?"))
            fill_price = lim
            self._live_open_syms.add(symbol)
            self._live_mgr.register(symbol, direction, fill_price, sl_pct, lev)

            # Fill watcher — market fallback after 8s if limit unfilled
            def _watch(oid=trade_id, sym=symbol, s=side, v=vol,
                       l=lev, sl=sl_price, dir_=direction):
                time.sleep(8)
                try:
                    od    = self._client.get_order(oid)
                    state = od.get("data", {}).get("state", -1)
                    if state not in (2,):
                        from urllib.request import Request
                        self._client.cancel_order(oid, sym)
                        self._client.place_order(sym, s, 0, v, l, order_type=5,
                                                 stop_loss=sl)
                        self._scan_log.log(
                            f"  → LIMIT unfilled → MARKET {dir_} {sym}", AMBER_HI)
                except Exception as e:
                    self._scan_log.log(f"  → Fill watcher: {e}", RED_HI)
            threading.Thread(target=_watch, daemon=True).start()

        self._scan_log.log(
            f"ENTRY {direction} {symbol} @ {fill_price:.4f}  "
            f"lev={lev}×  margin=${margin}  SL={sl_pct}%={sl_price:.4f}",
            GREEN_HI)

        # Queue Claude trend analysis
        ctx = {
            "symbol": symbol, "direction": direction,
            "entry_price": fill_price, "leverage": lev,
            "margin": margin, "sl_pct": sl_pct,
            "ema_val": self._scan_results.get(symbol, {}).get("ema_val", 0),
            "distance_pct": self._scan_results.get(symbol, {}).get("distance_pct", 0),
            "candle_count": self._scan_results.get(symbol, {}).get("candle_count", 0),
        }
        self._claude.enqueue(symbol, ctx)

    # ─────────────────────────── RISK LIFECYCLE ───────────────────────────────

    def _log_risk(self, msg: str, color: str = None):
        if getattr(self, "_scan_log", None):
            self._scan_log.log(msg, color or BLUE_HI)

    def _risk_tick(self):
        """1 Hz: check paper SL; sync live positions."""
        if self._paper_mode:
            for ev in self._paper_engine.check_sl(self._cur_prices):
                self._book_event(ev)
        else:
            self._live_poll_ctr = getattr(self, "_live_poll_ctr", 0) + 1
            if self._live_poll_ctr % 2 == 0:
                norm = self._live_mgr.sync(self._cur_prices)
                self._live_positions  = norm
                self._live_open_syms  = set(self._live_mgr.state.keys())

    def _book_event(self, ev: dict):
        if self._paper_mode: self._paper_trades.append(ev)
        else:                self._live_trades.append(ev)
        self._history_tbl.add_trade(ev)
        pnl = ev.get("pnl_usd", 0)
        self._scan_log.log(
            f"CLOSED {ev['symbol']} {ev['direction']} "
            f"reason={ev['reason']}  pnl={fmt_pnl(pnl)}",
            GREEN_HI if pnl >= 0 else RED_HI)

    # ─────────────────────────── UI REFRESH ───────────────────────────────────

    def _refresh_ui(self):
        # Balance labels
        if self._paper_mode:
            self._lbl_bal.setText(f"${self._paper_engine.balance:.2f}")
            self._lbl_avail.setText("—")

        # Stats panel
        trades = self._full_trades()
        self._lbl_trades.setText(str(len(trades)))
        pnl = sum(t.get("pnl_usd", 0) for t in trades)
        self._lbl_pnl.setText(fmt_pnl(pnl))
        self._lbl_pnl.setStyleSheet(
            f"color:{'#22e57e' if pnl >= 0 else '#ff4d68'}; font-weight:bold;")

        positions = (self._paper_engine.positions if self._paper_mode
                     else self._live_positions)
        self._lbl_open.setText(str(len(positions)))

        # Positions panel
        self._positions_panel.update_positions(
            positions, self._cur_prices,
            paper_engine=self._paper_engine if self._paper_mode else None,
            live_mgr=None if self._paper_mode else self._live_mgr)

        # Chart entry/SL lines for visible chart
        tabs = getattr(self, "_asset_tabs", None)
        if tabs:
            w = tabs.currentWidget()
            sym = getattr(w, "symbol", None)
            if sym and isinstance(w, DailyCandleChart):
                w.set_levels(self._chart_levels(sym))

    def _full_trades(self) -> list:
        return self._paper_trades if self._paper_mode else self._live_trades

    # ─────────────────────────── MANUAL OPS ───────────────────────────────────

    @pyqtSlot(str, str)
    def _manual_close(self, pos_id: str, symbol: str):
        price = self._cur_prices.get(symbol, 0)
        if self._paper_mode:
            ev = self._paper_engine.close_manual(pos_id, price)
            if ev:
                self._book_event(ev)
                self._scan_log.log(
                    f"Manual close {symbol} @ {price:.4f}", AMBER_HI)
        else:
            try:
                pos = next((p for p in self._client.get_positions()
                            if str(p.get("positionId","")) == pos_id
                            or p.get("symbol") == symbol), None)
                if pos:
                    direction = "LONG" if pos.get("positionType") == 1 else "SHORT"
                    vol = float(pos.get("holdVol") or 1)
                    r   = self._client.market_close(
                        symbol, direction, int(vol),
                        str(pos.get("positionId","")))
                    ok  = isinstance(r, dict) and (r.get("success") or r.get("code") == 0)
                    self._scan_log.log(
                        f"Manual close {symbol} {direction} vol={int(vol)} "
                        f"{'sent' if ok else 'REJECTED: ' + str(r)}",
                        AMBER_HI if ok else RED_HI)
                    self._live_mgr.state.pop(symbol, None)
                    self._live_open_syms.discard(symbol)
            except Exception as e:
                self._scan_log.log(f"Manual close error: {e}", RED_HI)

    def _manual_hedge(self, pos_id: str, symbol: str, price: float):
        """Open an opposite position at 40% of the original margin."""
        pos = next((p for p in self._paper_engine.positions
                    if p["id"] == pos_id), None)
        if not pos: return
        opp_dir   = "SHORT" if pos["direction"] == "LONG" else "LONG"
        hedge_mgn = pos["margin"] * 0.4
        cfg       = self._settings.get_config()
        if self._paper_mode:
            self._paper_engine.place(symbol, opp_dir, price, hedge_mgn,
                                     pos["leverage"], cfg["sl_pct"])
            self._scan_log.log(
                f"HEDGE {opp_dir} {symbol} @ {price:.4f} margin=${hedge_mgn:.1f}",
                AMBER_HI)

    # ─────────────────────────── CLAUDE CALLBACK ──────────────────────────────

    @pyqtSlot(str, str)
    def _on_claude_done(self, symbol: str, analysis: str):
        self._ai_tab.add_analysis(symbol, analysis)
        try:
            parsed = json.loads(analysis)
        except Exception:
            return
        # If Claude signals an early exit, close the position
        if parsed.get("exit_signal"):
            reason = parsed.get("exit_reason", "Claude early exit")
            self._scan_log.log(
                f"🤖 Claude EXIT {symbol}: {reason}", AMBER_HI)
            price = self._cur_prices.get(symbol, 0)
            if self._paper_mode:
                pos = next((p for p in self._paper_engine.positions
                            if p["symbol"] == symbol), None)
                if pos:
                    ev = self._paper_engine.close_manual(pos["id"], price)
                    if ev: self._book_event(ev)
            else:
                self._live_mgr.close_ema_flip(symbol, self._cur_prices)

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def main():
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass

    pg.setConfigOptions(antialias=False, useOpenGL=False, crashWarning=False)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VER)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
