#!/usr/bin/env python3
"""
MEXC Futures Scalping Bot
Requires: pip install PyQt5 pyqtgraph websocket-client anthropic requests
"""

# ─── STDLIB ──────────────────────────────────────────────────────────────────────────────
import sys, os, json, time, hmac, hashlib, threading, queue, logging
import asyncio, ssl, math, copy, traceback
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import deque

# ─── THIRD PARTY ─────────────────────────────────────────────────────────────────────
try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QTabWidget, QLabel, QPushButton, QLineEdit,
        QComboBox, QCheckBox, QGroupBox, QScrollArea, QFrame,
        QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
        QTextEdit, QSlider, QSpinBox, QDoubleSpinBox, QSizePolicy,
        QMessageBox, QAction, QMenuBar, QStatusBar, QProgressBar,
        QToolButton, QButtonGroup, QRadioButton, QDialog, QFormLayout,
        QDialogButtonBox, QAbstractItemView, QTreeWidget, QTreeWidgetItem
    )
    from PyQt5.QtCore import (
        Qt, QTimer, QThread, pyqtSignal, QMutex, QMutexLocker,
        QSize, QSettings, pyqtSlot, QDateTime, QObject, QRunnable,
        QThreadPool, QRectF
    )
    from PyQt5.QtGui import (
        QFont, QColor, QPalette, QPixmap, QIcon, QPainter, QPen,
        QBrush, QLinearGradient, QFontDatabase, QTextCursor
    )
    import pyqtgraph as pg
    from pyqtgraph import DateAxisItem
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False
    print("ERROR: PyQt5 / pyqtgraph not found.\nRun: pip install PyQt5 pyqtgraph websocket-client anthropic requests")
    sys.exit(1)

try:
    import websocket as ws_lib
    HAS_WS = True
except ImportError:
    HAS_WS = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# ─── CONSTANTS ───────────────────────────────────────────────────────────────────────────
APP_NAME    = "Ascent Terminal"
APP_VER     = "3.0.0"
MEXC_REST   = "https://contract.mexc.com"
MEXC_WS     = "wss://contract.mexc.com/edge"
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".ascent_terminal.json")
LOG_FILE    = os.path.join(os.path.expanduser("~"), "ascent_terminal.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

# ─── DEFAULT CONFIG ───────────────────────────────────────────────────────────────────
DEFAULT_CFG = {
    "api_key":         "",
    "api_secret":      "",
    "symbol":          "BTC_USDT",
    "contract_type":   "perpetual",
    "leverage":        10,
    "order_size_usdt": 50.0,
    "tp_pct":          0.008,
    "sl_pct":          0.004,
    "ema_fast":        9,
    "ema_slow":        21,
    "rsi_period":      14,
    "rsi_oversold":    35,
    "rsi_overbought":  65,
    "bb_period":       20,
    "bb_std":          2.0,
    "vol_multiplier":  1.5,
    "max_open_trades": 1,
    "paper_trade":     True,
    "auto_trade":      False,
    "theme":           "dark",
    "ai_enabled":      False,
    "ai_model":        "claude-opus-4-5",
    "ai_api_key":      "",
    "ws_enabled":      True,
    "refresh_sec":     60,
    "symbols_watchlist": ["BTC_USDT","ETH_USDT","SOL_USDT","XRP_USDT","DOGE_USDT"],
}

# ─── CONFIG I/O ────────────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception as e:
            log.warning(f"Config load error: {e}")
    return cfg

def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        log.error(f"Config save error: {e}")

# ─── MEXC REST API ────────────────────────────────────────────────────────────────────────
class MexcAPI:
    def __init__(self, key: str, secret: str):
        self.key    = key
        self.secret = secret
        self.session_lock = threading.Lock()

    def _sign(self, params: dict) -> dict:
        ts = str(int(time.time() * 1000))
        params["timestamp"] = ts
        query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in sorted(params.items()))
        sig = hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _req(self, method: str, path: str, params: dict = None, signed: bool = False) -> dict:
        params = params or {}
        if signed:
            params = self._sign(params)
        url = MEXC_REST + path
        if method == "GET" and params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        if method != "GET" and params:
            data = json.dumps(params).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.key:
            req.add_header("ApiKey", self.key)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            log.error(f"HTTP {e.code} {path}: {body[:200]}")
            return {"code": e.code, "msg": body[:200]}
        except Exception as e:
            log.error(f"Request error {path}: {e}")
            return {"code": -1, "msg": str(e)}

    # ─── Public endpoints ─────────────────────────────────────────────────────────────
    def get_ticker(self, symbol: str) -> dict:
        return self._req("GET", "/api/v1/contract/ticker", {"symbol": symbol})

    def get_klines(self, symbol: str, interval: str = "Min1", limit: int = 200) -> dict:
        return self._req("GET", "/api/v1/contract/kline/" + symbol,
                         {"interval": interval, "limit": limit})

    def get_depth(self, symbol: str, limit: int = 20) -> dict:
        return self._req("GET", "/api/v1/contract/depth/" + symbol, {"limit": limit})

    def get_contract_detail(self, symbol: str) -> dict:
        return self._req("GET", "/api/v1/contract/detail", {"symbol": symbol})

    def list_contracts(self) -> dict:
        return self._req("GET", "/api/v1/contract/detail")

    # ─── Private endpoints ───────────────────────────────────────────────────────────
    def get_account(self) -> dict:
        return self._req("GET", "/api/v1/private/account/assets", signed=True)

    def get_positions(self) -> dict:
        return self._req("GET", "/api/v1/private/position/open_positions", signed=True)

    def place_order(self, symbol: str, side: int, vol: float,
                    order_type: int = 1, price: float = None,
                    leverage: int = 10, open_type: int = 1) -> dict:
        params = {
            "symbol":    symbol,
            "side":      side,
            "openType":  open_type,
            "type":      order_type,
            "vol":       vol,
            "leverage":  leverage,
        }
        if price:
            params["price"] = price
        return self._req("POST", "/api/v1/private/order/submit", params, signed=True)

    def cancel_order(self, order_id: str) -> dict:
        return self._req("DELETE", "/api/v1/private/order/cancel",
                         {"orderId": order_id}, signed=True)

    def get_open_orders(self, symbol: str) -> dict:
        return self._req("GET", "/api/v1/private/order/list/open_orders/" + symbol, signed=True)

    def set_leverage(self, symbol: str, leverage: int, position_type: int = 1) -> dict:
        return self._req("POST", "/api/v1/private/position/change_leverage",
                         {"symbol": symbol, "leverage": leverage,
                          "openType": position_type}, signed=True)

# ─── TECHNICAL INDICATORS ──────────────────────────────────────────────────────────────────
def ema(prices: list, period: int) -> list:
    if len(prices) < period:
        return [float("nan")] * len(prices)
    result = [float("nan")] * (period - 1)
    sma = sum(prices[:period]) / period
    result.append(sma)
    k = 2 / (period + 1)
    for p in prices[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result

def rsi(prices: list, period: int = 14) -> list:
    if len(prices) < period + 1:
        return [float("nan")] * len(prices)
    result = [float("nan")] * period
    gains, losses = [], []
    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period, len(prices)):
        delta = prices[i] - prices[i - 1]
        g = max(delta, 0)
        lo = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + lo) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))
    return result

def bollinger(prices: list, period: int = 20, std_mult: float = 2.0):
    """Returns (upper, mid, lower)."""
    if len(prices) < period:
        nan = [float("nan")] * len(prices)
        return nan, nan, nan
    uppers, mids, lowers = [], [], []
    for i in range(len(prices)):
        if i < period - 1:
            uppers.append(float("nan"))
            mids.append(float("nan"))
            lowers.append(float("nan"))
        else:
            window = prices[i - period + 1 : i + 1]
            m = sum(window) / period
            variance = sum((x - m) ** 2 for x in window) / period
            sd = math.sqrt(variance)
            uppers.append(m + std_mult * sd)
            mids.append(m)
            lowers.append(m - std_mult * sd)
    return uppers, mids, lowers

def atr(highs, lows, closes, period: int = 14) -> list:
    if len(closes) < 2:
        return [float("nan")] * len(closes)
    trs = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    result = [float("nan")] * (period - 1)
    result.append(sum(trs[:period]) / period)
    k = 1 / period
    for tr in trs[period:]:
        result.append(tr * k + result[-1] * (1 - k))
    return result

# ─── SIGNAL ENGINE ──────────────────────────────────────────────────────────────────────────
class SignalEngine:
    """Stateless signal generator."""

    @staticmethod
    def generate(closes: list, highs: list, lows: list, cfg: dict) -> dict:
        if len(closes) < 50:
            return {"signal": "NONE", "reason": "not enough data"}

        ema_f = ema(closes, cfg["ema_fast"])
        ema_s = ema(closes, cfg["ema_slow"])
        rsi_v = rsi(closes, cfg["rsi_period"])
        bb_u, bb_m, bb_l = bollinger(closes, cfg["bb_period"], cfg["bb_std"])
        atr_v = atr(highs, lows, closes)

        ef, es = ema_f[-1], ema_s[-1]
        ef_p, es_p = ema_f[-2], ema_s[-2]
        rv = rsi_v[-1]
        price = closes[-1]
        vol_ratio = (price - bb_l[-1]) / (bb_u[-1] - bb_l[-1] + 1e-9)

        signal = "NONE"
        reasons = []

        # ─ EMA crossover ─
        cross_up   = ef_p < es_p and ef > es
        cross_down = ef_p > es_p and ef < es

        if cross_up and rv < cfg["rsi_oversold"] + 15 and vol_ratio < 0.4:
            signal = "BUY"
            reasons = [f"EMA cross up", f"RSI={rv:.1f}", f"BB pos={vol_ratio:.2f}"]
        elif cross_down and rv > cfg["rsi_overbought"] - 15 and vol_ratio > 0.6:
            signal = "SELL"
            reasons = [f"EMA cross down", f"RSI={rv:.1f}", f"BB pos={vol_ratio:.2f}"]

        return {
            "signal":    signal,
            "reason":    ", ".join(reasons),
            "ema_fast":  ef,
            "ema_slow":  es,
            "rsi":       rv,
            "bb_upper":  bb_u[-1],
            "bb_mid":    bb_m[-1],
            "bb_lower":  bb_l[-1],
            "atr":       atr_v[-1] if atr_v else float("nan"),
        }

# ─── TRADE MANAGER ─────────────────────────────────────────────────────────────────────────
class TradeManager:
    def __init__(self, api: MexcAPI, cfg: dict):
        self.api = api
        self.cfg = cfg
        self.trades: list  = []   # list of dicts
        self.open_trade     = None
        self._lock          = threading.Lock()

    # ───
    def entry(self, signal: str, price: float, sig_info: dict) -> dict | None:
        with self._lock:
            if self.open_trade:
                return None
            if len([t for t in self.trades if t["status"] == "open"]) >= self.cfg["max_open_trades"]:
                return None

            size_usdt = self.cfg["order_size_usdt"]
            lev       = self.cfg["leverage"]
            tp_pct    = self.cfg["tp_pct"]
            sl_pct    = self.cfg["sl_pct"]

            if signal == "BUY":
                tp = price * (1 + tp_pct)
                sl = price * (1 - sl_pct)
                side = 1
            else:
                tp = price * (1 - tp_pct)
                sl = price * (1 + sl_pct)
                side = 3

            vol = round(size_usdt * lev / price, 4)

            trade = {
                "id":       len(self.trades) + 1,
                "symbol":   self.cfg["symbol"],
                "side":     signal,
                "entry":    price,
                "tp":       tp,
                "sl":       sl,
                "vol":      vol,
                "status":   "open",
                "open_ts":  time.time(),
                "close_ts": None,
                "pnl":      0.0,
                "paper":    self.cfg["paper_trade"],
                "order_id": None,
            }

            if not self.cfg["paper_trade"]:
                resp = self.api.place_order(
                    self.cfg["symbol"], side, vol, leverage=lev
                )
                trade["order_id"] = resp.get("data")
                if not trade["order_id"]:
                    log.error(f"Order rejected: {resp}")
                    return None

            self.trades.append(trade)
            self.open_trade = trade
            log.info(f"{'[PAPER] ' if trade['paper'] else ''}OPEN {signal} @ {price:.4f}  TP={tp:.4f}  SL={sl:.4f}")
            return trade

    def update(self, current_price: float) -> dict | None:
        """Check TP/SL on open trade.  Returns closed trade or None."""
        with self._lock:
            if not self.open_trade:
                return None
            t = self.open_trade
            hit = None
            if t["side"] == "BUY":
                if current_price >= t["tp"]:
                    hit = "TP"
                elif current_price <= t["sl"]:
                    hit = "SL"
            else:
                if current_price <= t["tp"]:
                    hit = "TP"
                elif current_price >= t["sl"]:
                    hit = "SL"

            if hit:
                close_price = t["tp"] if hit == "TP" else t["sl"]
                if t["side"] == "BUY":
                    t["pnl"] = (close_price - t["entry"]) / t["entry"] * t["vol"] * t["entry"]
                else:
                    t["pnl"] = (t["entry"] - close_price) / t["entry"] * t["vol"] * t["entry"]
                t["status"]   = "closed"
                t["close_ts"] = time.time()
                self.open_trade = None
                log.info(f"CLOSE {t['side']} hit {hit} @ {close_price:.4f}  PnL={t['pnl']:.2f}")
                return t
            return None

    def stats(self) -> dict:
        closed = [t for t in self.trades if t["status"] == "closed"]
        if not closed:
            return {"trades": 0, "win_rate": 0, "total_pnl": 0, "avg_pnl": 0}
        wins = [t for t in closed if t["pnl"] > 0]
        return {
            "trades":    len(closed),
            "win_rate":  len(wins) / len(closed) * 100,
            "total_pnl": sum(t["pnl"] for t in closed),
            "avg_pnl":   sum(t["pnl"] for t in closed) / len(closed),
        }

# ─── AI ASSISTANT ───────────────────────────────────────────────────────────────────────────
class AIAssistant:
    def __init__(self, api_key: str, model: str = "claude-opus-4-5"):
        self.model  = model
        self._client = None
        if HAS_ANTHROPIC and api_key:
            try:
                self._client = anthropic.Anthropic(api_key=api_key)
            except Exception as e:
                log.warning(f"AI init error: {e}")

    def ask(self, prompt: str, context: str = "") -> str:
        if not self._client:
            return "AI not available (install anthropic + set API key)"
        try:
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                messages=[{"role": "user", "content": f"{context}\n\n{prompt}".strip()}]
            )
            return msg.content[0].text
        except Exception as e:
            return f"AI error: {e}"

    def analyse_market(self, sig: dict, stats: dict) -> str:
        context = (
            f"Signal: {sig.get('signal')}  Reason: {sig.get('reason')}\n"
            f"EMA fast={sig.get('ema_fast'):.4f}  slow={sig.get('ema_slow'):.4f}\n"
            f"RSI={sig.get('rsi'):.1f}  BB upper={sig.get('bb_upper'):.4f}  lower={sig.get('bb_lower'):.4f}\n"
            f"Recent trade stats: {stats}\n"
        )
        return self.ask("Briefly analyse this MEXC futures scalping signal and give a risk rating 1-10.", context)

# ─── WEB-SOCKET FEED ────────────────────────────────────────────────────────────────────────
class WsFeed(QThread):
    tick = pyqtSignal(dict)   # emits {symbol, price, vol24h, change24h}

    def __init__(self, symbols: list, parent=None):
        super().__init__(parent)
        self.symbols  = symbols
        self._running = True
        self._ws      = None

    def run(self):
        if not HAS_WS:
            log.warning("websocket-client not installed; WS feed disabled.")
            return
        while self._running:
            try:
                self._ws = ws_lib.WebSocketApp(
                    MEXC_WS,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            except Exception as e:
                log.error(f"WS error: {e}")
            if self._running:
                time.sleep(5)

    def _on_open(self, ws):
        for sym in self.symbols:
            ws.send(json.dumps({"method": "sub.ticker", "param": {"symbol": sym}}))

    def _on_message(self, ws, raw):
        try:
            d = json.loads(raw)
            if d.get("channel") == "push.ticker":
                data = d.get("data", {})
                self.tick.emit({
                    "symbol":   data.get("symbol", ""),
                    "price":    float(data.get("lastPrice", 0)),
                    "vol24h":   float(data.get("volume24", 0)),
                    "change24h":float(data.get("riseFallRate", 0)) * 100,
                })
        except Exception:
            pass

    def _on_error(self, ws, err):
        log.debug(f"WS error: {err}")

    def _on_close(self, ws, *_):
        log.debug("WS closed")

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()

# ─── DATA WORKER (fetches klines + signals in background thread) ───────────────────────────
class DataWorker(QThread):
    result = pyqtSignal(dict)
    error  = pyqtSignal(str)

    def __init__(self, api: MexcAPI, cfg: dict, parent=None):
        super().__init__(parent)
        self.api = api
        self.cfg = cfg

    def run(self):
        try:
            sym = self.cfg["symbol"]
            kl  = self.api.get_klines(sym, "Min1", 200)
            if not kl.get("data"):
                self.error.emit(f"No kline data for {sym}")
                return
            data = kl["data"]
            closes = [float(c[4]) for c in data]
            highs  = [float(c[2]) for c in data]
            lows   = [float(c[3]) for c in data]
            times  = [int(c[0]) // 1000 for c in data]

            sig = SignalEngine.generate(closes, highs, lows, self.cfg)

            tick  = self.api.get_ticker(sym)
            price = float(tick.get("data", {}).get("lastPrice", closes[-1]))

            self.result.emit({
                "closes": closes,
                "highs":  highs,
                "lows":   lows,
                "times":  times,
                "signal": sig,
                "price":  price,
            })
        except Exception as e:
            self.error.emit(str(e))

# ─── COLOUR THEME ────────────────────────────────────────────────────────────────────────────
THEME = {
    "dark": {
        "bg":        "#0d1117",
        "panel":     "#161b22",
        "border":    "#30363d",
        "text":      "#c9d1d9",
        "accent":    "#58a6ff",
        "green":     "#3fb950",
        "red":       "#f85149",
        "yellow":    "#d29922",
        "muted":     "#8b949e",
        "chart_bg":  "#0d1117",
        "grid":      "#21262d",
    },
    "light": {
        "bg":        "#ffffff",
        "panel":     "#f6f8fa",
        "border":    "#d0d7de",
        "text":      "#24292f",
        "accent":    "#0969da",
        "green":     "#1a7f37",
        "red":       "#cf222e",
        "yellow":    "#9a6700",
        "muted":     "#57606a",
        "chart_bg":  "#ffffff",
        "grid":      "#eaeef2",
    },
}

def apply_theme(app: QApplication, name: str = "dark"):
    t = THEME.get(name, THEME["dark"])
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(t["bg"]))
    pal.setColor(QPalette.WindowText,      QColor(t["text"]))
    pal.setColor(QPalette.Base,            QColor(t["panel"]))
    pal.setColor(QPalette.AlternateBase,   QColor(t["bg"]))
    pal.setColor(QPalette.ToolTipBase,     QColor(t["panel"]))
    pal.setColor(QPalette.ToolTipText,     QColor(t["text"]))
    pal.setColor(QPalette.Text,            QColor(t["text"]))
    pal.setColor(QPalette.Button,          QColor(t["panel"]))
    pal.setColor(QPalette.ButtonText,      QColor(t["text"]))
    pal.setColor(QPalette.Link,            QColor(t["accent"]))
    pal.setColor(QPalette.Highlight,       QColor(t["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(t["bg"]))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QMainWindow, QWidget {{ background:{t['bg']}; color:{t['text']}; }}
        QGroupBox {{ border:1px solid {t['border']}; border-radius:6px;
                    margin-top:6px; padding:8px; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:8px;
                            color:{t['accent']}; font-weight:bold; }}
        QPushButton {{ background:{t['panel']}; color:{t['text']};
                       border:1px solid {t['border']}; border-radius:4px;
                       padding:4px 12px; }}
        QPushButton:hover {{ border-color:{t['accent']}; color:{t['accent']}; }}
        QPushButton:pressed {{ background:{t['bg']}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background:{t['panel']}; color:{t['text']};
            border:1px solid {t['border']}; border-radius:4px; padding:3px 6px; }}
        QTableWidget {{ background:{t['panel']}; color:{t['text']};
                        gridline-color:{t['border']}; }}
        QHeaderView::section {{ background:{t['bg']}; color:{t['muted']};
                                border:none; padding:4px; }}
        QTabWidget::pane {{ border:1px solid {t['border']}; }}
        QTabBar::tab {{ background:{t['panel']}; color:{t['muted']};
                        border:1px solid {t['border']}; padding:6px 16px;
                        border-bottom:none; }}
        QTabBar::tab:selected {{ color:{t['accent']}; border-bottom:2px solid {t['accent']}; }}
        QScrollBar:vertical {{ background:{t['panel']}; width:8px; }}
        QScrollBar::handle:vertical {{ background:{t['border']}; border-radius:4px; }}
        QTextEdit {{ background:{t['panel']}; color:{t['text']};
                     border:1px solid {t['border']}; border-radius:4px; }}
        QLabel#price_label {{ font-size:28px; font-weight:bold; }}
        QLabel#signal_label {{ font-size:16px; font-weight:bold; }}
    """)
    return t

# ─── STAT CARD ──────────────────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, title: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self._title = QLabel(title)
        self._title.setObjectName("card_title")
        self._value = QLabel(value)
        self._value.setObjectName("card_value")
        self._value.setFont(QFont("Consolas", 13, QFont.Bold))
        lay.addWidget(self._title)
        lay.addWidget(self._value)

    def set_value(self, v: str, color: str = None):
        self._value.setText(v)
        if color:
            self._value.setStyleSheet(f"color:{color};")

# ─── CHART WIDGET ─────────────────────────────────────────────────────────────────────────
class ChartWidget(QWidget):
    def __init__(self, t: dict, parent=None):
        super().__init__(parent)
        self.t = t
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.pw = pg.GraphicsLayoutWidget(background=t["chart_bg"])
        lay.addWidget(self.pw)

        self._price_plot = self.pw.addPlot(row=0, col=0)
        self._rsi_plot   = self.pw.addPlot(row=1, col=0)
        self.pw.ci.layout.setRowStretchFactor(0, 3)
        self.pw.ci.layout.setRowStretchFactor(1, 1)

        for p in (self._price_plot, self._rsi_plot):
            p.showGrid(x=True, y=True, alpha=0.3)
            p.getAxis("bottom").setStyle(tickTextOffset=4)

        self._price_plot.setLabel("left", "Price")
        self._rsi_plot.setLabel("left", "RSI")
        self._rsi_plot.setXLink(self._price_plot)
        self._rsi_plot.addLine(y=70, pen=pg.mkPen(t["red"],   width=1, style=Qt.DashLine))
        self._rsi_plot.addLine(y=30, pen=pg.mkPen(t["green"], width=1, style=Qt.DashLine))

    def update_data(self, closes, highs, lows, times, sig: dict, t: dict):
        self._price_plot.clear()
        self._rsi_plot.clear()

        xs = list(range(len(closes)))
        self._price_plot.plot(xs, closes, pen=pg.mkPen(t["accent"], width=2))

        cfg_tmp = dict(DEFAULT_CFG)
        ema_f = ema(closes, cfg_tmp["ema_fast"])
        ema_s = ema(closes, cfg_tmp["ema_slow"])
        valid = [(x, e) for x, e in zip(xs, ema_f) if not math.isnan(e)]
        if valid:
            vx, vy = zip(*valid)
            self._price_plot.plot(list(vx), list(vy),
                                  pen=pg.mkPen(t["yellow"], width=1))
        valid = [(x, e) for x, e in zip(xs, ema_s) if not math.isnan(e)]
        if valid:
            vx, vy = zip(*valid)
            self._price_plot.plot(list(vx), list(vy),
                                  pen=pg.mkPen(t["muted"], width=1))

        rsi_v = rsi(closes, cfg_tmp["rsi_period"])
        valid = [(x, r) for x, r in zip(xs, rsi_v) if not math.isnan(r)]
        if valid:
            vx, vy = zip(*valid)
            self._rsi_plot.addLine(y=70, pen=pg.mkPen(t["red"],   width=1, style=Qt.DashLine))
            self._rsi_plot.addLine(y=30, pen=pg.mkPen(t["green"], width=1, style=Qt.DashLine))
            self._rsi_plot.plot(list(vx), list(vy),
                                pen=pg.mkPen(t["accent"], width=2))

# ─── SETTINGS DIALOG ───────────────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._cfg = dict(cfg)
        self._fields = {}
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)

        def add(label, key, widget):
            self._fields[key] = widget
            form.addRow(label, widget)

        # ─ API ─
        w = QLineEdit(self._cfg["api_key"]); w.setEchoMode(QLineEdit.Password)
        add("MEXC API Key", "api_key", w)
        w = QLineEdit(self._cfg["api_secret"]); w.setEchoMode(QLineEdit.Password)
        add("MEXC API Secret", "api_secret", w)

        # ─ Symbol ─
        w = QLineEdit(self._cfg["symbol"])
        add("Symbol", "symbol", w)

        # ─ Trading ─
        w = QSpinBox(); w.setRange(1, 125); w.setValue(self._cfg["leverage"])
        add("Leverage", "leverage", w)
        w = QDoubleSpinBox(); w.setRange(1, 100000); w.setValue(self._cfg["order_size_usdt"])
        add("Order Size (USDT)", "order_size_usdt", w)
        w = QDoubleSpinBox(); w.setRange(0.001, 0.5); w.setDecimals(3); w.setSingleStep(0.001)
        w.setValue(self._cfg["tp_pct"])
        add("Take Profit %", "tp_pct", w)
        w = QDoubleSpinBox(); w.setRange(0.001, 0.5); w.setDecimals(3); w.setSingleStep(0.001)
        w.setValue(self._cfg["sl_pct"])
        add("Stop Loss %", "sl_pct", w)

        # ─ Indicators ─
        w = QSpinBox(); w.setRange(2, 50); w.setValue(self._cfg["ema_fast"])
        add("EMA Fast", "ema_fast", w)
        w = QSpinBox(); w.setRange(5, 200); w.setValue(self._cfg["ema_slow"])
        add("EMA Slow", "ema_slow", w)
        w = QSpinBox(); w.setRange(2, 50); w.setValue(self._cfg["rsi_period"])
        add("RSI Period", "rsi_period", w)
        w = QSpinBox(); w.setRange(10, 40); w.setValue(self._cfg["rsi_oversold"])
        add("RSI Oversold", "rsi_oversold", w)
        w = QSpinBox(); w.setRange(60, 90); w.setValue(self._cfg["rsi_overbought"])
        add("RSI Overbought", "rsi_overbought", w)

        # ─ Behaviour ─
        w = QCheckBox(); w.setChecked(self._cfg["paper_trade"])
        add("Paper Trade", "paper_trade", w)
        w = QCheckBox(); w.setChecked(self._cfg["auto_trade"])
        add("Auto Trade", "auto_trade", w)
        w = QComboBox(); w.addItems(["dark", "light"]); w.setCurrentText(self._cfg["theme"])
        add("Theme", "theme", w)
        w = QSpinBox(); w.setRange(10, 300); w.setValue(self._cfg["refresh_sec"])
        add("Refresh (sec)", "refresh_sec", w)

        # ─ AI ─
        w = QCheckBox(); w.setChecked(self._cfg["ai_enabled"])
        add("AI Enabled", "ai_enabled", w)
        w = QLineEdit(self._cfg["ai_api_key"]); w.setEchoMode(QLineEdit.Password)
        add("Claude API Key", "ai_api_key", w)
        w = QComboBox()
        w.addItems(["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"])
        w.setCurrentText(self._cfg["ai_model"])
        add("AI Model", "ai_model", w)

        btn = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn.accepted.connect(self._accept)
        btn.rejected.connect(self.reject)
        lay.addWidget(btn)

    def _accept(self):
        for key, w in self._fields.items():
            if isinstance(w, QCheckBox):
                self._cfg[key] = w.isChecked()
            elif isinstance(w, QComboBox):
                self._cfg[key] = w.currentText()
            elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
                self._cfg[key] = w.value()
            else:
                self._cfg[key] = w.text()
        self.accept()

    def result_cfg(self) -> dict:
        return self._cfg

# ─── TRADES TABLE ───────────────────────────────────────────────────────────────────────────
class TradesTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self._tbl = QTableWidget(0, 8)
        self._tbl.setHorizontalHeaderLabels(
            ["#", "Symbol", "Side", "Entry", "TP", "SL", "Status", "PnL"]
        )
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self._tbl)

    def refresh(self, trades: list):
        self._tbl.setRowCount(len(trades))
        for r, t in enumerate(trades):
            vals = [
                str(t["id"]), t["symbol"], t["side"],
                f"{t['entry']:.4f}", f"{t['tp']:.4f}", f"{t['sl']:.4f}",
                t["status"], f"{t['pnl']:.2f}"
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignCenter)
                if c == 7:   # PnL
                    pnl = t["pnl"]
                    item.setForeground(QColor("#3fb950" if pnl >= 0 else "#f85149"))
                self._tbl.setItem(r, c, item)

# ─── MAIN WINDOW ──────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg     = load_config()
        self.api     = MexcAPI(self.cfg["api_key"], self.cfg["api_secret"])
        self.trader  = TradeManager(self.api, self.cfg)
        self.ai      = AIAssistant(self.cfg["ai_api_key"], self.cfg["ai_model"]) \
                       if self.cfg["ai_enabled"] else None
        self._t      = apply_theme(QApplication.instance(), self.cfg.get("theme", "dark"))
        self._worker = None
        self._ws     = None
        self._last_data = {}
        self._setup_ui()
        self._start_feeds()
        self._refresh()

    # ─── UI ──────────────────────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VER}")
        self.resize(1400, 900)
        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ─ top bar ─
        top = QHBoxLayout()
        root.addLayout(top)

        lbl = QLabel(APP_NAME)
        lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        lbl.setStyleSheet(f"color:{self._t['accent']};")
        top.addWidget(lbl)
        top.addStretch()

        self._sym_combo = QComboBox()
        self._sym_combo.addItems(self.cfg["symbols_watchlist"])
        self._sym_combo.setCurrentText(self.cfg["symbol"])
        self._sym_combo.currentTextChanged.connect(self._on_symbol_change)
        top.addWidget(QLabel("Symbol:"))
        top.addWidget(self._sym_combo)

        self._paper_lbl = QLabel()
        self._paper_lbl.setFont(QFont("Consolas", 11, QFont.Bold))
        top.addWidget(self._paper_lbl)
        self._update_paper_label()

        btn_settings = QPushButton("⚙ Settings")
        btn_settings.clicked.connect(self._open_settings)
        top.addWidget(btn_settings)

        btn_refresh = QPushButton("↺ Refresh")
        btn_refresh.clicked.connect(self._refresh)
        top.addWidget(btn_refresh)

        # ─ stat cards row ─
        cards_row = QHBoxLayout()
        root.addLayout(cards_row)
        self._card_price  = StatCard("Last Price")
        self._card_change = StatCard("24h Change")
        self._card_vol    = StatCard("24h Volume")
        self._card_signal = StatCard("Signal")
        self._card_rsi    = StatCard("RSI")
        self._card_ema    = StatCard("EMA Fast / Slow")
        self._card_pnl    = StatCard("Total PnL")
        self._card_wr     = StatCard("Win Rate")
        for c in (self._card_price, self._card_change, self._card_vol,
                  self._card_signal, self._card_rsi, self._card_ema,
                  self._card_pnl, self._card_wr):
            cards_row.addWidget(c)

        # ─ tabs ─
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        # Tab 1: chart
        self._chart = ChartWidget(self._t)
        self._tabs.addTab(self._chart, "Chart")

        # Tab 2: trades
        self._trades_tbl = TradesTable()
        self._tabs.addTab(self._trades_tbl, "Trades")

        # Tab 3: AI
        ai_w = QWidget()
        ai_lay = QVBoxLayout(ai_w)
        self._ai_prompt = QTextEdit()
        self._ai_prompt.setPlaceholderText("Ask the AI assistant anything about the market...")
        self._ai_prompt.setMaximumHeight(80)
        ai_btn = QPushButton("Ask AI")
        ai_btn.clicked.connect(self._ask_ai)
        self._ai_output = QTextEdit()
        self._ai_output.setReadOnly(True)
        ai_lay.addWidget(QLabel("Prompt:"))
        ai_lay.addWidget(self._ai_prompt)
        ai_lay.addWidget(ai_btn)
        ai_lay.addWidget(QLabel("Response:"))
        ai_lay.addWidget(self._ai_output)
        self._tabs.addTab(ai_w, "AI Assistant")

        # Tab 4: log
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 9))
        self._tabs.addTab(self._log_view, "Log")

        # ─ status bar ─
        self._status = self.statusBar()
        self._status.showMessage("Ready")

        # ─ menu ─
        mb = self.menuBar()
        fm = mb.addMenu("File")
        fm.addAction("Settings", self._open_settings)
        fm.addSeparator()
        fm.addAction("Exit", self.close)
        tm = mb.addMenu("Trade")
        tm.addAction("Force Buy",  lambda: self._manual_trade("BUY"))
        tm.addAction("Force Sell", lambda: self._manual_trade("SELL"))

        # ─ auto-refresh timer ─
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(self.cfg["refresh_sec"] * 1000)

    # ─── feeds ────────────────────────────────────────────────────────────────────────────────────
    def _start_feeds(self):
        if self.cfg.get("ws_enabled") and HAS_WS:
            self._ws = WsFeed(self.cfg["symbols_watchlist"])
            self._ws.tick.connect(self._on_ws_tick)
            self._ws.start()

    def _on_ws_tick(self, d: dict):
        if d["symbol"] == self.cfg["symbol"]:
            self._card_price.set_value(f"{d['price']:.4f}")
            c = d["change24h"]
            color = "#3fb950" if c >= 0 else "#f85149"
            self._card_change.set_value(f"{c:+.2f}%", color)
            self._card_vol.set_value(f"{d['vol24h']:,.0f}")

    # ─── data refresh ─────────────────────────────────────────────────────────────────────────
    def _refresh(self):
        if self._worker and self._worker.isRunning():
            return
        self._worker = DataWorker(self.api, self.cfg)
        self._worker.result.connect(self._on_data)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._status.showMessage("Fetching data...")

    def _on_data(self, data: dict):
        self._last_data = data
        closes  = data["closes"]
        sig     = data["signal"]
        price   = data["price"]

        # update cards
        self._card_price.set_value(f"{price:.4f}")
        s = sig["signal"]
        color = {"BUY": "#3fb950", "SELL": "#f85149"}.get(s, "#8b949e")
        self._card_signal.set_value(s, color)
        rv = sig.get("rsi", float("nan"))
        if not math.isnan(rv):
            c = "#3fb950" if rv < 40 else "#f85149" if rv > 60 else "#c9d1d9"
            self._card_rsi.set_value(f"{rv:.1f}", c)
        ef = sig.get("ema_fast", float("nan"))
        es = sig.get("ema_slow", float("nan"))
        if not math.isnan(ef):
            self._card_ema.set_value(f"{ef:.2f} / {es:.2f}")

        # trade manager update
        closed = self.trader.update(price)
        if closed:
            self._log(f"Trade closed: {closed['side']} PnL={closed['pnl']:.2f}")

        stats = self.trader.stats()
        pnl = stats["total_pnl"]
        self._card_pnl.set_value(f"{pnl:.2f}",
                                  "#3fb950" if pnl >= 0 else "#f85149")
        wr = stats["win_rate"]
        self._card_wr.set_value(f"{wr:.1f}%")

        # auto trade
        if self.cfg.get("auto_trade") and s in ("BUY", "SELL"):
            trade = self.trader.entry(s, price, sig)
            if trade:
                prefix = "[PAPER] " if trade["paper"] else ""
                self._log(f"{prefix}AUTO {s} @ {price:.4f}  reason: {sig.get('reason','')}")

        # chart
        self._chart.update_data(
            closes, data["highs"], data["lows"], data["times"], sig, self._t
        )
        self._trades_tbl.refresh(self.trader.trades)
        self._status.showMessage(
            f"Updated {datetime.now().strftime('%H:%M:%S')}  |  {len(self.trader.trades)} trades"
        )

    def _on_error(self, msg: str):
        self._status.showMessage(f"Error: {msg}")
        self._log(f"ERROR: {msg}")

    # ─── actions ──────────────────────────────────────────────────────────────────────────────────
    def _manual_trade(self, side: str):
        if not self._last_data:
            QMessageBox.warning(self, "No Data", "Please refresh first.")
            return
        price = self._last_data.get("price", 0)
        if not price:
            QMessageBox.warning(self, "No Price", "No price data available.")
            return
        trade = self.trader.entry(side, price, {})
        if trade:
            prefix = "[PAPER] " if trade["paper"] else ""
            self._log(f"{prefix}MANUAL {side} @ {price:.4f}")
        else:
            self._log("Trade rejected (already open or limit reached)")

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec_() == QDialog.Accepted:
            self.cfg = dlg.result_cfg()
            save_config(self.cfg)
            self.api     = MexcAPI(self.cfg["api_key"], self.cfg["api_secret"])
            self.trader  = TradeManager(self.api, self.cfg)
            self.ai      = AIAssistant(self.cfg["ai_api_key"], self.cfg["ai_model"]) \
                           if self.cfg["ai_enabled"] else None
            self._t = apply_theme(QApplication.instance(), self.cfg.get("theme", "dark"))
            self._update_paper_label()
            self._timer.setInterval(self.cfg["refresh_sec"] * 1000)
            self._refresh()

    def _ask_ai(self):
        if not self.ai:
            self._ai_output.setText("AI not configured. Enable in Settings.")
            return
        prompt = self._ai_prompt.toPlainText().strip()
        if not prompt:
            prompt = "Analyse the current market signal."
        sig   = self._last_data.get("signal", {})
        stats = self.trader.stats()
        resp  = self.ai.analyse_market(sig, stats) if not prompt else \
                self.ai.ask(prompt, str(sig))
        self._ai_output.setText(resp)

    def _update_paper_label(self):
        if self.cfg.get("paper_trade"):
            self._paper_lbl.setText("  PAPER  ")
            self._paper_lbl.setStyleSheet(
                "background:#d29922; color:#0d1117; border-radius:4px; padding:2px 8px;"
            )
        else:
            self._paper_lbl.setText("  LIVE  ")
            self._paper_lbl.setStyleSheet(
                "background:#f85149; color:#ffffff; border-radius:4px; padding:2px 8px;"
            )

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_view.append(f"[{ts}] {msg}")
        log.info(msg)

    def _on_symbol_change(self, sym: str):
        self.cfg["symbol"] = sym
        save_config(self.cfg)
        self.trader = TradeManager(self.api, self.cfg)
        self._refresh()

    def closeEvent(self, event):
        if self._ws:
            self._ws.stop()
            self._ws.wait(2000)
        save_config(self.cfg)
        event.accept()

# ─── ADVANCED CONFIG (from apply_advanced_config) ───────────────────────────────────────────────────────────────────────
# (advanced config helpers kept for future use — not wired to MainWindow yet)

def apply_advanced_config(cfg: dict) -> dict:
    """
    Validate and normalise a config dict.
    Fills missing keys from DEFAULT_CFG.
    """
    result = dict(DEFAULT_CFG)
    result.update(cfg)
    # clamp values
    result["leverage"]        = max(1,   min(125,    result["leverage"]))
    result["order_size_usdt"] = max(1.0, min(100000, result["order_size_usdt"]))
    result["tp_pct"]          = max(0.001, min(0.5,  result["tp_pct"]))
    result["sl_pct"]          = max(0.001, min(0.5,  result["sl_pct"]))
    result["rsi_oversold"]    = max(10,  min(45,     result["rsi_oversold"]))
    result["rsi_overbought"]  = max(55,  min(90,     result["rsi_overbought"]))
    return result


# ─── The block below uses apply_advanced_config ────────────────────────────────────────────────────────────────────────────────────────
# apply_advanced_config(cfg) actually receives them (previously the
# SettingsDialog wrote raw widget values).  Now we normalise on save.

_orig_save = save_config
def save_config(cfg: dict):       # type: ignore[misc]
    _orig_save(apply_advanced_config(cfg))

# ─── ENTRY POINT ────────────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VER)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
