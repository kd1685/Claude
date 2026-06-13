#!/usr/bin/env python3
"""
MEXC Futures Scalping Bot
Requires: pip install PyQt5 pyqtgraph websocket-client anthropic requests
"""

# ─── STDLIB ──────────────────────────────────────────────────────────────────
import sys, os, json, time, hmac, hashlib, threading, queue, logging
import asyncio, ssl, math, copy, traceback
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
    import anthropic as anthropic_lib
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# ─── SHARED INDICATOR LIBRARY (platform/indicators.py) ───────────────────────
# The web terminal's 26-indicator toolkit doubles as an optional signal engine
# for the scalper ("Indicator Lab"). We import it from wherever the repo keeps
# it; if it isn't found the bot still runs with the classic 7-signal engine and
# the Indicator Lab option simply doesn't appear.
ind_lib = None
HAS_IND_LIB = False
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    for _cand in (_HERE,
                  os.path.join(os.path.dirname(_HERE), "platform"),
                  os.path.join(_HERE, "platform")):
        if os.path.isfile(os.path.join(_cand, "indicators.py")):
            if _cand not in sys.path:
                sys.path.insert(0, _cand)
            break
    import indicators as ind_lib
    HAS_IND_LIB = hasattr(ind_lib, "compute_panel") and hasattr(ind_lib, "REGISTRY")
except Exception:
    ind_lib = None
    HAS_IND_LIB = False

# Current, non-deprecated analysis model. Override with env CLAUDE_MODEL if you
# want a different one (e.g. a faster/cheaper Haiku). The SDK also honours
# ANTHROPIC_BASE_URL and HTTPS_PROXY env vars if you must route through a proxy.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")

try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

APP_NAME    = "MEXC Scalping Bot"
APP_VER     = "1.0.0"
MEXC_WS     = "wss://contract.mexc.com/edge"
MEXC_REST   = "https://contract.mexc.com"

TOP_ASSETS = [
    "BTC_USDT","ETH_USDT","SOL_USDT","BNB_USDT","XRP_USDT",
    "DOGE_USDT","ADA_USDT","AVAX_USDT","LINK_USDT","DOT_USDT",
    "LTC_USDT","ATOM_USDT","UNI_USDT","NEAR_USDT","APT_USDT"
]

# Exchange hard limits — MEXC does not allow higher leverage than these per asset.
# Your configured leverage is capped to these silently; the scan log will warn you.
ASSET_MAX_LEV = {
    "BTC_USDT":200,"ETH_USDT":200,"SOL_USDT":100,"BNB_USDT":100,
    "XRP_USDT":100,"DOGE_USDT":75,"ADA_USDT":75,"AVAX_USDT":75,
    "LINK_USDT":75,"DOT_USDT":75,"LTC_USDT":75,"ATOM_USDT":50,
    "UNI_USDT":50,"NEAR_USDT":50,"APT_USDT":50
}

LEVERAGE_OPTIONS = [1,2,3,4,5,6,7,8,9,10,15,20,25,30,40,50,
                    60,75,100,150,200,250,300,400,500,1000]

MARGIN_OPTIONS   = [5,10,15,20,25,30,50,75,100,150,200,300,500,750,1000]

SCAN_INTERVAL_MS = 20000   # 20 s

# Fees (from screenshot: maker 0.04%, taker 0.06%)
MAKER_FEE = 0.0004
TAKER_FEE = 0.0006
ROUND_TRIP_FEE = MAKER_FEE + TAKER_FEE   # 0.10%

# ─── RISK MANAGEMENT (scalping) ───────────────────────────────────────────────
# Philosophy: minimise losses, take achievable profits. TP/SL are sized to the
# asset's real volatility (ATR) so targets actually get hit; breakeven + partial
# + trailing protect and bank gains so a ~55% win rate stays profitable.
TP_ATR_MULT   = 1.2    # TP distance ≈ 1.2 × ATR%  (achievable)
SL_ATR_MULT   = 0.8    # SL distance ≈ 0.8 × ATR%  (tight) → R:R ~1.5:1
# Floors must clear the 0.10% round-trip fee with real edge left over. A 0.15%
# TP nets almost nothing after fees and just churns — the floors below give a
# scalp room to actually pay (≈0.30% net on the TP, ≈0.10% fee).
ATR_TP_FLOOR  = 0.45   # min TP % move (≈3× the round-trip fee)
ATR_SL_FLOOR  = 0.30   # min SL % move → keeps R:R ~1.5:1 at the floor
BE_TRIGGER    = 0.5    # at 50% of the way to TP, move SL to breakeven(+fees)
PARTIAL_AT    = 0.6    # at 60% of the way to TP, bank a partial
PARTIAL_SIZE  = 0.5    # close 50% of the position on the partial
TRAIL_AFTER   = 0.6    # begin trailing once 60% of the way to TP (post-breakeven)
TRAIL_ATR_MULT= 0.6    # trail the stop 0.6 × ATR% behind price
# LIVE only: a wider server-side TP/SL is attached at entry as a disaster floor
# that survives app/network death. The bot manages the tighter, real targets
# client-side and always fires first while it's alive.
SAFETY_SL_MULT = 1.2   # server stop-loss sits 1.2× the managed SL: the bot's
                       # tight stop fires first; this is the worst-case floor if
                       # the app dies mid-trade (loss capped near the managed SL)
SAFETY_TP_MULT = 1.5   # server take-profit sits 1.5× beyond the managed TP, so the
                       # bot's trailing stop can run a winner past the base TP

# ─── POSITION / CAPITAL LIMITS ────────────────────────────────────────────────
PAPER_START_BALANCE   = 1000.0   # every fresh paper session starts here
MAX_OPEN_POSITIONS    = 5        # hard cap on concurrent open positions

# ─── ANTI-CHASE ENTRY FILTER ──────────────────────────────────────────────────
# Skip a signal when price has already made its move — i.e. it's stretched too
# far from the EMA, or the last candle just spiked in the trade direction.
# Thresholds are in multiples of the asset's ATR%, so they scale with volatility.
ANTI_CHASE_EMA_ATR   = 1.5   # skip if price is >1.5×ATR beyond the EMA (extended)
ANTI_CHASE_SPIKE_ATR = 1.2   # skip if the last candle ran >1.2×ATR in the dir
ANTI_CHASE_HIGH_LOOKBACK = 10  # candles to check for buying-into-a-recent-high
# One position per symbol at a time — re-entering the same coin every scan is
# what produced dozens of duplicate, fee-bleeding trades.

# ─── SMART PARAMETER CALCULATOR ──────────────────────────────────────────────
# Fee to cover on round trip (leverage × round_trip_fee must be < TP%)
# Recommended risk:reward: SL = TP / 2 for scalping
# Optimal leverage band: aim for ~2% notional move = TP% in price,
# so leverage ≈ TP% / ATR_estimate, capped by asset limits.

def calc_smart_params(margin: float, asset: str = "BTC_USDT",
                      leverage: int = None) -> dict:
    """
    Given a margin amount (and optionally an explicit leverage), compute optimal
    leverage, TP%, SL%. Pass `leverage` to size TP/SL for a manually-chosen
    leverage instead of deriving it from margin — higher leverage ⇒ tighter
    targets (liquidation is closer, and a small price move is already a big
    margin return).

    KEY DESIGN PRINCIPLE — price-move targets, not leverage-derived TP/SL:
      TP% and SL% are PRICE MOVE targets (e.g. 0.5% price move).
      Leverage scales INDEPENDENTLY of TP/SL price moves.
      This avoids the old bug where high leverage forced huge TP% → huge SL%
      → safety guard walked leverage back down (defeating the whole point).

    Scaling: larger margin → higher leverage, smaller price-move target.
      $5-10  →  5×  targeting 1.5% price move
      $100   → 50×  targeting 0.6% price move  (net return ~25% on margin)
      $200   → 100× targeting 0.4% price move  (net return ~30% on margin)

    MEXC fees: 0.04% maker + 0.06% taker = 0.10% round-trip (on notional).
    At any leverage, fee as % of price = 0.10% fixed — only the LEVERAGE
    turns that small price move into a large margin return.

    Rules enforced:
      1. TP price move > round-trip fee (0.10%) — always met by design
      2. SL < TP price move (R:R ≥ 1.2 after fees)
      3. Asset max leverage respected
    """
    max_lev = ASSET_MAX_LEV.get(asset, 50)

    # If the caller pinned a leverage (manual override), size TP/SL for THAT
    # leverage and skip the margin→leverage derivation entirely.
    if leverage is not None:
        lev = min(int(leverage), max_lev)
        return _params_for_leverage(lev)

    # Steeper leverage curve: larger margin → meaningfully higher leverage
    if margin <= 10:
        target_lev = 5
    elif margin <= 20:
        target_lev = 10
    elif margin <= 35:
        target_lev = 15
    elif margin <= 50:
        target_lev = 20
    elif margin <= 75:
        target_lev = 30
    elif margin <= 100:
        target_lev = 50
    elif margin <= 150:
        target_lev = 75
    elif margin <= 200:
        target_lev = 100
    elif margin <= 300:
        target_lev = 125
    elif margin <= 500:
        target_lev = 150
    elif margin <= 750:
        target_lev = 175
    else:
        target_lev = 200

    lev = min(target_lev, max_lev)
    return _params_for_leverage(lev)


def _params_for_leverage(lev: int) -> dict:
    """TP%/SL% price-move targets for a given leverage. Tighter at higher
    leverage (liquidation is closer; a small move is already a big margin
    return). TP is floored so a win always clears the round-trip fee with
    real edge left over — below ~0.30% a scalp just bleeds fees."""
    if lev <= 10:
        tp_pct, sl_pct = 1.5, 0.9
    elif lev <= 20:
        tp_pct, sl_pct = 1.0, 0.6
    elif lev <= 30:
        tp_pct, sl_pct = 0.8, 0.5
    elif lev <= 50:
        tp_pct, sl_pct = 0.6, 0.4
    elif lev <= 75:
        tp_pct, sl_pct = 0.5, 0.3
    elif lev <= 125:
        tp_pct, sl_pct = 0.45, 0.25
    elif lev <= 150:
        tp_pct, sl_pct = 0.40, 0.20
    elif lev <= 175:
        tp_pct, sl_pct = 0.35, 0.16
    else:
        tp_pct, sl_pct = 0.30, 0.14

    # Fee as % of price (fixed regardless of leverage). Floor TP at ~3× the
    # round-trip fee so wins are meaningfully net-positive; SL stays tight.
    fee_pct  = ROUND_TRIP_FEE * 100          # = 0.10%
    tp_pct   = max(tp_pct, round(fee_pct * 3, 2))   # ≥ 0.30%
    net_tp_price = tp_pct - fee_pct
    fee_cover_ok = net_tp_price > 0 and (net_tp_price / sl_pct) >= 1.0

    note = (f"Auto: lev={lev}× | TP={tp_pct}% | SL={sl_pct}% | "
            f"net_tp={net_tp_price:.2f}% | gross_margin_return={tp_pct*lev:.1f}% | "
            f"{'✓ covers fees' if fee_cover_ok else '⚠ marginal'}")
    return {
        "leverage": lev, "tp_pct": tp_pct, "sl_pct": sl_pct,
        "fee_pct": fee_pct, "fee_cover_ok": fee_cover_ok, "note": note
    }


# Signal scoring weights (7 indicators, symmetric long/short, threshold default 6/10)
DEFAULT_SIGNAL_THRESHOLD = 7.0
OVERNIGHT_THRESHOLD_DROP = 0.3   # gentle loosening at night (was 0.8 — too loose)
OVERNIGHT_START_H = 22
OVERNIGHT_END_H   = 7

# ─── ADVANCED STRATEGY DEFAULTS / RUNTIME OVERRIDE ───────────────────────────
# Snapshot of the validated, tested constants above. The Settings panel
# ("Advanced Strategy" group) exposes every one of these, and
# apply_advanced_config() pushes the user's values back into the module
# globals — the engine classes read these names at call time, so rebinding
# them covers every code path (paper + live).
ADVANCED_DEFAULTS = {
    "be_trigger":           BE_TRIGGER,
    "partial_at":           PARTIAL_AT,
    "partial_size":         PARTIAL_SIZE,
    "trail_after":          TRAIL_AFTER,
    "trail_atr_mult":       TRAIL_ATR_MULT,
    "tp_atr_mult":          TP_ATR_MULT,
    "sl_atr_mult":          SL_ATR_MULT,
    "atr_tp_floor":         ATR_TP_FLOOR,
    "atr_sl_floor":         ATR_SL_FLOOR,
    "safety_sl_mult":       SAFETY_SL_MULT,
    "safety_tp_mult":       SAFETY_TP_MULT,
    "scan_interval_s":      SCAN_INTERVAL_MS / 1000,
    "overnight_drop":       OVERNIGHT_THRESHOLD_DROP,
    "anti_chase_ema_atr":   ANTI_CHASE_EMA_ATR,
    "anti_chase_spike_atr": ANTI_CHASE_SPIKE_ATR,
    "paper_start_balance":  PAPER_START_BALANCE,
}


def apply_advanced_config(cfg: dict):
    """Overwrite the module-level strategy/risk constants from the settings UI.

    Called by MainWindow whenever settings change/apply and at bot start.
    Missing keys fall back to the validated defaults, so behaviour is
    identical when the user hasn't touched the Advanced Strategy panel.
    """
    global BE_TRIGGER, PARTIAL_AT, PARTIAL_SIZE, TRAIL_AFTER, TRAIL_ATR_MULT
    global TP_ATR_MULT, SL_ATR_MULT, ATR_TP_FLOOR, ATR_SL_FLOOR
    global SAFETY_SL_MULT, SAFETY_TP_MULT, SCAN_INTERVAL_MS
    global OVERNIGHT_THRESHOLD_DROP, ANTI_CHASE_EMA_ATR, ANTI_CHASE_SPIKE_ATR
    global PAPER_START_BALANCE

    def _f(key):
        try:
            return float(cfg.get(key, ADVANCED_DEFAULTS[key]))
        except (TypeError, ValueError):
            return float(ADVANCED_DEFAULTS[key])

    BE_TRIGGER       = _f("be_trigger")
    PARTIAL_AT       = _f("partial_at")
    PARTIAL_SIZE     = _f("partial_size")
    TRAIL_AFTER      = _f("trail_after")
    TRAIL_ATR_MULT   = _f("trail_atr_mult")
    TP_ATR_MULT      = _f("tp_atr_mult")
    SL_ATR_MULT      = _f("sl_atr_mult")
    ATR_TP_FLOOR     = _f("atr_tp_floor")
    ATR_SL_FLOOR     = _f("atr_sl_floor")
    SAFETY_SL_MULT   = _f("safety_sl_mult")
    SAFETY_TP_MULT   = _f("safety_tp_mult")
    SCAN_INTERVAL_MS = max(1000, int(round(_f("scan_interval_s") * 1000)))
    OVERNIGHT_THRESHOLD_DROP = _f("overnight_drop")
    ANTI_CHASE_EMA_ATR       = _f("anti_chase_ema_atr")
    ANTI_CHASE_SPIKE_ATR     = _f("anti_chase_spike_atr")
    PAPER_START_BALANCE      = _f("paper_start_balance")

# Dark theme palette
DARK_BG      = "#0e1117"
DARK_PANEL   = "#151926"
DARK_CARD    = "#1c2130"
DARK_BORDER  = "#323a4d"
GREEN_HI     = "#22e57e"
RED_HI       = "#ff4d68"
AMBER_HI     = "#ffc83d"
BLUE_HI      = "#52ccff"
# Readable text hierarchy. The old greys (#8892a4 / #4a5366) were ~2–5:1 on the
# dark background — the dim one was effectively unreadable. These pass WCAG AA.
TEXT_PRI     = "#eef1fa"   # primary
TEXT_SEC     = "#c0c8da"   # secondary — clearly legible
TEXT_DIM     = "#94a0b8"   # muted — still readable, not washed out

STYLE_SHEET = f"""
QMainWindow, QWidget {{ background:{DARK_BG}; color:{TEXT_PRI}; font-family:'Consolas','Courier New',monospace; font-size:12px; }}
QTabWidget::pane {{ border:1px solid {DARK_BORDER}; background:{DARK_PANEL}; }}
QTabBar::tab {{ background:{DARK_CARD}; color:{TEXT_SEC}; padding:6px 14px; border:1px solid {DARK_BORDER}; margin-right:2px; }}
QTabBar::tab:selected {{ background:{DARK_PANEL}; color:{TEXT_PRI}; border-bottom:2px solid {BLUE_HI}; }}
QTabBar::tab:hover {{ color:{TEXT_PRI}; }}
QGroupBox {{ border:1px solid {DARK_BORDER}; border-radius:4px; margin-top:8px; padding-top:8px; color:{TEXT_SEC}; font-size:11px; }}
QGroupBox::title {{ subcontrol-origin:margin; left:8px; color:{BLUE_HI}; }}
QPushButton {{ background:{DARK_CARD}; color:{TEXT_PRI}; border:1px solid {DARK_BORDER}; border-radius:3px; padding:4px 10px; }}
QPushButton:hover {{ background:#1e2435; border-color:{BLUE_HI}; }}
QPushButton:pressed {{ background:#252b3b; }}
QPushButton:checked {{ background:#13344a; border:1px solid {BLUE_HI}; color:{BLUE_HI}; font-weight:bold; }}
QPushButton:disabled {{ color:{TEXT_DIM}; }}
QPushButton#btnStart {{ background:#0a3d1f; border-color:{GREEN_HI}; color:{GREEN_HI}; font-weight:bold; }}
QPushButton#btnStart:hover {{ background:#0d5229; }}
QPushButton#btnStop {{ background:#3d0a0a; border-color:{RED_HI}; color:{RED_HI}; font-weight:bold; }}
QPushButton#btnStop:hover {{ background:#5c1010; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background:{DARK_CARD}; color:{TEXT_PRI}; border:1px solid {DARK_BORDER};
    border-radius:3px; padding:3px 6px; selection-background-color:{BLUE_HI};
}}
QComboBox::drop-down {{ border:none; }}
QComboBox QAbstractItemView {{ background:{DARK_CARD}; color:{TEXT_PRI}; selection-background-color:#1e2435; }}
QCheckBox {{ color:{TEXT_PRI}; spacing:6px; }}
QCheckBox::indicator {{ width:14px; height:14px; border:1px solid {DARK_BORDER}; border-radius:2px; background:{DARK_CARD}; }}
QCheckBox::indicator:checked {{ background:{BLUE_HI}; border-color:{BLUE_HI}; }}
QTableWidget {{ background:{DARK_PANEL}; gridline-color:{DARK_BORDER}; border:none; }}
QTableWidget::item {{ padding:3px 6px; border:none; }}
QTableWidget::item:selected {{ background:#1e2435; }}
QHeaderView::section {{ background:{DARK_CARD}; color:{TEXT_SEC}; border:none; border-bottom:1px solid {DARK_BORDER}; padding:4px 6px; font-size:11px; }}
QScrollBar:vertical {{ background:{DARK_PANEL}; width:8px; }}
QScrollBar::handle:vertical {{ background:{DARK_BORDER}; border-radius:4px; min-height:20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0px; }}
QScrollBar:horizontal {{ background:{DARK_PANEL}; height:8px; }}
QScrollBar::handle:horizontal {{ background:{DARK_BORDER}; border-radius:4px; }}
QTextEdit {{ background:{DARK_PANEL}; color:{TEXT_SEC}; border:1px solid {DARK_BORDER}; font-family:'Consolas','Courier New',monospace; font-size:11px; }}
QLabel#statVal {{ color:{GREEN_HI}; font-size:18px; font-weight:bold; }}
QLabel#statLbl {{ color:{TEXT_DIM}; font-size:10px; font-weight:bold; letter-spacing:0.5px; }}
QToolTip {{ background:{DARK_CARD}; color:{TEXT_PRI}; border:1px solid {BLUE_HI}; }}
QFrame#separator {{ background:{DARK_BORDER}; max-height:1px; }}
QSplitter::handle {{ background:{DARK_BORDER}; }}
"""

# ─── UTILITIES ────────────────────────────────────────────────────────────────

def sign_request(secret: str, params: dict) -> str:
    qs = "&".join(f"{k}={v}" for k,v in sorted(params.items()))
    return hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()

def now_ms() -> int:
    return int(time.time() * 1000)

def fmt_pnl(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}"

def fmt_pct(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"

def is_overnight() -> bool:
    h = datetime.now(timezone.utc).hour
    return h >= OVERNIGHT_START_H or h < OVERNIGHT_END_H

# ─── SIGNAL ENGINE ───────────────────────────────────────────────────────────

class SignalEngine:
    """
    Computes a 0–10 signal score from 7 indicators on 1m + 5m candles.
    Indicators:
      1. EMA cross (9/21 on 1m)        – trend direction
      2. RSI (14, 1m)                  – momentum
      3. MACD histogram (1m)           – momentum confirm
      4. Bollinger Band squeeze (5m)   – volatility breakout
      5. Volume spike (1m)             – volume confirm
      6. EMA alignment 1m vs 5m       – dual-TF gate
      7. ATR filter                    – volatility gate
    Each passes a gate and adds 10/7 ≈ 1.43 pts → max 10.
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

    @staticmethod
    def rsi(closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [max(d, 0) for d in diffs[-period:]]
        losses = [-min(d, 0) for d in diffs[-period:]]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd_hist(closes: list) -> float:
        e12 = SignalEngine.ema(closes, 12)
        e26 = SignalEngine.ema(closes, 26)
        if not e12 or not e26:
            return 0.0
        macd_line = [e12[i] - e26[i] for i in range(min(len(e12), len(e26)))]
        signal = SignalEngine.ema(macd_line, 9)
        if not signal or not macd_line:
            return 0.0
        return macd_line[-1] - signal[-1]

    @staticmethod
    def bollinger(closes: list, period: int = 20, std_mult: float = 2.0):
        if len(closes) < period:
            return None, None, None
        window = closes[-period:]
        mid = sum(window) / period
        std = math.sqrt(sum((x - mid)**2 for x in window) / period)
        return mid - std_mult*std, mid, mid + std_mult*std

    @staticmethod
    def atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.0
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
            trs.append(tr)
        return sum(trs[-period:]) / period

    def compute(self, candles_1m: list, candles_5m: list, dual_tf: bool = True) -> dict:
        """
        candles: list of dicts {t, o, h, l, c, v}
        Returns {score, direction, signals, atr_pct, rsi}

        SYMMETRIC scoring: every indicator votes for the side it actually favours
        (bullish evidence → long score, bearish evidence → short score). The
        final score is the WINNING side's total on a 0–10 scale, so longs and
        shorts are scored on equal footing. 5 directional indicators (EMA, RSI,
        MACD, Bollinger break, Dual-TF) + 2 confirmations (Volume, ATR) that back
        whichever side is leading; 7 contributors × 10/7 ≈ 1.43 each → max 10.
        """
        if len(candles_1m) < 30:
            return {"score": 0, "direction": "NONE", "signals": [], "atr_pct": 0, "rsi": 50}

        c1  = [x["c"] for x in candles_1m]
        h1  = [x["h"] for x in candles_1m]
        l1  = [x["l"] for x in candles_1m]
        v1  = [x["v"] for x in candles_1m]
        o1  = [x["o"] for x in candles_1m]
        price = c1[-1]

        signals = []
        per_ind = 10 / 7
        bull = 0.0
        bear = 0.0

        # 1. EMA 9/21 cross (1m) — trend direction
        ema9  = self.ema(c1, 9)
        ema21 = self.ema(c1, 21)
        if ema9 and ema21:
            if ema9[-1] > ema21[-1]:
                bull += per_ind; signals.append(("EMA9/21", "BULL"))
            else:
                bear += per_ind; signals.append(("EMA9/21", "BEAR"))

        # 2. RSI — momentum, with extremes voting the reversal side
        rsi_val = self.rsi(c1)
        if rsi_val >= 70:
            bear += per_ind; signals.append(("RSI", f"{rsi_val:.0f} OVERBOUGHT"))
        elif rsi_val <= 30:
            bull += per_ind; signals.append(("RSI", f"{rsi_val:.0f} OVERSOLD"))
        elif rsi_val > 50:
            bull += per_ind; signals.append(("RSI", f"{rsi_val:.0f} BULL"))
        else:
            bear += per_ind; signals.append(("RSI", f"{rsi_val:.0f} BEAR"))

        # 3. MACD histogram — momentum confirm
        hist = self.macd_hist(c1)
        if hist > 0:
            bull += per_ind; signals.append(("MACD", "BULL"))
        else:
            bear += per_ind; signals.append(("MACD", "BEAR"))

        # 4. Bollinger break (5m) — volatility breakout in either direction
        if len(candles_5m) >= 20:
            c5 = [x["c"] for x in candles_5m]
            bb_lo, bb_mid, bb_hi = self.bollinger(c5)
            if bb_lo and bb_hi:
                band_pct = (bb_hi - bb_lo) / bb_mid * 100
                if price > bb_hi * 0.999:
                    bull += per_ind; signals.append(("BB-Break", "UP"))
                elif price < bb_lo * 1.001:
                    bear += per_ind; signals.append(("BB-Break", "DOWN"))
                else:
                    signals.append(("BB-Squeeze", "YES" if band_pct < 2.0 else f"{band_pct:.1f}%"))

        # 5. Dual-TF gate: 1m EMA alignment with 5m EMA — votes the agreed side
        if dual_tf and len(candles_5m) >= 21 and ema9 and ema21:
            c5 = [x["c"] for x in candles_5m]
            ema9_5m  = self.ema(c5, 9)
            ema21_5m = self.ema(c5, 21)
            if ema9_5m and ema21_5m:
                tf1_bull = ema9[-1] > ema21[-1]
                tf5_bull = ema9_5m[-1] > ema21_5m[-1]
                if tf1_bull == tf5_bull:
                    if tf1_bull: bull += per_ind
                    else:        bear += per_ind
                    signals.append(("DualTF", "ALIGNED"))
                else:
                    signals.append(("DualTF", "CONFLICT"))

        # Leading direction from the directional votes so far.
        lead = "LONG" if bull > bear else "SHORT" if bear > bull else "NONE"

        # 6. Volume spike — confirms the leading side (or the last candle's body)
        if len(v1) >= 21:
            avg_vol = sum(v1[-21:-1]) / 20
            cur_vol = v1[-1]
            signals.append(("Volume", f"x{cur_vol/avg_vol:.1f}" if avg_vol else "?"))
            if avg_vol and cur_vol > avg_vol * 1.5:
                side = lead if lead != "NONE" else ("LONG" if c1[-1] >= o1[-1] else "SHORT")
                if side == "LONG": bull += per_ind
                else:              bear += per_ind

        # 7. ATR filter — healthy volatility confirms the leading side
        atr_val = self.atr(h1, l1, c1)
        atr_pct = atr_val / price * 100 if price else 0
        signals.append(("ATR%", f"{atr_pct:.3f}"))
        if 0.05 < atr_pct < 5.0:
            if lead == "LONG":  bull += per_ind
            elif lead == "SHORT": bear += per_ind

        # Relaxed mode: with Dual-TF off, give the leading side a free confirm
        # so single-TF scores stay comparable.
        if not dual_tf and lead != "NONE":
            if lead == "LONG": bull += per_ind
            else:              bear += per_ind
            signals.append(("DualTF", "OFF"))

        bull = min(10.0, bull)
        bear = min(10.0, bear)
        if bull > bear:
            score, direction = bull, "LONG"
        elif bear > bull:
            score, direction = bear, "SHORT"
        else:
            score, direction = bull, "NONE"

        return {
            "score": round(score, 2),
            "direction": direction,
            "signals": signals,
            "atr_pct": atr_pct,
            "rsi": rsi_val,
        }


class IndicatorPanelEngine:
    """
    EXPERIMENTAL signal engine: drives the scalper from the shared
    26-indicator library (platform/indicators.py) instead of the classic
    7-signal engine. Every indicator is user-toggleable and weightable from
    the "Signal Engine" settings group.

    Honesty guardrail (do not remove): our 40-coin out-of-sample testing
    found NO fee-beating edge in indicator scalping. This engine exists for
    transparency and experimentation — a fully customisable strategy lab —
    not because any indicator mix is a validated money-maker. The validated
    edge in this project remains the EMA30 daily trend strategy. Run PAPER
    first, always.

    Interface-compatible with SignalEngine.compute():
        compute(candles_1m, candles_5m, dual_tf) ->
            {"score" 0-10, "direction" LONG/SHORT/NONE, "signals", "atr_pct", "rsi"}

    Score mapping: compute_panel() returns a weighted bull-ness score on a
    0-10 scale where 5.0 is neutral. We convert that to a 0-10 *conviction*
    (abs distance from neutral × 2) so the existing threshold slider keeps
    its meaning: 7/10 still means "strong agreement", whichever the side.
    """

    def __init__(self, enabled=None, weights=None):
        # enabled: list of registry keys (None = library defaults, [] = none)
        # weights: {key: float}; weight 0 disables an indicator entirely
        self.enabled = enabled
        self.weights = dict(weights or {})

    @staticmethod
    def _to_lib(candles: list):
        """Scalper candle dicts {t,o,h,l,c,v} -> library format + volume list."""
        lib = [{"time": c["t"], "open": c["o"], "high": c["h"],
                "low": c["l"], "close": c["c"]} for c in candles]
        vols = [float(c.get("v") or 0.0) for c in candles]
        return lib, vols

    @staticmethod
    def _conviction(panel: dict) -> float:
        return min(10.0, abs(panel["score"] - 5.0) * 2.0)

    def compute(self, candles_1m: list, candles_5m: list, dual_tf: bool = True) -> dict:
        if not HAS_IND_LIB or len(candles_1m) < 30:
            return {"score": 0, "direction": "NONE", "signals": [],
                    "atr_pct": 0, "rsi": 50}

        lib1, vols1 = self._to_lib(candles_1m)
        panel1 = ind_lib.compute_panel(lib1, vols1,
                                       enabled=self.enabled,
                                       weights=self.weights)
        direction = panel1["direction"] if panel1["direction"] in ("LONG", "SHORT") else "NONE"
        score = self._conviction(panel1)

        # Per-indicator votes for the scan log / Claude context (skip NEUTRAL
        # noise, then append a one-line panel summary).
        signals = [(ind_lib.REGISTRY.get(k, {}).get("label", k), s["vote"])
                   for k, s in panel1["signals"].items() if s["vote"] != "NEUTRAL"]
        v = panel1["votes"]
        signals.append(("Panel",
                        f"{v['bull']}B/{v['bear']}S/{v['neutral']}N "
                        f"score {panel1['score']:.1f}"))

        # Dual-TF gate: the 5m panel must agree with the 1m panel, mirroring
        # the classic engine's EMA-alignment gate.
        if dual_tf and direction != "NONE":
            if len(candles_5m) >= 30:
                lib5, vols5 = self._to_lib(candles_5m)
                panel5 = ind_lib.compute_panel(lib5, vols5,
                                               enabled=self.enabled,
                                               weights=self.weights)
                if panel5["direction"] == direction:
                    signals.append(("DualTF", "ALIGNED"))
                else:
                    signals.append(("DualTF", "CONFLICT"))
                    direction = "NONE"
            else:
                signals.append(("DualTF", "NO 5m DATA"))
                direction = "NONE"

        # ATR% and RSI context — the adaptive threshold, anti-chase filter and
        # Claude analysis all expect these regardless of engine.
        c1 = [x["c"] for x in candles_1m]
        h1 = [x["h"] for x in candles_1m]
        l1 = [x["l"] for x in candles_1m]
        price = c1[-1]
        atr_val = SignalEngine.atr(h1, l1, c1)
        atr_pct = atr_val / price * 100 if price else 0
        rsi_val = SignalEngine.rsi(c1)

        return {
            "score": round(score, 2),
            "direction": direction,
            "signals": signals,
            "atr_pct": atr_pct,
            "rsi": rsi_val,
        }

# ─── MEXC REST CLIENT ─────────────────────────────────────────────────────────

class MexcClient:
    """
    MEXC Futures REST client.
    Signing rules (contract API):
      POST: sign( apiKey + timestamp_ms_str + json_body ), body sent as compact JSON
      GET:  sign( apiKey + timestamp_ms_str + sorted_query_string ), params as URL query
    Headers on every signed request: ApiKey, Request-Time, Signature, Content-Type
    Uses stdlib urllib so no third-party dependency is required.
    """
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key    = api_key
        self.api_secret = api_secret

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _sign(self, ts_str: str, param_str: str) -> str:
        """HMAC-SHA256(secret, apiKey + timestamp + paramString)."""
        target = self.api_key + ts_str + param_str
        return hmac.new(self.api_secret.encode("utf-8"),
                        target.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def _request(self, method: str, path: str, params: dict = None,
                 signed: bool = True, timeout: int = 12) -> dict:
        """
        Core HTTP dispatch using stdlib urllib — no requests lib needed.
        Retries up to 3 times on 429/5xx with exponential back-off.
        GET  : params → URL query string (sorted, URL-encoded for signing)
        POST : params → compact JSON body
        """
        url = MEXC_REST + path
        method = method.upper()

        if method == "GET":
            p = dict(sorted((params or {}).items()))
            qs = "&".join(
                f"{k}={urllib.parse.quote(str(v), safe='')}"
                for k, v in p.items()
            ) if p else ""
            body_bytes = None
            sign_payload = qs
            full_url = url + ("?" + qs if qs else "")
        else:  # POST
            body_str = json.dumps(params or {}, separators=(",", ":"))
            body_bytes = body_str.encode("utf-8")
            sign_payload = body_str
            full_url = url

        headers = {"Content-Type": "application/json",
                   "User-Agent": "MexcScalpingBot/1.0"}

        if signed:
            if not self.api_key or not self.api_secret:
                return {"success": False, "error": "API key/secret not set"}
            ts_str = str(int(time.time() * 1000))
            sig = self._sign(ts_str, sign_payload)
            headers.update({
                "ApiKey":       self.api_key,
                "Request-Time": ts_str,
                "Signature":    sig,
            })

        req = urllib.request.Request(
            full_url, data=body_bytes, headers=headers, method=method
        )

        last_exc = None
        raw = b""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read()
                break
            except urllib.error.HTTPError as e:
                try:
                    raw = e.read()
                except Exception:
                    raw = b""
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                    last_exc = e
                    continue
                # Surface MEXC error JSON to caller
                try:
                    return json.loads(raw.decode("utf-8", errors="replace"))
                except Exception:
                    return {"success": False, "code": e.code,
                            "msg": raw.decode("utf-8", errors="replace")[:300]}
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_exc = e
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                return {"success": False, "error": str(e)}

        if not raw:
            return {"success": False, "error": f"Empty response from API (last: {last_exc})"}

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                return json.loads(raw.decode("latin-1"))
            except Exception:
                return {"success": False, "error": f"Unparseable response: {raw[:200]}"}

    def get(self, path: str, params: dict = None, signed: bool = False) -> dict:
        return self._request("GET", path, params, signed=signed)

    def post(self, path: str, body: dict = None, signed: bool = True) -> dict:
        return self._request("POST", path, body, signed=signed)

    # ── Public endpoints ──────────────────────────────────────────────────────

    def klines(self, symbol: str, interval: str, limit: int = 100) -> list:
        """interval: Min1, Min5, Min15, Min30, Min60, Hour4, Day1"""
        data = self.get(f"/api/v1/contract/kline/{symbol}", {"interval": interval, "limit": limit})
        if "data" not in data:
            return []
        raw = data["data"]
        candles = []
        times = raw.get("time", [])
        opens  = raw.get("open", [])
        highs  = raw.get("high", [])
        lows   = raw.get("low", [])
        closes = raw.get("close", [])
        vols   = raw.get("vol", [])
        for i in range(len(times)):
            try:
                candles.append({
                    "t": float(times[i]),
                    "o": float(opens[i]),
                    "h": float(highs[i]),
                    "l": float(lows[i]),
                    "c": float(closes[i]),
                    "v": float(vols[i])
                })
            except:
                pass
        return candles

    def ticker(self, symbol: str) -> dict:
        data = self.get(f"/api/v1/contract/ticker", {"symbol": symbol})
        return data.get("data", {})

    def contract_detail(self, symbol: str = None) -> list:
        """Contract specs incl. contractSize, vol/price scales, min/max vol,
        max leverage. Public endpoint. Returns a list of contract dicts."""
        params = {"symbol": symbol} if symbol else {}
        data = self.get("/api/v1/contract/detail", params)
        d = data.get("data", [])
        if isinstance(d, dict):   # single-symbol responses come back as a dict
            d = [d]
        return d if isinstance(d, list) else []

    # ── Private endpoints ─────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        return self.get("/api/v1/private/account/assets", signed=True)

    def get_positions(self) -> list:
        r = self.get("/api/v1/private/position/open_positions", signed=True)
        return r.get("data", [])

    def get_orders(self) -> list:
        r = self.get("/api/v1/private/order/history_orders", signed=True)
        return r.get("data", {}).get("resultList", [])

    def place_order(self, symbol: str, side: int, price: float,
                    vol: float, leverage: int, open_type: int = 1,
                    order_type: int = 1, take_profit: float = None,
                    stop_loss: float = None) -> dict:
        """
        side: 1=open long, 2=close short, 3=open short, 4=close long
        order_type: 1=limit (maker, 0.04% fee), 5=market (taker, 0.06% fee)
        open_type: 1=isolated, 2=cross
        Default is LIMIT to minimise fees (maker rate).
        """
        body = {
            "symbol":    symbol,
            "side":      side,
            "openType":  open_type,
            "type":      order_type,
            "vol":       vol,
            "leverage":  leverage,
        }
        if order_type == 1 and price:
            body["price"] = round(price, 6)   # limit order requires price
        if take_profit:
            body["takeProfitPrice"] = take_profit
        if stop_loss:
            body["stopLossPrice"] = stop_loss
        return self.post("/api/v1/private/order/submit", body)

    def cancel_order(self, order_id: str, symbol: str = "") -> dict:
        # Contract cancel takes a JSON array of order ids.
        # Note: body must be a list, so we call _request directly with raw bytes.
        if not self.api_key or not self.api_secret:
            return {"success": False, "error": "API key/secret not set"}
        body_str = json.dumps([str(order_id)], separators=(",", ":"))
        ts_str   = str(int(time.time() * 1000))
        sig      = self._sign(ts_str, body_str)
        headers  = {
            "ApiKey":       self.api_key,
            "Request-Time": ts_str,
            "Signature":    sig,
            "Content-Type": "application/json",
            "User-Agent":   "MexcScalpingBot/1.0",
        }
        req = urllib.request.Request(
            MEXC_REST + "/api/v1/private/order/cancel",
            data=body_str.encode("utf-8"),
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8", errors="replace"))
            except Exception:
                return {"success": False, "code": e.code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_order(self, order_id: str) -> dict:
        return self.get(f"/api/v1/private/order/get/{order_id}")

    def close_position(self, pos_id: str, symbol: str, vol: float) -> dict:
        return self.post("/api/v1/private/order/submit", {
            "positionId": pos_id, "symbol": symbol,
            "vol": vol, "side": 4, "type": 5
        })

    def market_close(self, symbol: str, direction: str, vol: float,
                     pos_id: str = "") -> dict:
        """Reduce-only MARKET close of `vol` contracts (partial or full).
        Side per MEXC convention: close LONG = 4, close SHORT = 2; type 5 = market.
        Uses the same /order/submit path as every other order (proven signing)."""
        side = 4 if direction == "LONG" else 2
        body = {"symbol": symbol, "price": 0, "vol": vol,
                "side": side, "type": 5, "openType": 1}
        if pos_id:
            body["positionId"] = pos_id
        return self.post("/api/v1/private/order/submit", body)

    def set_leverage(self, symbol: str, leverage: int, position_type: int = 1) -> dict:
        return self.post("/api/v1/private/position/change_leverage", {
            "symbol": symbol, "leverage": leverage, "positionType": position_type
        })

# ─── WEBSOCKET MANAGER ────────────────────────────────────────────────────────

class WsManager(QThread):
    tick_received  = pyqtSignal(str, dict)   # symbol, data
    ws_status      = pyqtSignal(bool)        # connected?
    ws_error       = pyqtSignal(str)         # human-readable error

    def __init__(self, symbols: list, api_key: str = "", api_secret: str = ""):
        super().__init__()
        self.symbols    = symbols
        self.api_key    = api_key
        self.api_secret = api_secret
        self._ws        = None
        self._running   = False
        self._lock      = threading.Lock()

    def _on_open(self, ws):
        self.ws_status.emit(True)
        # Auth only if keys provided (not needed for public deal stream).
        if self.api_key and self.api_secret:
            ts  = str(now_ms())
            sig = hmac.new(self.api_secret.encode(),
                            (self.api_key + ts).encode(),
                            hashlib.sha256).hexdigest()
            ws.send(json.dumps({"method":"login","param":{"apiKey":self.api_key,"reqTime":ts,"signature":sig}}))
        # Subscribe to deal (trade) ticks only — one sub per symbol.
        # MEXC caps a connection at 30 subscriptions, so we keep it lean and
        # use REST for klines/charts. Cap defensively at 28.
        for sym in self.symbols[:28]:
            ws.send(json.dumps({"method":"sub.deal","param":{"symbol":sym}}))
        # MEXC closes the socket after ~60s without an app-level ping, so we
        # send {"method":"ping"} on a background loop.
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
        ch = data.get("channel", "")
        # Ignore pong / subscription-ack / no-symbol control frames.
        if "pong" in ch or ch.startswith("rs."):
            return
        sym = data.get("symbol", "")
        d   = data.get("data")
        if not sym or d is None:
            return
        self.tick_received.emit(sym, {"channel": ch, "data": d})

    def _on_error(self, ws, error):
        try:
            self.ws_error.emit(str(error)[:160])
        except Exception:
            pass

    def _on_close(self, ws, *args):
        self.ws_status.emit(False)
        if self._running:
            self.ws_error.emit("connection closed — reconnecting in 3s")
            time.sleep(3)
            self._connect()

    def _connect(self):
        if not HAS_WS:
            return
        self._ws = ws_lib.WebSocketApp(
            MEXC_WS,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
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

    def update_symbols(self, symbols: list):
        self.symbols = symbols

# ─── PAPER TRADE ENGINE ───────────────────────────────────────────────────────

class PaperEngine:
    """Simulated order execution for paper trading."""
    def __init__(self):
        self.balance  = PAPER_START_BALANCE
        self.positions: list = []
        self.history:  list = []
        self._id      = 0

    def _nid(self) -> str:
        self._id += 1
        return f"PAPER-{self._id}"

    def place(self, symbol, direction, price, margin, leverage, tp_pct, sl_pct,
              vol=None, atr_pct=0.0):
        # Can't deploy margin we don't have — a paper account can't go negative.
        if margin > self.balance:
            return None
        # vol = contract count (matches live sizing); fall back to notional/price.
        qty      = vol if vol is not None else (margin * leverage) / price
        tp_price = price * (1 + tp_pct/100) if direction=="LONG" else price * (1 - tp_pct/100)
        sl_price = price * (1 - sl_pct/100) if direction=="LONG" else price * (1 + sl_pct/100)
        pos = {
            "id": self._nid(), "symbol": symbol, "direction": direction,
            "entry": price, "qty": qty, "vol": vol, "margin": margin, "leverage": leverage,
            "tp": tp_price, "sl": sl_price, "init_sl": sl_price,
            "tp_pct": tp_pct, "sl_pct": sl_pct, "atr_pct": atr_pct,
            # management state
            "be_armed": False, "partial_done": False, "trail_active": False,
            "opened_at": datetime.now(timezone.utc).isoformat()
        }
        self.balance -= margin
        self.positions.append(pos)
        return pos

    def _pnl(self, pos, price, margin, leverage):
        """Net USD P&L for a given margin slice at `price` (fees included)."""
        pnl_pct  = (price - pos["entry"]) / pos["entry"] * 100
        pnl_pct *= (1 if pos["direction"] == "LONG" else -1) * leverage
        net_pct  = pnl_pct - ROUND_TRIP_FEE * 100 * leverage
        return margin * net_pct / 100, net_pct

    def _progress(self, pos, price):
        """Fraction of the way from entry toward TP (can exceed 1, can go < 0)."""
        span = (pos["tp"] - pos["entry"])
        if span == 0:
            return 0.0
        return (price - pos["entry"]) / span   # works for both dirs (tp on right side)

    def update_prices(self, prices: dict):
        """Drive the full scalping lifecycle for every open paper position:
        partial take-profit → breakeven → trailing stop → final TP/SL.
        Returns a list of realized records (partials flagged with partial=True)."""
        events = []
        for pos in list(self.positions):
            price = prices.get(pos["symbol"])
            if not price:
                continue
            is_long = pos["direction"] == "LONG"
            prog    = self._progress(pos, price)

            # ── 1. Partial take-profit: bank PARTIAL_SIZE of the position ──
            if not pos["partial_done"] and prog >= PARTIAL_AT:
                part_margin = pos["margin"] * PARTIAL_SIZE
                original_margin = pos["margin"]   # snapshot BEFORE mutation so history shows full margin
                pnl_usd, pnl_pct = self._pnl(pos, price, part_margin, pos["leverage"])
                self.balance += part_margin + pnl_usd
                pos["margin"] -= part_margin
                if pos.get("vol"):
                    pos["vol"] *= (1 - PARTIAL_SIZE)
                pos["qty"]  *= (1 - PARTIAL_SIZE)
                pos["partial_done"] = True
                events.append({**pos, "exit": price, "exit_at": datetime.now(timezone.utc).isoformat(),
                               "margin": original_margin,   # override with pre-partial margin
                               "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                               "reason": "PARTIAL", "partial": True})

            # ── 2. Breakeven: move SL to entry (+fees) once halfway to TP ──
            if not pos["be_armed"] and prog >= BE_TRIGGER:
                fee_buf = ROUND_TRIP_FEE
                pos["sl"] = pos["entry"] * (1 + fee_buf) if is_long else pos["entry"] * (1 - fee_buf)
                pos["be_armed"] = True

            # ── 3. Trailing stop: trail behind price after TRAIL_AFTER ──
            if pos["be_armed"] and prog >= TRAIL_AFTER:
                trail_pct = (pos["atr_pct"] * TRAIL_ATR_MULT) or pos["sl_pct"]
                if is_long:
                    new_sl = price * (1 - trail_pct/100)
                    if new_sl > pos["sl"]:
                        pos["sl"] = new_sl; pos["trail_active"] = True
                else:
                    new_sl = price * (1 + trail_pct/100)
                    if new_sl < pos["sl"]:
                        pos["sl"] = new_sl; pos["trail_active"] = True

            # ── 4. Exit checks (full close of the remainder) ──
            hit = None
            if is_long:
                if price >= pos["tp"]:   hit = "TP"
                elif price <= pos["sl"]: hit = "TRAIL" if pos["trail_active"] else ("BE" if pos["be_armed"] else "SL")
            else:
                if price <= pos["tp"]:   hit = "TP"
                elif price >= pos["sl"]: hit = "TRAIL" if pos["trail_active"] else ("BE" if pos["be_armed"] else "SL")

            if hit:
                pnl_usd, pnl_pct = self._pnl(pos, price, pos["margin"], pos["leverage"])
                self.balance += pos["margin"] + pnl_usd
                events.append({**pos, "exit": price, "exit_at": datetime.now(timezone.utc).isoformat(),
                               "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                               "reason": hit, "partial": False})
                self.positions.remove(pos)

        for ev in events:
            self.history.append(ev)
        return events

    def close_manual(self, pos_id: str, price: float):
        pos = next((p for p in self.positions if p["id"]==pos_id), None)
        if not pos:
            return
        pnl_pct  = (price - pos["entry"]) / pos["entry"] * 100
        pnl_pct *= (1 if pos["direction"]=="LONG" else -1) * pos["leverage"]
        fee_pct   = ROUND_TRIP_FEE * 100 * pos["leverage"]
        net_pct   = pnl_pct - fee_pct
        net_usd   = pos["margin"] * net_pct / 100
        self.balance += pos["margin"] + net_usd
        rec = {**pos, "exit": price, "exit_at": datetime.now(timezone.utc).isoformat(),
               "pnl_usd": net_usd, "pnl_pct": net_pct, "reason": "MANUAL"}
        self.history.append(rec)
        self.positions = [p for p in self.positions if p["id"]!=pos_id]

# ─── LIVE POSITION MANAGER ────────────────────────────────────────────────────

class LiveManager:
    """Applies the scalping risk lifecycle — partial take-profit, breakeven,
    trailing stop, final TP — to REAL MEXC positions.

    Design (deliberately simpler than server-side stop juggling):
      • The ENTRY order carries a WIDE server-side TP/SL as a disaster floor
        that survives app/network death (set in _execute_trade).
      • This manager holds the tighter, *real* targets as VIRTUAL stops and
        executes them with reduce-only MARKET orders (the one proven order
        path). Because the virtual stop always sits on the favourable side of
        the server floor, the bot fires first whenever it's alive.
      • Live truth (entry, vol, positionId) is re-read from open_positions every
        tick, so manual changes or partial fills can't desync our accounting.
    """

    def __init__(self, client, log):
        self._client = client
        self._log    = log
        self.state   = {}   # symbol -> management record
        self.targets = {}   # symbol -> intended {direction,tp_pct,sl_pct,atr_pct}

    def set_client(self, client):
        self._client = client

    def register(self, symbol, direction, tp_pct, sl_pct, atr_pct):
        """Record the intended (tight) targets when an entry is placed."""
        self.targets[symbol] = dict(direction=direction, tp_pct=tp_pct,
                                    sl_pct=sl_pct, atr_pct=atr_pct)

    def _progress(self, rec, price):
        span = rec["tp"] - rec["entry"]
        return (price - rec["entry"]) / span if span else 0.0

    def _net(self, rec, price, margin):
        pnl_pct  = (price - rec["entry"]) / rec["entry"] * 100
        pnl_pct *= (1 if rec["direction"] == "LONG" else -1) * rec["leverage"]
        net_pct  = pnl_pct - ROUND_TRIP_FEE * 100 * rec["leverage"]
        return margin * net_pct / 100, net_pct

    def _record(self, rec, price, vol, reason, partial):
        margin = rec["margin"] * (vol / rec["vol"]) if rec["vol"] else rec["margin"]
        pnl_usd, pnl_pct = self._net(rec, price, margin)
        return {"id": rec["pos_id"], "symbol": rec["symbol"], "direction": rec["direction"],
                "entry": rec["entry"], "exit": price, "margin": margin,
                "leverage": rec["leverage"], "vol": vol,
                "opened_at": rec.get("opened_at", ""),
                "exit_at": datetime.now(timezone.utc).isoformat(),
                "pnl_usd": pnl_usd, "pnl_pct": pnl_pct, "reason": reason, "partial": partial}

    def _send_close(self, rec, vol, reason):
        """Fire a reduce-only market close; return True only on confirmed accept."""
        try:
            r = self._client.market_close(rec["symbol"], rec["direction"], int(vol),
                                          rec.get("pos_id", ""))
        except Exception as e:
            self._log(f"  ⚠ live {reason} close error {rec['symbol']}: {e}", AMBER_HI)
            return False
        ok = isinstance(r, dict) and (r.get("success") or r.get("code") == 0)
        if not ok:
            msg = r.get("message", r) if isinstance(r, dict) else r
            self._log(f"  ⚠ live {reason} close rejected {rec['symbol']}: {msg}", AMBER_HI)
        return ok

    def _manage(self, rec, price):
        """Run one lifecycle step on a live position. Returns realized events."""
        events  = []
        is_long = rec["direction"] == "LONG"
        prog    = self._progress(rec, price)

        # 1. Partial take-profit (needs ≥2 contracts to split)
        if not rec["partial_done"] and prog >= PARTIAL_AT and rec["vol"] >= 2:
            part = int(round(rec["vol"] * PARTIAL_SIZE))
            if 1 <= part < rec["vol"] and self._send_close(rec, part, "PARTIAL"):
                events.append(self._record(rec, price, part, "PARTIAL", True))
                rec["margin"] *= (rec["vol"] - part) / rec["vol"]
                rec["vol"]    -= part
                rec["partial_done"] = True

        # 2. Breakeven: pull the virtual stop to entry (+fees) at the halfway mark
        if not rec["be_armed"] and prog >= BE_TRIGGER:
            rec["sl"] = rec["entry"] * (1 + ROUND_TRIP_FEE) if is_long else rec["entry"] * (1 - ROUND_TRIP_FEE)
            rec["be_armed"] = True

        # 3. Trailing stop behind price once well in profit
        if rec["be_armed"] and prog >= TRAIL_AFTER:
            trail_pct = (rec["atr_pct"] * TRAIL_ATR_MULT) or rec["sl_pct"]
            if is_long:
                ns = price * (1 - trail_pct/100)
                if ns > rec["sl"]: rec["sl"] = ns; rec["trail_active"] = True
            else:
                ns = price * (1 + trail_pct/100)
                if ns < rec["sl"]: rec["sl"] = ns; rec["trail_active"] = True

        # 4. Exit the remainder on TP or the virtual stop
        hit = None
        if is_long:
            if price >= rec["tp"]:   hit = "TP"
            elif price <= rec["sl"]: hit = "TRAIL" if rec["trail_active"] else ("BE" if rec["be_armed"] else "SL")
        else:
            if price <= rec["tp"]:   hit = "TP"
            elif price >= rec["sl"]: hit = "TRAIL" if rec["trail_active"] else ("BE" if rec["be_armed"] else "SL")
        if hit and self._send_close(rec, rec["vol"], hit):
            events.append(self._record(rec, price, rec["vol"], hit, False))
            rec["_closed"] = True
        return events

    def sync_and_manage(self, prices: dict):
        """Re-read live positions, manage each, and return
        (normalized positions for the UI, realized events)."""
        try:
            live = self._client.get_positions() or []
        except Exception as e:
            self._log(f"  ⚠ live positions fetch failed: {e}", AMBER_HI)
            return [], []

        events, norm, seen = [], [], set()
        for p in live:
            sym = p.get("symbol")
            if not sym:
                continue
            entry = float(p.get("holdAvgPrice") or p.get("openAvgPrice") or 0)
            vol   = float(p.get("holdVol") or 0)
            if entry <= 0 or vol <= 0:
                continue
            seen.add(sym)
            direction = "LONG" if p.get("positionType") == 1 else "SHORT"
            lev    = int(p.get("leverage") or 1)
            margin = float(p.get("im") or p.get("oim") or 0)
            pos_id = str(p.get("positionId") or "")
            price  = prices.get(sym, entry)

            rec = self.state.get(sym)
            if not rec:
                tg = self.targets.get(sym, {})
                atr_pct = tg.get("atr_pct", 0.0)
                tp_pct  = tg.get("tp_pct") or (max(ATR_TP_FLOOR, atr_pct*TP_ATR_MULT) if atr_pct else 0.6)
                sl_pct  = tg.get("sl_pct") or (max(ATR_SL_FLOOR, atr_pct*SL_ATR_MULT) if atr_pct else 0.4)
                tp = entry*(1+tp_pct/100) if direction == "LONG" else entry*(1-tp_pct/100)
                sl = entry*(1-sl_pct/100) if direction == "LONG" else entry*(1+sl_pct/100)
                rec = dict(symbol=sym, direction=direction, entry=entry, vol=vol,
                           leverage=lev, margin=margin, pos_id=pos_id,
                           tp=tp, sl=sl, tp_pct=tp_pct, sl_pct=sl_pct, atr_pct=atr_pct,
                           be_armed=False, partial_done=False, trail_active=False,
                           opened_at=datetime.now(timezone.utc).isoformat())
                self.state[sym] = rec
            else:
                # Trust the exchange for size/margin; keep our virtual stops.
                rec.update(vol=vol, margin=margin, pos_id=pos_id, leverage=lev)

            events.extend(self._manage(rec, price))
            if not rec.get("_closed"):
                norm.append({"id": pos_id, "symbol": sym, "direction": direction,
                             "entry": entry, "margin": rec["margin"], "leverage": lev})

        # Forget positions the exchange no longer reports (closed any which way).
        for sym in list(self.state):
            if sym not in seen or self.state[sym].get("_closed"):
                self.state.pop(sym, None)
        return norm, events

# ─── CLAUDE AI ANALYSER ───────────────────────────────────────────────────────

class ClaudeAnalyser(QThread):
    analysis_done = pyqtSignal(str, str)   # trade_id, analysis_text

    def __init__(self, api_key: str):
        super().__init__()
        self._api_key = api_key.strip()
        self._queue   = queue.Queue()
        self._running = False

    def enqueue(self, trade_id: str, context: dict):
        self._queue.put((trade_id, context))

    def set_key(self, key: str):
        self._api_key = key.strip()

    def run(self):
        self._running = True
        while self._running:
            try:
                trade_id, ctx = self._queue.get(timeout=1)
                self._analyse(trade_id, ctx)
            except queue.Empty:
                pass

    def stop(self):
        self._running = False

    def _manage_prompt(self, ctx: dict) -> str:
        """Prompt for re-evaluating an ALREADY-OPEN position: cut losers early,
        let winners run, retune TP/SL."""
        return f"""You are managing a LIVE open crypto scalp on MEXC. Decide whether to
hold, cut it early, or retune its targets. Be decisive: cut losers fast, let
winners run, don't pay fees for no reason (round-trip 0.10%).

Open position (live state):
{json.dumps(ctx, indent=2)}

Guidance:
- CLOSE now if the thesis is broken, momentum reversed, or it's bleeding with no edge left — better a small loss than a full SL.
- HOLD and EXTEND (raise new_tp_pct) if it's running in your favour with momentum intact — let the winner breathe past the original TP.
- TIGHTEN (lower new_sl_pct, e.g. toward breakeven) to lock in gains once well in profit.
- new_tp_pct / new_sl_pct are DISTANCES IN % FROM ENTRY (not price). Use null to leave unchanged.

Respond ONLY in this exact JSON (no markdown):
{{"action":"HOLD",
  "new_tp_pct":null,
  "new_sl_pct":null,
  "confidence":7,
  "reasoning":"Step-by-step read of price action, momentum, and why hold/close/retune.",
  "outlook":"1-2 sentences on where this goes next."}}"""

    def _analyse(self, trade_id: str, ctx: dict):
        if not self._api_key:
            self.analysis_done.emit(trade_id, json.dumps({
                "quality": 0, "reasoning": "Claude API key not configured.",
                "tp_adj": "keep", "sl_adj": "keep", "hedge": False,
                "hedge_reason": "", "multi_contract": False, "multi_reason": "",
                "outlook": "No API key set.", "entry_verdict": "SKIP",
                "risk_reward": "N/A", "fee_assessment": "N/A"
            }))
        if not self._api_key:
            self.analysis_done.emit(trade_id, json.dumps({
                "quality": 0, "reasoning": "Claude API key not configured.",
                "tp_adj": "keep", "sl_adj": "keep", "hedge": False,
                "hedge_reason": "", "multi_contract": False, "multi_reason": "",
                "outlook": "No API key set.", "entry_verdict": "SKIP",
                "risk_reward": "N/A", "fee_assessment": "N/A"
            }))
            return

        prompt = f"""You are an elite crypto futures scalping analyst for MEXC. Think like a Wall Street desk trader:
minimise fees, maximise edge, cut losers fast, let winners run within scalp targets.

MEXC API fees: maker 0.04% (limit orders), taker 0.06% (market orders).
This trade used: {ctx.get('order_type', 'LIMIT(maker)')}. Round-trip fee: 0.10% of notional.

Analyse this trade and provide a FULL reasoning chain, then your JSON verdict.

Trade context:
{json.dumps(ctx, indent=2)}

Your analysis must cover:
1. SIGNAL QUALITY (1-10): How clean is the entry? What confirms/weakens it?
2. ENTRY VERDICT: STRONG / ACCEPTABLE / MARGINAL / AVOID — and why
3. FEE ASSESSMENT: Is net profit (after {ctx.get('est_fee_usd','?')} USD fees) worth the risk?
4. TP ADJUSTMENT: Should TP be tightened or widened given ATR={ctx.get('atr_pct',0):.3f}%?
5. SL ADJUSTMENT: Is SL positioned correctly vs volatility?
6. RISK:REWARD: Actual R:R = net_profit ${ctx.get('net_profit_if_tp','?')} vs max_loss ${ctx.get('max_loss_if_sl','?')}
7. HEDGE RECOMMENDATION: Yes/No and exact reasoning
8. MARKET OUTLOOK: 2 sentences on direction and momentum
9. NEXT TRADE PARAMS: If you'd adjust leverage/TP/SL for the NEXT similar trade, state them

Respond ONLY in this exact JSON (no markdown, no preamble):
{{"quality":8,
  "entry_verdict":"STRONG",
  "reasoning":"Step-by-step: [1] RSI at X confirms momentum... [2] ATR suggests volatility...",
  "fee_assessment":"Fee $X is Y% of potential profit — acceptable/marginal/poor",
  "tp_adj":"keep",
  "sl_adj":"-0.05",
  "hedge":false,
  "hedge_reason":"Trend is unidirectional, hedge would dilute gains",
  "multi_contract":false,
  "multi_reason":"Score strong but not exceptional",
  "risk_reward":"1:2.4 after fees",
  "outlook":"Momentum is building on 5m. Watch for resistance at [level].",
  "suggested_lev":null,
  "suggested_tp":null,
  "suggested_sl":null
}}"""

        # For ongoing position management, swap in the management prompt.
        is_manage = ctx.get("mode") == "manage"
        if is_manage:
            prompt = self._manage_prompt(ctx)

        def _emit_error(reason: str, outlook: str):
            err = {
                "quality": 0, "reasoning": reason,
                "tp_adj": "keep", "sl_adj": "keep", "hedge": False,
                "hedge_reason": "", "multi_contract": False, "multi_reason": "",
                "outlook": outlook, "entry_verdict": "ERROR",
                "risk_reward": "N/A", "fee_assessment": "N/A",
                "suggested_lev": None, "suggested_tp": None, "suggested_sl": None
            }
            if is_manage:        # keep the manager from acting on an error
                err["action"] = "HOLD"
            self.analysis_done.emit(trade_id, json.dumps(err))

        if not HAS_REQUESTS:
            _emit_error("requests library not installed. Run: pip install requests",
                        "Missing requests library.")
            return

        # ── Direct HTTPS call to Anthropic API (avoids SDK connection issues) ─
        try:
            resp = req_lib.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      CLAUDE_MODEL,
                    "max_tokens": 700,
                    "messages":   [{"role": "user", "content": prompt}],
                },
                timeout=25,
            )
        except Exception as e:
            _emit_error(
                f"Network error reaching api.anthropic.com: {type(e).__name__}: {e}\n\n"
                f"MEXC connects fine but Anthropic is blocked. Try:\n"
                f"1. Temporarily disable antivirus/firewall\n"
                f"2. Set HTTPS_PROXY env var if behind a proxy\n"
                f"3. Use a VPN",
                "Network error — see reasoning for fixes.")
            return

        # ── Handle HTTP errors ────────────────────────────────────────────────
        if resp.status_code != 200:
            try:
                err = resp.json()
                msg_text = err.get("error", {}).get("message", resp.text[:300])
            except Exception:
                msg_text = resp.text[:300]
            _emit_error(
                f"Anthropic API error {resp.status_code}: {msg_text}",
                f"API error {resp.status_code}")
            return

        # ── Parse response ────────────────────────────────────────────────────
        try:
            data = resp.json()
            text = data["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed = json.loads(text.strip())
            self.analysis_done.emit(trade_id, json.dumps(parsed))
        except Exception as e:
            raw = resp.text[:500]
            _emit_error(f"JSON parse error: {e}\n\nRaw response:\n{raw}",
                        "Parse error — raw response shown in reasoning.")

    def _diagnose_error(self, e) -> tuple:
        """Turn an SDK exception into a clear, actionable message for the UI."""
        ant = anthropic_lib
        if isinstance(e, getattr(ant, "AuthenticationError", ())):
            return ("Authentication failed (401) — the Claude API key is wrong "
                    "or revoked. Check it in Settings.", "Bad API key.")
        if isinstance(e, getattr(ant, "PermissionDeniedError", ())):
            return ("Permission denied (403) — the Anthropic API is not available "
                    "for your account/region. A VPN to a supported country, a "
                    "proxy (HTTPS_PROXY env var), or AWS Bedrock / Google Vertex "
                    "is required.", "API blocked for this region/account.")
        if isinstance(e, getattr(ant, "RateLimitError", ())):
            return ("Rate limited (429) — too many requests or out of credits.",
                    "Rate limited.")
        if isinstance(e, getattr(ant, "APIConnectionError", ())):
            return ("Can't reach api.anthropic.com — the request never connected. "
                    "This is a network block on this machine: firewall/antivirus, "
                    "a proxy that isn't configured, or the API not being available "
                    "in your country. MEXC works because it's a different host. "
                    "Fixes: allow the app through your firewall, set HTTPS_PROXY, "
                    "or use a VPN to a supported region.",
                    "Network can't reach Claude (firewall / proxy / region).")
        if isinstance(e, getattr(ant, "BadRequestError", ())):
            return (f"Bad request (400) — likely an invalid model name or malformed prompt. "
                    f"Check CLAUDE_MODEL env var or the model string in the code. Error: {e}",
                    "Bad request — check model name.")
        if isinstance(e, getattr(ant, "NotFoundError", ())):
            return (f"Model not found (404) — the model name '{CLAUDE_MODEL}' is not valid "
                    f"for your API key. Check the CLAUDE_MODEL constant. Error: {e}",
                    "Model not found — check model name.")
        return (f"API Error: {e}", "Error contacting Claude.")

# ─── SCAN WORKER ──────────────────────────────────────────────────────────────

class ScanWorker(QRunnable):
    """Runs in ThreadPool – fetches klines + computes signal for one symbol."""

    class Signals(QObject):
        done = pyqtSignal(str, dict)

    def __init__(self, symbol: str, client: MexcClient, engine: SignalEngine,
                 dual_tf: bool, candle_cache: dict):
        super().__init__()
        self.symbol       = symbol
        self.client       = client
        self.engine       = engine
        self.dual_tf      = dual_tf
        self.candle_cache = candle_cache
        self.signals      = ScanWorker.Signals()

    def run(self):
        try:
            c1m = self.client.klines(self.symbol, "Min1", 60)
            c5m = self.client.klines(self.symbol, "Min5", 60)
            if c1m:
                self.candle_cache[self.symbol] = {"1m": c1m, "5m": c5m}
            result = self.engine.compute(c1m or [], c5m or [], self.dual_tf)
            result["symbol"]   = self.symbol
            result["price"]    = c1m[-1]["c"] if c1m else 0
            result["ts"]       = time.time()
            self.signals.done.emit(self.symbol, result)
        except Exception as e:
            self.signals.done.emit(self.symbol, {"symbol": self.symbol, "score": 0,
                                                  "direction": "NONE", "signals": [],
                                                  "error": str(e), "price": 0})

# ─── BALANCE WORKER ───────────────────────────────────────────────────────────

def parse_usdt_balance(resp: dict):
    """
    Extract USDT equity from a MEXC contract /account/assets response.
    Returns float or None if not found. Prefers equity, then availableBalance,
    then cashBalance. Handles both list (all assets) and dict (single) payloads.
    """
    if not isinstance(resp, dict):
        return None
    data = resp.get("data")

    def _from(asset: dict):
        for key in ("equity", "availableBalance", "cashBalance"):
            if asset.get(key) is not None:
                try:
                    return float(asset[key])
                except (TypeError, ValueError):
                    continue
        return None

    if isinstance(data, list):
        for a in data:
            if isinstance(a, dict) and a.get("currency") == "USDT":
                return _from(a)
    elif isinstance(data, dict):
        # Single-currency endpoint or already-USDT payload
        if data.get("currency") in (None, "USDT"):
            return _from(data)
    return None


def parse_usdt_avail(resp: dict):
    """Free/available USDT margin from a MEXC assets response (None if absent)."""
    if not isinstance(resp, dict):
        return None
    data = resp.get("data")
    assets = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for a in assets:
        if isinstance(a, dict) and a.get("currency") in (None, "USDT"):
            v = a.get("availableBalance")
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
    return None


class BalanceWorker(QRunnable):
    """Fetches live MEXC futures balance off the UI thread."""

    class Signals(QObject):
        done  = pyqtSignal(float, float)   # equity, available
        error = pyqtSignal(str)

    def __init__(self, client: "MexcClient"):
        super().__init__()
        self.client  = client
        self.signals = BalanceWorker.Signals()

    def run(self):
        try:
            resp = self.client.get_balance()
            if isinstance(resp, dict) and resp.get("error"):
                self.signals.error.emit(str(resp.get("error"))[:160])
                return
            bal = parse_usdt_balance(resp)
            if bal is not None:
                avail = parse_usdt_avail(resp)
                self.signals.done.emit(bal, avail if avail is not None else bal)
            else:
                self.signals.error.emit(f"USDT not found in response: {str(resp)[:120]}")
        except Exception as e:
            self.signals.error.emit(str(e))


class ChartWorker(QRunnable):
    """Fetches klines for ONE symbol purely for chart display.

    Deliberately isolated from the bot's scan/signal pipeline: it never
    touches scan results, signal scores, the scan log, or trade execution,
    so browsing charts/timeframes has zero effect on how the bot operates.
    """

    class Signals(QObject):
        done = pyqtSignal(str, list, list)   # symbol, candles_1m, candles_5m

    def __init__(self, symbol: str, client: "MexcClient"):
        super().__init__()
        self.symbol  = symbol
        self.client  = client
        self.signals = ChartWorker.Signals()

    def run(self):
        try:
            c1m = self.client.klines(self.symbol, "Min1", 60)
            c5m = self.client.klines(self.symbol, "Min5", 60)
            self.signals.done.emit(self.symbol, c1m or [], c5m or [])
        except Exception:
            self.signals.done.emit(self.symbol, [], [])

# ─── CANDLE CHART WIDGET ──────────────────────────────────────────────────────

class TimeAxisItem(pg.AxisItem):
    """Bottom axis that renders epoch-second candle timestamps as GMT/UTC clock
    time (HH:MM) instead of raw unix numbers like 1.78e+09."""
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            try:
                out.append(datetime.fromtimestamp(float(v), tz=timezone.utc).strftime("%H:%M"))
            except Exception:
                out.append("")
        return out


class CandleChart(QWidget):
    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self.symbol  = symbol
        self._candles_1m = []
        self._candles_5m = []
        self._tf     = "1m"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(2)

        # TF selector
        top = QHBoxLayout()
        lbl = QLabel(symbol)
        lbl.setStyleSheet(f"color:{BLUE_HI}; font-weight:bold;")
        top.addWidget(lbl)
        top.addStretch()
        for tf in ["1m","5m"]:
            btn = QPushButton(tf)
            btn.setFixedSize(36,22)
            btn.setCheckable(True)
            btn.setChecked(tf=="1m")
            btn.clicked.connect(lambda _, t=tf: self._switch_tf(t))
            top.addWidget(btn)
            setattr(self, f"_btn_{tf}", btn)
        layout.addLayout(top)

        # pyqtgraph plot — GMT time on the x-axis
        pg.setConfigOptions(antialias=False, useOpenGL=False)
        self.plot_widget = pg.PlotWidget(
            background=DARK_PANEL,
            axisItems={"bottom": TimeAxisItem(orientation="bottom")})
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis("left").setTextPen(TEXT_SEC)
        self.plot_widget.getAxis("bottom").setTextPen(TEXT_SEC)
        layout.addWidget(self.plot_widget)

        self._candle_item = None
        self._ema9_item   = None
        self._ema21_item  = None
        self._levels      = []      # open-position entry/TP/SL lines to overlay
        self._levels_key  = None    # change-guard so we only redraw when needed

    def _switch_tf(self, tf: str):
        self._tf = tf
        for t in ["1m","5m"]:
            btn = getattr(self, f"_btn_{t}", None)
            if btn:
                btn.setChecked(t == tf)
        self.refresh()

    def update_candles(self, c1m: list, c5m: list):
        self._candles_1m = c1m
        self._candles_5m = c5m
        self.refresh()

    def set_levels(self, levels: list):
        """Overlay entry / TP / SL lines for open positions on this symbol.
        Only redraws when the levels actually change (trailing SL, new/closed
        position) so it doesn't churn the plot every UI tick."""
        key = [(round(l["entry"], 8), round(l["tp"], 8), round(l["sl"], 8))
               for l in levels]
        if key == self._levels_key:
            return
        self._levels_key = key
        self._levels = levels
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
        candles = self._candles_1m if self._tf == "1m" else self._candles_5m
        if not candles:
            return
        self.plot_widget.clear()
        eng = SignalEngine()

        closes = [c["c"] for c in candles]
        e9  = eng.ema(closes, 9)
        e21 = eng.ema(closes, 21)
        times = [c["t"] for c in candles]

        # Draw candles as bar graph items
        n   = len(candles)
        w   = (times[-1] - times[0]) / n * 0.4 if n > 1 else 30

        for c in candles:
            color = GREEN_HI if c["c"] >= c["o"] else RED_HI
            # Wick
            self.plot_widget.plot([c["t"], c["t"]], [c["l"], c["h"]],
                                   pen=pg.mkPen(color, width=1))
            # Body
            rect = pg.QtWidgets.QGraphicsRectItem(c["t"]-w/2, min(c["o"],c["c"]),
                                                   w, abs(c["c"]-c["o"]))
            rect.setPen(pg.mkPen(color, width=0))
            rect.setBrush(pg.mkBrush(color))
            self.plot_widget.addItem(rect)

        # EMAs
        if e9:
            offset = len(times) - len(e9)
            t9 = times[offset:]
            self.plot_widget.plot(t9, e9, pen=pg.mkPen(AMBER_HI, width=1))
        if e21:
            offset = len(times) - len(e21)
            t21 = times[offset:]
            self.plot_widget.plot(t21, e21, pen=pg.mkPen(BLUE_HI, width=1))

        # Open-position levels — entry / TP / SL, MEXC-style
        for lv in self._levels:
            self._hline(lv["entry"], f"Entry {lv['direction']}", TEXT_SEC)
            self._hline(lv["tp"], "TP", GREEN_HI)
            self._hline(lv["sl"], "SL", RED_HI)

# ─── SETTINGS WIDGET ─────────────────────────────────────────────────────────

class SettingsPanel(QWidget):
    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_settings()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0,0,0,0)
        main_layout.addWidget(scroll)
        layout = QVBoxLayout(inner)
        layout.setSpacing(12)

        # ── API Keys ─────────────────────────────────────────────────────────
        grp_api = QGroupBox("API Keys")
        f = QFormLayout(grp_api)
        self.mexc_key    = QLineEdit(); self.mexc_key.setEchoMode(QLineEdit.Password)
        self.mexc_secret = QLineEdit(); self.mexc_secret.setEchoMode(QLineEdit.Password)
        self.claude_key  = QLineEdit(); self.claude_key.setEchoMode(QLineEdit.Password)
        f.addRow("MEXC API Key:", self.mexc_key)
        f.addRow("MEXC Secret:",  self.mexc_secret)
        f.addRow("Claude API Key:", self.claude_key)
        btn_save = QPushButton("Save Keys")
        btn_save.clicked.connect(self._save_settings)
        f.addRow("", btn_save)
        layout.addWidget(grp_api)

        # ── Trading Params ────────────────────────────────────────────────────
        grp_trade = QGroupBox("Trading Parameters")
        g = QGridLayout(grp_trade)
        g.setSpacing(8)

        # Row 0 - Margin (drives auto-calc)
        g.addWidget(QLabel("\U0001f4b0 Margin (USDT):"), 0, 0)
        self.cbo_margin = QComboBox()
        self.cbo_margin.setEditable(True)
        for v in MARGIN_OPTIONS:
            self.cbo_margin.addItem(str(v))
        self.cbo_margin.setCurrentText("50")
        g.addWidget(self.cbo_margin, 0, 1)

        # Auto-calc info label
        self._lbl_auto = QLabel("")
        self._lbl_auto.setStyleSheet(f"color:{BLUE_HI}; font-size:10px;")
        self._lbl_auto.setWordWrap(True)
        g.addWidget(self._lbl_auto, 1, 0, 1, 2)

        # Row 2 - Leverage with AUTO toggle
        g.addWidget(QLabel("\u26a1 Leverage:"), 2, 0)
        lev_row = QHBoxLayout()
        lev_row.setContentsMargins(0,0,0,0)
        lev_row.setSpacing(4)
        self.cbo_leverage = QComboBox()
        for v in LEVERAGE_OPTIONS:
            self.cbo_leverage.addItem(str(v), v)
        self.cbo_leverage.setCurrentText("10")
        lev_row.addWidget(self.cbo_leverage)
        self._btn_lev_auto = QPushButton("AUTO")
        self._btn_lev_auto.setFixedWidth(46)
        self._btn_lev_auto.setCheckable(True)
        self._btn_lev_auto.setChecked(True)
        self._btn_lev_auto.setToolTip("AUTO: derived from margin. Click to override manually.")
        self._btn_lev_auto.setStyleSheet(
            "QPushButton{background:#0a2a3d;border:1px solid #40c4ff;color:#40c4ff;font-size:9px;border-radius:2px;}"
            "QPushButton:!checked{background:#191d27;border:1px solid #2a2f3e;color:#4a5366;}"
        )
        lev_row.addWidget(self._btn_lev_auto)
        lev_w = QWidget(); lev_w.setLayout(lev_row)
        g.addWidget(lev_w, 2, 1)

        # Row 3 - Take Profit with AUTO toggle
        g.addWidget(QLabel("\U0001f3af Take Profit %:"), 3, 0)
        tp_row = QHBoxLayout(); tp_row.setContentsMargins(0,0,0,0); tp_row.setSpacing(4)
        self.spn_tp = QDoubleSpinBox()
        self.spn_tp.setRange(0.1, 50); self.spn_tp.setValue(1.5); self.spn_tp.setSingleStep(0.1)
        tp_row.addWidget(self.spn_tp)
        self._btn_tp_auto = QPushButton("AUTO")
        self._btn_tp_auto.setFixedWidth(46)
        self._btn_tp_auto.setCheckable(True)
        self._btn_tp_auto.setChecked(True)
        self._btn_tp_auto.setStyleSheet(
            "QPushButton{background:#0a2a3d;border:1px solid #40c4ff;color:#40c4ff;font-size:9px;border-radius:2px;}"
            "QPushButton:!checked{background:#191d27;border:1px solid #2a2f3e;color:#4a5366;}"
        )
        tp_row.addWidget(self._btn_tp_auto)
        tp_w = QWidget(); tp_w.setLayout(tp_row)
        g.addWidget(tp_w, 3, 1)

        # Row 4 - Stop Loss with AUTO toggle
        g.addWidget(QLabel("\U0001f6e1 Stop Loss %:"), 4, 0)
        sl_row = QHBoxLayout(); sl_row.setContentsMargins(0,0,0,0); sl_row.setSpacing(4)
        self.spn_sl = QDoubleSpinBox()
        self.spn_sl.setRange(0.1, 50); self.spn_sl.setValue(0.8); self.spn_sl.setSingleStep(0.1)
        sl_row.addWidget(self.spn_sl)
        self._btn_sl_auto = QPushButton("AUTO")
        self._btn_sl_auto.setFixedWidth(46)
        self._btn_sl_auto.setCheckable(True)
        self._btn_sl_auto.setChecked(True)
        self._btn_sl_auto.setStyleSheet(
            "QPushButton{background:#0a2a3d;border:1px solid #40c4ff;color:#40c4ff;font-size:9px;border-radius:2px;}"
            "QPushButton:!checked{background:#191d27;border:1px solid #2a2f3e;color:#4a5366;}"
        )
        sl_row.addWidget(self._btn_sl_auto)
        sl_w = QWidget(); sl_w.setLayout(sl_row)
        g.addWidget(sl_w, 4, 1)

        g.addWidget(QLabel("\U0001f4ca Signal Threshold:"), 5, 0)
        self.spn_thresh = QDoubleSpinBox()
        self.spn_thresh.setRange(0, 10); self.spn_thresh.setValue(DEFAULT_SIGNAL_THRESHOLD)
        self.spn_thresh.setSingleStep(0.5)
        g.addWidget(self.spn_thresh, 5, 1)

        g.addWidget(QLabel("\U0001f553 Timeframe Mode:"), 6, 0)
        self.chk_dual_tf = QCheckBox("Dual TF (1m + 5m)")
        self.chk_dual_tf.setChecked(True)
        g.addWidget(self.chk_dual_tf, 6, 1)

        g.addWidget(QLabel("\U0001f522 Max Open Positions:"), 7, 0)
        self.spn_maxpos = QSpinBox()
        self.spn_maxpos.setRange(1, 50)
        self.spn_maxpos.setValue(MAX_OPEN_POSITIONS)
        self.spn_maxpos.setToolTip("Hard cap on concurrent positions. One position "
                                   "per symbol regardless of this number.")
        g.addWidget(self.spn_maxpos, 7, 1)

        layout.addWidget(grp_trade)

        # Wire up auto-calc
        self.cbo_margin.currentTextChanged.connect(self._on_margin_changed)
        self.cbo_leverage.currentTextChanged.connect(self._on_margin_changed)
        self._btn_lev_auto.toggled.connect(self._on_auto_toggled)
        self._btn_tp_auto.toggled.connect(self._on_auto_toggled)
        self._btn_sl_auto.toggled.connect(self._on_auto_toggled)
        self._on_margin_changed()

        # ── Adaptive / Overnight ──────────────────────────────────────────────
        grp_adapt = QGroupBox("Adaptive Threshold")
        a = QVBoxLayout(grp_adapt)
        self.chk_adaptive  = QCheckBox("Enable Adaptive Threshold (ATR-based)")
        self.chk_overnight = QCheckBox("Overnight Mode (force on / off = auto by UTC time)")
        self.chk_anti_chase = QCheckBox("Anti-Chase Entries (skip overextended / into-resistance)")
        self.chk_anti_chase.setToolTip(
            "Skip a signal when price is already stretched far from the EMA or just "
            "spiked in the trade direction — avoids buying the top of a move.")
        self.chk_adaptive.setChecked(True)
        self.chk_overnight.setChecked(True)
        self.chk_anti_chase.setChecked(True)
        a.addWidget(self.chk_adaptive)
        a.addWidget(self.chk_overnight)
        a.addWidget(self.chk_anti_chase)
        layout.addWidget(grp_adapt)

        # ── Advanced Strategy (every risk-engine constant, user-tunable) ──────
        grp_adv = QGroupBox("Advanced Strategy  (expert — check to expand)")
        grp_adv.setCheckable(True)
        grp_adv.setChecked(False)
        adv_wrap = QVBoxLayout(grp_adv)
        adv_body = QWidget()
        adv_body.setVisible(False)
        grp_adv.toggled.connect(adv_body.setVisible)
        adv_wrap.addWidget(adv_body)
        av = QVBoxLayout(adv_body)
        av.setContentsMargins(0, 4, 0, 0)
        av.setSpacing(8)

        adv_note = QLabel("Defaults are the tested configuration. Changes are "
                          "experimental — test in PAPER first.")
        adv_note.setWordWrap(True)
        adv_note.setStyleSheet(f"color:{AMBER_HI}; font-size:10px;")
        av.addWidget(adv_note)

        ga = QGridLayout()
        ga.setSpacing(6)
        av.addLayout(ga)

        # (cfg key, label, tooltip, min, max, step, decimals) — defaults come
        # from ADVANCED_DEFAULTS so UI and engine can never drift apart.
        adv_spec = [
            ("be_trigger", "Breakeven Trigger",
             "Move the SL to breakeven(+fees) at this fraction of the way to TP "
             "(0.5 = halfway).", 0.05, 0.95, 0.05, 2),
            ("partial_at", "Partial TP At",
             "Bank a partial profit at this fraction of the way to TP.",
             0.05, 0.95, 0.05, 2),
            ("partial_size", "Partial Size",
             "Fraction of the position closed on the partial take-profit "
             "(0.5 = half).", 0.10, 0.90, 0.05, 2),
            ("trail_after", "Trail After",
             "Start trailing the stop at this fraction of the way to TP "
             "(post-breakeven).", 0.05, 0.95, 0.05, 2),
            ("trail_atr_mult", "Trail ATR Mult",
             "Trail the stop this many × ATR% behind price.", 0.1, 5.0, 0.1, 2),
            ("tp_atr_mult", "TP ATR Mult",
             "Adaptive TP distance = this × the asset's ATR%.", 0.1, 10.0, 0.1, 2),
            ("sl_atr_mult", "SL ATR Mult",
             "Adaptive SL distance = this × the asset's ATR%.", 0.1, 10.0, 0.1, 2),
            ("atr_tp_floor", "TP Floor %",
             "Minimum TP price move in % — should clear the 0.10% round-trip "
             "fee with edge left over.", 0.05, 5.0, 0.05, 2),
            ("atr_sl_floor", "SL Floor %",
             "Minimum SL price move in %.", 0.05, 5.0, 0.05, 2),
            ("safety_sl_mult", "Safety SL Mult",
             "LIVE only: server-side disaster stop sits this × the managed SL "
             "(fires only if the app dies).", 1.0, 5.0, 0.1, 2),
            ("safety_tp_mult", "Safety TP Mult",
             "LIVE only: server-side TP sits this × beyond the managed TP so "
             "the trailing stop can run a winner.", 1.0, 10.0, 0.1, 2),
            ("scan_interval_s", "Scan Interval (s)",
             "Seconds between market scans.", 5, 600, 5, 0),
            ("overnight_drop", "Overnight Drop",
             "How much the signal threshold is loosened overnight "
             "(22:00–07:00 UTC).", 0.0, 5.0, 0.1, 2),
            ("anti_chase_ema_atr", "Anti-Chase EMA×ATR",
             "Skip entries when price is more than this × ATR beyond the EMA "
             "(overextended).", 0.1, 10.0, 0.1, 2),
            ("anti_chase_spike_atr", "Anti-Chase Spike×ATR",
             "Skip entries when the last candle ran more than this × ATR in "
             "the trade direction.", 0.1, 10.0, 0.1, 2),
            ("paper_start_balance", "Paper Start Balance",
             "Starting bankroll (USDT) for every fresh paper session.",
             10.0, 1000000.0, 50.0, 2),
        ]
        self._adv_spins = {}
        for row, (key, label, tip, lo, hi, step, dec) in enumerate(adv_spec):
            lbl = QLabel(label + ":")
            lbl.setToolTip(tip)
            spn = QDoubleSpinBox()
            spn.setDecimals(dec)
            spn.setRange(lo, hi)
            spn.setSingleStep(step)
            spn.setValue(float(ADVANCED_DEFAULTS[key]))
            spn.setToolTip(tip)
            ga.addWidget(lbl, row, 0)
            ga.addWidget(spn, row, 1)
            self._adv_spins[key] = spn

        btn_adv_reset = QPushButton("Reset to validated defaults")
        btn_adv_reset.setToolTip("Restore every Advanced Strategy value to the "
                                 "original, tested configuration.")
        btn_adv_reset.clicked.connect(self._reset_advanced)
        av.addWidget(btn_adv_reset)
        layout.addWidget(grp_adv)

        # Persist + apply advanced values as they change (same QSettings store
        # as the API keys; _save_settings emits settings_changed → MainWindow
        # re-applies the config to the running engine).
        for spn in self._adv_spins.values():
            spn.valueChanged.connect(self._save_settings)

        # ── Signal Engine (classic vs 26-indicator lab) ───────────────────────
        grp_eng = QGroupBox("Signal Engine  (check to expand)")
        grp_eng.setCheckable(True)
        grp_eng.setChecked(False)
        eng_wrap = QVBoxLayout(grp_eng)
        eng_body = QWidget()
        eng_body.setVisible(False)
        grp_eng.toggled.connect(eng_body.setVisible)
        eng_wrap.addWidget(eng_body)
        ev = QVBoxLayout(eng_body)
        ev.setContentsMargins(0, 4, 0, 0)
        ev.setSpacing(8)

        self.cbo_engine = QComboBox()
        self.cbo_engine.addItem("Classic 7-signal engine (tested default)", "classic")
        if HAS_IND_LIB:
            self.cbo_engine.addItem("Indicator Lab — 26-indicator panel (experimental)", "panel")
        self.cbo_engine.setToolTip(
            "Classic = the original 7-signal scoring used in all testing.\n"
            "Indicator Lab = build your own signal from the full 26-indicator\n"
            "toolkit (same library as the web terminal).")
        ev.addWidget(self.cbo_engine)

        eng_note = QLabel(
            "Honesty note: our 40-coin out-of-sample testing found NO "
            "fee-beating edge in indicator scalping. The Indicator Lab is an "
            "experimentation tool, not a validated strategy — run PAPER first. "
            "Weight 0 or unticked = indicator skipped (no CPU spent)."
            if HAS_IND_LIB else
            "indicators.py not found next to the bot or in ../platform — "
            "Indicator Lab unavailable. Classic engine in use.")
        eng_note.setWordWrap(True)
        eng_note.setStyleSheet(f"color:{AMBER_HI}; font-size:10px;")
        ev.addWidget(eng_note)

        self._ind_chks, self._ind_wts = {}, {}
        if HAS_IND_LIB:
            group_titles = {"trend": "Trend", "momentum": "Momentum",
                            "volatility": "Volatility", "volume": "Volume",
                            "pattern": "Patterns"}
            for gkey, gtitle in group_titles.items():
                keys = [k for k, m in ind_lib.REGISTRY.items() if m["group"] == gkey]
                if not keys:
                    continue
                sub = QGroupBox(gtitle)
                sg = QGridLayout(sub)
                sg.setSpacing(4)
                for i, k in enumerate(keys):
                    meta = ind_lib.REGISTRY[k]
                    chk = QCheckBox(meta["label"])
                    chk.setChecked(bool(meta["default_on"]))
                    chk.setToolTip(f"Include {meta['label']} in the panel vote.")
                    wt = QDoubleSpinBox()
                    wt.setRange(0.0, 5.0)
                    wt.setSingleStep(0.25)
                    wt.setDecimals(2)
                    wt.setValue(1.0)
                    wt.setFixedWidth(64)
                    wt.setToolTip("Vote weight (0 = skip entirely).")
                    row, col = divmod(i, 2)
                    sg.addWidget(chk, row, col * 2)
                    sg.addWidget(wt, row, col * 2 + 1)
                    self._ind_chks[k] = chk
                    self._ind_wts[k] = wt
                ev.addWidget(sub)

            eng_btns = QHBoxLayout()
            btn_ind_reset = QPushButton("Reset to defaults")
            btn_ind_reset.setToolTip("Library defaults: the curated default-on "
                                     "set, every weight back to 1.0.")
            btn_ind_reset.clicked.connect(self._reset_indicators)
            btn_ind_all = QPushButton("All on")
            btn_ind_all.clicked.connect(lambda: self._set_all_indicators(True))
            btn_ind_none = QPushButton("All off")
            btn_ind_none.clicked.connect(lambda: self._set_all_indicators(False))
            for b in (btn_ind_reset, btn_ind_all, btn_ind_none):
                eng_btns.addWidget(b)
            ev.addLayout(eng_btns)

            for chk in self._ind_chks.values():
                chk.toggled.connect(self._save_settings)
            for wt in self._ind_wts.values():
                wt.valueChanged.connect(self._save_settings)

        self.cbo_engine.currentIndexChanged.connect(self._save_settings)
        layout.addWidget(grp_eng)

        # ── Asset Toggles ─────────────────────────────────────────────────────
        grp_assets = QGroupBox("Asset Selection")
        ag = QGridLayout(grp_assets)
        self._asset_chks = {}
        for i, sym in enumerate(TOP_ASSETS):
            chk = QCheckBox(sym.replace("_USDT",""))
            chk.setChecked(True)
            self._asset_chks[sym] = chk
            ag.addWidget(chk, i//3, i%3)
        layout.addWidget(grp_assets)

        layout.addStretch()

    def _reset_advanced(self):
        """Restore every Advanced Strategy spinbox to the validated defaults.
        (Block signals while writing so we emit a single settings_changed.)"""
        for key, spn in self._adv_spins.items():
            spn.blockSignals(True)
            spn.setValue(float(ADVANCED_DEFAULTS[key]))
            spn.blockSignals(False)
        self._save_settings()

    def _reset_indicators(self):
        """Indicator Lab back to library defaults: default-on set, weights 1.0."""
        for k, chk in self._ind_chks.items():
            chk.blockSignals(True)
            chk.setChecked(bool(ind_lib.REGISTRY[k]["default_on"]))
            chk.blockSignals(False)
        for wt in self._ind_wts.values():
            wt.blockSignals(True)
            wt.setValue(1.0)
            wt.blockSignals(False)
        self._save_settings()

    def _set_all_indicators(self, on: bool):
        for chk in self._ind_chks.values():
            chk.blockSignals(True)
            chk.setChecked(on)
            chk.blockSignals(False)
        self._save_settings()

    def _on_margin_changed(self, text=None):
        """Recompute leverage/TP/SL whenever margin, leverage, or an AUTO toggle
        changes. When leverage is set manually, TP/SL are sized for THAT
        leverage; when leverage is AUTO, it's derived from margin."""
        if getattr(self, "_recalc_busy", False):
            return
        self._recalc_busy = True
        try:
            try:
                margin = float(self.cbo_margin.currentText())
            except ValueError:
                return

            if self._btn_lev_auto.isChecked():
                # Leverage AUTO → derive from margin, then push it to the combo.
                params = calc_smart_params(margin)
                idx = self.cbo_leverage.findText(str(params["leverage"]))
                self.cbo_leverage.blockSignals(True)
                if idx >= 0:
                    self.cbo_leverage.setCurrentIndex(idx)
                else:
                    self.cbo_leverage.setCurrentText(str(params["leverage"]))
                self.cbo_leverage.blockSignals(False)
            else:
                # Manual leverage → size TP/SL for the chosen leverage.
                try:
                    sel_lev = int(self.cbo_leverage.currentData()
                                  or self.cbo_leverage.currentText())
                except (TypeError, ValueError):
                    sel_lev = 20
                params = calc_smart_params(margin, leverage=sel_lev)

            if self._btn_tp_auto.isChecked():
                self.spn_tp.setValue(params["tp_pct"])
            if self._btn_sl_auto.isChecked():
                self.spn_sl.setValue(params["sl_pct"])

            icon = "✓" if params["fee_cover_ok"] else "⚠"
            self._lbl_auto.setText(
                f"{icon} Auto: {params['leverage']}× lev · TP {params['tp_pct']}% · "
                f"SL {params['sl_pct']}% · fees {params['fee_pct']:.2f}%"
            )
            color = BLUE_HI if params["fee_cover_ok"] else AMBER_HI
            self._lbl_auto.setStyleSheet(f"color:{color}; font-size:10px;")
        finally:
            self._recalc_busy = False

    def _on_auto_toggled(self, _checked):
        """Re-run auto-calc when any AUTO button is toggled."""
        self._on_margin_changed()

    def apply_claude_override(self, leverage: int = None, tp_pct: float = None, sl_pct: float = None):
        """Called when Claude's analysis suggests better params. Respects user overrides."""
        if leverage is not None and self._btn_lev_auto.isChecked():
            idx = self.cbo_leverage.findText(str(leverage))
            if idx >= 0:
                self.cbo_leverage.setCurrentIndex(idx)
        if tp_pct is not None and self._btn_tp_auto.isChecked():
            self.spn_tp.setValue(tp_pct)
        if sl_pct is not None and self._btn_sl_auto.isChecked():
            self.spn_sl.setValue(sl_pct)

    def _save_settings(self):
        s = QSettings("MEXCBot","ScalpBot")
        s.setValue("mexc_key",    self.mexc_key.text())
        s.setValue("mexc_secret", self.mexc_secret.text())
        s.setValue("claude_key",  self.claude_key.text())
        s.setValue("adv_values",
                   json.dumps({k: sp.value() for k, sp in self._adv_spins.items()}))
        s.setValue("signal_engine", self.cbo_engine.currentData() or "classic")
        s.setValue("ind_enabled",
                   json.dumps([k for k, c in self._ind_chks.items() if c.isChecked()]))
        s.setValue("ind_weights",
                   json.dumps({k: w.value() for k, w in self._ind_wts.items()}))
        self.settings_changed.emit()

    def _load_settings(self):
        s = QSettings("MEXCBot","ScalpBot")
        self.mexc_key.setText(s.value("mexc_key",""))
        self.mexc_secret.setText(s.value("mexc_secret",""))
        self.claude_key.setText(s.value("claude_key",""))

        def _loads(key, fallback):
            try:
                v = json.loads(s.value(key, "") or "")
                return v if v is not None else fallback
            except (TypeError, ValueError, json.JSONDecodeError):
                return fallback

        # Advanced Strategy values (validated defaults when never saved)
        adv = _loads("adv_values", {})
        for k, spn in self._adv_spins.items():
            if k in adv:
                try:
                    spn.blockSignals(True)
                    spn.setValue(float(adv[k]))
                finally:
                    spn.blockSignals(False)

        # Signal engine mode (silently falls back to classic if the saved
        # mode isn't available, e.g. indicators.py has gone missing)
        mode = s.value("signal_engine", "classic")
        idx = self.cbo_engine.findData(mode)
        self.cbo_engine.blockSignals(True)
        self.cbo_engine.setCurrentIndex(idx if idx >= 0 else 0)
        self.cbo_engine.blockSignals(False)

        # Indicator Lab toggles + weights
        if self._ind_chks:
            en = _loads("ind_enabled", None)
            if isinstance(en, list):
                en_set = set(en)
                for k, chk in self._ind_chks.items():
                    chk.blockSignals(True)
                    chk.setChecked(k in en_set)
                    chk.blockSignals(False)
            wts = _loads("ind_weights", {})
            if isinstance(wts, dict):
                for k, wt in self._ind_wts.items():
                    if k in wts:
                        try:
                            wt.blockSignals(True)
                            wt.setValue(float(wts[k]))
                        finally:
                            wt.blockSignals(False)

    def get_config(self) -> dict:
        def _safe_margin(text: str, default: float) -> float:
            """Convert margin text to float, returning default for empty or
            partial inputs (e.g. bare '.') that float() would reject."""
            try:
                v = float(text)
                return v if v > 0 else default
            except (ValueError, TypeError):
                return default

        cfg = {
            "mexc_key":     self.mexc_key.text(),
            "mexc_secret":  self.mexc_secret.text(),
            "claude_key":   self.claude_key.text().strip(),
            "leverage":     int(self.cbo_leverage.currentData() or 20),
            "margin":       _safe_margin(self.cbo_margin.currentText(), 20),
            "tp_pct":       self.spn_tp.value(),
            "sl_pct":       self.spn_sl.value(),
            "threshold":    self.spn_thresh.value(),
            "dual_tf":      self.chk_dual_tf.isChecked(),
            "adaptive":     self.chk_adaptive.isChecked(),
            "overnight":    self.chk_overnight.isChecked(),
            "anti_chase":   self.chk_anti_chase.isChecked(),
            "tp_auto":      self._btn_tp_auto.isChecked(),
            "sl_auto":      self._btn_sl_auto.isChecked(),
            "max_positions":self.spn_maxpos.value(),
            "active_assets":[s for s,c in self._asset_chks.items() if c.isChecked()],
            "signal_engine": self.cbo_engine.currentData() or "classic",
            "ind_enabled":  [k for k, c in self._ind_chks.items() if c.isChecked()],
            "ind_weights":  {k: w.value() for k, w in self._ind_wts.items()},
        }
        # Advanced Strategy values ride along under their own keys so
        # apply_advanced_config(cfg) actually receives them (previously the
        # panel's edits never reached the engine — it always fell back to
        # the defaults).
        cfg.update({k: sp.value() for k, sp in self._adv_spins.items()})
        return cfg

# ─── POSITIONS PANEL ─────────────────────────────────────────────────────────

class PositionsPanel(QWidget):
    close_requested = pyqtSignal(str, str, float)    # pos_id, symbol, price
    hedge_requested = pyqtSignal(str, str, float)    # pos_id, symbol, price

    def __init__(self, paper: bool = True, parent=None):
        super().__init__(parent)
        self._paper = paper
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4,4,4,4)

        self._tbl = QTableWidget(0, 9)
        self._tbl.setHorizontalHeaderLabels([
            "ID","Symbol","Dir","Entry","Current","Margin","Lev","P&L $","P&L %"
        ])
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self._tbl)

        btn_row = QHBoxLayout()
        btn_close = QPushButton("Close Selected")
        btn_close.clicked.connect(self._on_close)
        btn_hedge = QPushButton("Hedge Selected")
        btn_hedge.clicked.connect(self._on_hedge)
        btn_row.addWidget(btn_close)
        btn_row.addWidget(btn_hedge)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._positions  = []
        self._cur_prices = {}

    def update_positions(self, positions: list, cur_prices: dict):
        self._positions  = positions
        self._cur_prices = cur_prices
        self._tbl.setRowCount(len(positions))
        for r, pos in enumerate(positions):
            sym   = pos.get("symbol","")
            price = cur_prices.get(sym, pos.get("entry",0))
            entry = pos.get("entry", 0)
            margin= pos.get("margin", 0)
            lev   = pos.get("leverage", 1)
            dirc  = pos.get("direction","?")
            pnl_pct = ((price-entry)/entry*100)*(1 if dirc=="LONG" else -1)*lev if entry else 0
            fee_pct  = ROUND_TRIP_FEE*100*lev
            net_pct  = pnl_pct - fee_pct
            net_usd  = margin * net_pct / 100

            vals = [pos.get("id","?"), sym, dirc, f"{entry:.4f}",
                    f"{price:.4f}", f"{margin:.1f}", str(lev),
                    fmt_pnl(net_usd), fmt_pct(net_pct)]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                if c in (7,8):
                    item.setForeground(QColor(GREEN_HI if net_usd>=0 else RED_HI))
                self._tbl.setItem(r, c, item)

    def _selected_pos(self):
        rows = self._tbl.selectionModel().selectedRows()
        if not rows:
            return None
        r   = rows[0].row()
        pos = self._positions[r] if r < len(self._positions) else None
        return pos

    def _on_close(self):
        pos = self._selected_pos()
        if pos:
            sym   = pos.get("symbol","")
            price = self._cur_prices.get(sym, 0)
            self.close_requested.emit(pos.get("id",""), sym, price)

    def _on_hedge(self):
        pos = self._selected_pos()
        if pos:
            sym   = pos.get("symbol","")
            price = self._cur_prices.get(sym, 0)
            self.hedge_requested.emit(pos.get("id",""), sym, price)

# ─── TRADE HISTORY TABLE ─────────────────────────────────────────────────────

class TradeHistoryTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4,4,4,4)
        layout.setSpacing(4)

        self._trades = []   # accumulated realized records (for the breakdown)
        self._ref_balance = PAPER_START_BALANCE   # base for the total-% figure

        # ── Per-symbol P&L breakdown — which coins actually make money ──
        self._sum_hdr = QLabel("  Per-Symbol P&L  (sorted best → worst)")
        self._sum_hdr.setStyleSheet(f"color:{BLUE_HI}; font-weight:bold; font-size:11px; padding:2px;")
        layout.addWidget(self._sum_hdr)

        self._summary = QTableWidget(0, 6)
        self._summary.setHorizontalHeaderLabels(
            ["Symbol","Trades","Win %","Net P&L $","Avg $","Best/Worst"])
        self._summary.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._summary.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._summary.verticalHeader().setVisible(False)
        self._summary.setMaximumHeight(190)
        layout.addWidget(self._summary)

        hist_hdr = QLabel("  Trade History")
        hist_hdr.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px; padding:2px;")
        layout.addWidget(hist_hdr)

        self._tbl = QTableWidget(0, 10)
        self._tbl.setHorizontalHeaderLabels([
            "Date","Time","Pair","Dir","Margin","Lev",
            "Entry","Exit","P&L $","P&L %"
        ])
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self._tbl)

    def add_trade(self, trade: dict):
        self._trades.append(trade)
        r = self._tbl.rowCount()
        self._tbl.insertRow(r)
        dt = trade.get("exit_at") or trade.get("opened_at","")
        try:
            dto = datetime.fromisoformat(dt)
            date_s = dto.strftime("%Y-%m-%d")
            time_s = dto.strftime("%H:%M:%S")
        except:
            date_s = time_s = dt
        pnl_u  = trade.get("pnl_usd", 0)
        pnl_p  = trade.get("pnl_pct", 0)
        vals = [
            date_s, time_s, trade.get("symbol",""),
            trade.get("direction",""), f"{trade.get('margin',0):.1f}",
            str(trade.get("leverage","")), f"{trade.get('entry',0):.4f}",
            f"{trade.get('exit',0):.4f}",
            fmt_pnl(pnl_u), fmt_pct(pnl_p)
        ]
        for c, val in enumerate(vals):
            item = QTableWidgetItem(str(val))
            if c in (8,9):
                item.setForeground(QColor(GREEN_HI if pnl_u>=0 else RED_HI))
            self._tbl.setItem(r, c, item)
        self._tbl.scrollToBottom()
        self._refresh_summary()

    def populate(self, trades: list):
        self._trades = []
        self._tbl.setRowCount(0)
        for t in trades:
            self.add_trade(t)

    def _refresh_summary(self):
        """Aggregate realized P&L per symbol. Net $ counts every realized slice
        (partials included); the trade count / win-rate count full round-trips
        only, matching the header stats."""
        # Grand total across everything realized this session.
        total_usd = sum(t.get("pnl_usd", 0) for t in self._trades)
        base = self._ref_balance or PAPER_START_BALANCE
        total_pct = (total_usd / base * 100) if base else 0
        tcol = GREEN_HI if total_usd >= 0 else RED_HI
        self._sum_hdr.setText(
            f"  Per-Symbol P&L   ·   Total "
            f"<span style='color:{tcol}'>{fmt_pnl(total_usd)}  ({total_pct:+.2f}%)</span>"
            f"   <span style='color:{TEXT_DIM}'>(sorted best → worst)</span>")

        agg = {}
        for t in self._trades:
            sym = t.get("symbol", "")
            if not sym:
                continue
            a = agg.setdefault(sym, {"net": 0.0, "n": 0, "wins": 0,
                                     "best": None, "worst": None})
            pnl = t.get("pnl_usd", 0)
            a["net"] += pnl
            if not t.get("partial"):
                a["n"] += 1
                if pnl > 0:
                    a["wins"] += 1
            a["best"]  = pnl if a["best"]  is None else max(a["best"],  pnl)
            a["worst"] = pnl if a["worst"] is None else min(a["worst"], pnl)

        rows = sorted(agg.items(), key=lambda kv: kv[1]["net"], reverse=True)
        self._summary.setRowCount(len(rows))
        for r, (sym, a) in enumerate(rows):
            wr  = (a["wins"] / a["n"] * 100) if a["n"] else 0
            avg = (a["net"] / a["n"]) if a["n"] else 0
            cells = [
                sym.replace("_USDT", ""),
                str(a["n"]),
                f"{wr:.0f}%",
                fmt_pnl(a["net"]),
                fmt_pnl(avg),
                f"{fmt_pnl(a['best'] or 0)} / {fmt_pnl(a['worst'] or 0)}",
            ]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(str(val))
                if c in (3, 4):
                    item.setForeground(QColor(GREEN_HI if a["net"] >= 0 else RED_HI))
                self._summary.setItem(r, c, item)


# ─── AI ANALYSIS TAB ─────────────────────────────────────────────────────────

VERDICT_COLORS = {
    "STRONG":     "#00e676",
    "ACCEPTABLE": "#40c4ff",
    "MARGINAL":   "#ffc400",
    "AVOID":      "#ff1744",
    "ERROR":      "#ff1744",
    "UNKNOWN":    "#8892a4",
    "SKIP":       "#4a5366",
}

class AIAnalysisTab(QWidget):
    """
    Rich Claude AI reasoning log. Left panel = trade list split into LIVE
    (positions currently open) and HISTORY (closed/inactive). Clicking any
    row shows the full reasoning in the right panel.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # ── Left: trade list ──────────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(280)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(2)

        hdr = QLabel("  Claude AI Log")
        hdr.setStyleSheet(f"color:{BLUE_HI}; font-weight:bold; font-size:12px; padding:4px;")
        lv.addWidget(hdr)

        # ── LIVE section ──
        live_hdr = QLabel("  ● LIVE POSITIONS")
        live_hdr.setStyleSheet(
            f"color:{GREEN_HI}; font-size:10px; font-weight:bold; "
            f"padding:3px 4px; background:{DARK_CARD}; border-bottom:1px solid {DARK_BORDER};"
        )
        lv.addWidget(live_hdr)

        self._live_list = QTableWidget(0, 4)
        self._live_list.setHorizontalHeaderLabels(["Symbol", "Q", "Verdict", "R:R"])
        self._live_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._live_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._live_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._live_list.verticalHeader().setVisible(False)
        self._live_list.setShowGrid(False)
        self._live_list.setMaximumHeight(160)
        self._live_list.setStyleSheet(
            f"QTableWidget {{ background:{DARK_CARD}; border:1px solid {GREEN_HI}; }}"
        )
        lv.addWidget(self._live_list)

        # ── HISTORY section ──
        hist_hdr = QLabel("  ◌ HISTORY")
        hist_hdr.setStyleSheet(
            f"color:{TEXT_SEC}; font-size:10px; font-weight:bold; "
            f"padding:3px 4px; background:{DARK_CARD}; border-bottom:1px solid {DARK_BORDER}; "
            f"margin-top:4px;"
        )
        lv.addWidget(hist_hdr)

        self._list = QTableWidget(0, 4)
        self._list.setHorizontalHeaderLabels(["Symbol", "Q", "Verdict", "R:R"])
        self._list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._list.verticalHeader().setVisible(False)
        self._list.setShowGrid(False)
        self._list.setStyleSheet(
            f"QTableWidget {{ background:{DARK_BG}; color:{TEXT_SEC}; }}"
        )
        lv.addWidget(self._list)

        # Stats bar
        self._stats_lbl = QLabel("  No analyses yet")
        self._stats_lbl.setStyleSheet(f"color:{TEXT_SEC}; font-size:10px; padding:3px;")
        lv.addWidget(self._stats_lbl)

        layout.addWidget(left)

        # ── Right: reasoning panel ────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        rhdr = QLabel("  Reasoning & Decision Chain")
        rhdr.setStyleSheet(f"color:{BLUE_HI}; font-weight:bold; font-size:12px; padding:4px;")
        rv.addWidget(rhdr)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setStyleSheet(
            f"background:{DARK_CARD}; color:{TEXT_PRI}; "
            f"border:1px solid {DARK_BORDER}; font-size:12px; "
            f"font-family:'Segoe UI','Arial',sans-serif;"
        )
        rv.addWidget(self._detail)
        layout.addWidget(right, 1)

        self._live_list.clicked.connect(self._show_detail)
        self._list.clicked.connect(self._show_detail)
        self._data = {}          # trade_id → parsed dict
        self._order = []         # insertion order
        self._active_ids = set() # trade_ids currently in LIVE section

    def _insert_row(self, table: QTableWidget, trade_id: str, parsed: dict,
                    row_idx: int = None) -> int:
        """Insert or update a row in the given table. Returns the row index."""
        symbol  = trade_id.split("-")[0] if "-" in trade_id else trade_id
        verdict = parsed.get("entry_verdict", "?")
        quality = str(parsed.get("quality", "?"))
        rr      = str(parsed.get("risk_reward", "?"))[:8]
        vcol    = QColor(VERDICT_COLORS.get(verdict, TEXT_SEC))

        # Find existing row in this table
        existing = None
        for i in range(table.rowCount()):
            if table.item(i, 0) and table.item(i, 0).data(Qt.UserRole) == trade_id:
                existing = i
                break

        if existing is None:
            r = table.rowCount() if row_idx is None else row_idx
            table.insertRow(r)
            existing = r

        sym_item = QTableWidgetItem(symbol)
        sym_item.setData(Qt.UserRole, trade_id)
        q_item   = QTableWidgetItem(quality)
        v_item   = QTableWidgetItem(verdict)
        rr_item  = QTableWidgetItem(rr)

        for item in [q_item, v_item, rr_item]:
            item.setForeground(vcol)

        for col, item in enumerate([sym_item, q_item, v_item, rr_item]):
            table.setItem(existing, col, item)

        return existing

    def add_analysis(self, trade_id: str, raw: str):
        try:
            parsed = json.loads(raw)
        except:
            parsed = {
                "quality": 0, "reasoning": raw,
                "entry_verdict": "UNKNOWN", "outlook": raw,
                "tp_adj": "keep", "sl_adj": "keep",
                "hedge": False, "risk_reward": "?",
                "fee_assessment": "?", "suggested_lev": None,
                "suggested_tp": None, "suggested_sl": None,
            }

        self._data[trade_id] = parsed
        if trade_id not in self._order:
            self._order.append(trade_id)

        # New analyses always go to LIVE section (trade just opened)
        self._active_ids.add(trade_id)

        # Remove from history table if it was there
        for i in range(self._list.rowCount()):
            if self._list.item(i, 0) and self._list.item(i, 0).data(Qt.UserRole) == trade_id:
                self._list.removeRow(i)
                break

        verdict = parsed.get("entry_verdict", "?")
        vcol = QColor(VERDICT_COLORS.get(verdict, TEXT_SEC))

        symbol = trade_id.split("-")[0] if "-" in trade_id else trade_id
        quality = str(parsed.get("quality", "?"))
        rr      = str(parsed.get("risk_reward", "?"))[:8]

        existing = self._insert_row(self._live_list, trade_id, parsed)

        # Auto-select and render the new entry unless the user is already
        # reading a different trade's detail
        live_sel = self._live_list.selectedItems()
        hist_sel = self._list.selectedItems()
        currently_viewing = (live_sel or hist_sel) and not (
            self._live_list.currentRow() == existing and
            self._live_list.item(existing, 0) is not None and
            self._live_list.item(existing, 0).data(Qt.UserRole) == trade_id
        )
        if not currently_viewing:
            self._list.clearSelection()
            self._live_list.selectRow(existing)
            self._render_detail(trade_id, parsed)
        self._update_stats()

    def mark_closed(self, trade_id: str):
        """Move a trade from the LIVE section to HISTORY when its position closes."""
        if trade_id not in self._active_ids:
            return
        self._active_ids.discard(trade_id)
        parsed = self._data.get(trade_id, {})

        # Remove from live list
        for i in range(self._live_list.rowCount()):
            if self._live_list.item(i, 0) and                self._live_list.item(i, 0).data(Qt.UserRole) == trade_id:
                self._live_list.removeRow(i)
                break

        # Prepend to history (most-recent first at top)
        self._insert_row(self._list, trade_id, parsed, row_idx=0)
        self._update_stats()

    def _render_detail(self, trade_id: str, p: dict):
        """Build rich HTML reasoning panel."""
        symbol  = trade_id.split("-")[0] if "-" in trade_id else trade_id
        verdict = p.get("entry_verdict", "?")
        vcol    = VERDICT_COLORS.get(verdict, TEXT_SEC)
        ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        def row(label, value, col=TEXT_PRI):
            return (f"<tr><td style='color:{TEXT_SEC};padding:2px 8px 2px 0;'>{label}</td>"
                    f"<td style='color:{col};padding:2px 0;'>{value}</td></tr>")

        # Header
        html = f"""
<div style='color:{vcol};font-size:13px;font-weight:bold;padding:4px 0 2px 0;'>
▶ {symbol} — {verdict} &nbsp; Quality: {p.get('quality','?')}/10
</div>
<div style='color:{TEXT_DIM};font-size:10px;margin-bottom:6px;'>{ts} &nbsp;|&nbsp; {trade_id}</div>
<table style='width:100%;border-collapse:collapse;'>
"""
        html += row("R:R",           p.get('risk_reward','?'),  BLUE_HI)
        html += row("Fee assessment", p.get('fee_assessment','?'), AMBER_HI)
        html += row("TP adjustment",  p.get('tp_adj','keep'),   GREEN_HI)
        html += row("SL adjustment",  p.get('sl_adj','keep'),   AMBER_HI)
        html += row("Hedge",
                    ("YES — " + str(p.get('hedge_reason',''))) if p.get('hedge') else "NO",
                    AMBER_HI if p.get('hedge') else GREEN_HI)
        html += row("Multi-contract",
                    ("YES — " + str(p.get('multi_reason',''))) if p.get('multi_contract') else "NO",
                    BLUE_HI if p.get('multi_contract') else TEXT_SEC)

        sug_lev = p.get('suggested_lev')
        sug_tp  = p.get('suggested_tp')
        sug_sl  = p.get('suggested_sl')
        if any(v is not None for v in [sug_lev, sug_tp, sug_sl]):
            parts = []
            if sug_lev: parts.append(f"lev={sug_lev}×")
            if sug_tp:  parts.append(f"TP={sug_tp}%")
            if sug_sl:  parts.append(f"SL={sug_sl}%")
            html += row("Next trade params", "  ".join(parts), BLUE_HI)

        html += "</table>"

        # Reasoning chain
        reasoning = p.get('reasoning', '')
        if reasoning:
            html += f"""
<div style='color:{BLUE_HI};font-weight:bold;margin-top:12px;margin-bottom:4px;
            font-size:12px;letter-spacing:0.5px;'>⚙ Reasoning Chain</div>
<div style='color:{TEXT_PRI};line-height:1.65;white-space:pre-wrap;
            background:{DARK_BG};padding:10px 12px;border-left:3px solid {BLUE_HI};
            border-radius:0 4px 4px 0;font-size:12px;
            font-family:"Segoe UI","Arial",sans-serif;'>{reasoning}</div>"""

        # Outlook
        outlook = p.get('outlook', '')
        if outlook:
            html += f"""
<div style='color:{AMBER_HI};font-weight:bold;margin-top:12px;margin-bottom:4px;
            font-size:12px;letter-spacing:0.5px;'>📊 Market Outlook</div>
<div style='color:{TEXT_PRI};line-height:1.65;font-style:italic;
            padding:6px 12px;border-left:3px solid {AMBER_HI};
            border-radius:0 4px 4px 0;font-size:12px;'>{outlook}</div>"""

        # TLDR — build from key fields
        verdict  = p.get('entry_verdict', '?')
        rr       = p.get('risk_reward', '?')
        tp_adj   = p.get('tp_adj', 'keep')
        sl_adj   = p.get('sl_adj', 'keep')
        hedge    = p.get('hedge', False)
        fee_ok   = p.get('fee_assessment', '')
        quality  = p.get('quality', '?')
        vcol     = VERDICT_COLORS.get(verdict, TEXT_SEC)

        tp_txt  = f"TP → {tp_adj}" if tp_adj and tp_adj != 'keep' else "TP: keep"
        sl_txt  = f"SL → {sl_adj}" if sl_adj and sl_adj != 'keep' else "SL: keep"
        h_txt   = "Hedge: YES" if hedge else "Hedge: NO"
        fee_short = (fee_ok[:60] + "…") if len(fee_ok) > 60 else fee_ok

        html += f"""
<div style='color:{GREEN_HI};font-weight:bold;margin-top:14px;margin-bottom:4px;
            font-size:12px;letter-spacing:0.5px;'>⚡ TL;DR</div>
<div style='background:{DARK_BG};padding:10px 14px;border-left:3px solid {GREEN_HI};
            border-radius:0 4px 4px 0;font-size:12px;line-height:1.8;'>
  <span style='color:{vcol};font-weight:bold;font-size:13px;'>{verdict}</span>
  &nbsp;·&nbsp;
  <span style='color:{TEXT_PRI};'>Quality {quality}/10</span>
  &nbsp;·&nbsp;
  <span style='color:{BLUE_HI};'>R:R {rr}</span>
  <br>
  <span style='color:{TEXT_SEC};'>{tp_txt} &nbsp;·&nbsp; {sl_txt} &nbsp;·&nbsp; {h_txt}</span>
  <br>
  <span style='color:{AMBER_HI};font-style:italic;'>{fee_short}</span>
</div>"""

        self._detail.setHtml(html)

    def _show_detail(self, index):
        """Handles clicks from both live_list and history list."""
        row   = index.row()
        # Determine which table sent the signal
        table = self.sender()
        item  = table.item(row, 0) if table else None
        if item:
            tid    = item.data(Qt.UserRole)
            parsed = self._data.get(tid, {})
            # Clear selection in the other table so only one row is highlighted
            if table is self._live_list:
                self._list.clearSelection()
            else:
                self._live_list.clearSelection()
            self._render_detail(tid, parsed)

    def _update_stats(self):
        total  = len(self._data)
        live   = len(self._active_ids)
        strong = sum(1 for p in self._data.values() if p.get("entry_verdict") == "STRONG")
        avoid  = sum(1 for p in self._data.values() if p.get("entry_verdict") == "AVOID")
        hedges = sum(1 for p in self._data.values() if p.get("hedge"))
        self._stats_lbl.setText(
            f"  Live: {live}  |  Total: {total}  |  Strong: {strong}  "
            f"|  Avoid: {avoid}  |  Hedged: {hedges}"
        )

# ─── SCAN LOG ────────────────────────────────────────────────────────────────

class ScanLog(QWidget):
    MAX_LINES = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self._txt = QTextEdit()
        self._txt.setReadOnly(True)
        self._txt.document().setMaximumBlockCount(self.MAX_LINES)
        layout.addWidget(self._txt)
        self._count = 0
        self._pending = []
        # Batch-flush every 2s to reduce repaints
        self._timer = QTimer()
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._flush)
        self._timer.start()

    def log(self, msg: str, color: str = TEXT_SEC):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self._pending.append((ts, msg, color))

    def _flush(self):
        if not self._pending:
            return
        cur = self._txt.textCursor()
        cur.movePosition(QTextCursor.End)
        for ts, msg, color in self._pending:
            self._txt.append(f'<span style="color:{TEXT_DIM}">{ts}</span> '
                              f'<span style="color:{color}">{msg}</span>')
        self._pending.clear()
        self._txt.ensureCursorVisible()

# ─── LIVE SETTINGS SIDEBAR (shown alongside charts) ──────────────────────────

class LiveSettingsSidebar(QWidget):
    """
    A compact scrollable sidebar with all trading settings accessible
    while viewing charts. Changes propagate immediately to the shared
    SettingsPanel, and the settings_changed signal is emitted.
    """
    settings_changed = pyqtSignal()

    def __init__(self, settings_panel, parent=None):
        super().__init__(parent)
        self._sp = settings_panel   # shared SettingsPanel reference
        self.setMinimumWidth(210)
        self.setMaximumWidth(240)
        self.setStyleSheet(f"background:{DARK_PANEL};")
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        hdr = QLabel(" ⚙  Live Settings")
        hdr.setStyleSheet(
            f"background:{DARK_CARD}; color:{BLUE_HI}; font-weight:bold; "
            f"font-size:11px; padding:6px 8px; border-bottom:1px solid {DARK_BORDER};"
        )
        outer.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(10)

        # ── Trading params ────────────────────────────────────────────────
        self._add_section(lay, "\U0001f4b0  Trade Setup")

        # Margin
        lay.addWidget(self._lbl("Margin (USDT)"))
        self._mrg = QComboBox(); self._mrg.setEditable(True)
        for v in MARGIN_OPTIONS:
            self._mrg.addItem(str(v))
        self._mrg.setCurrentText(self._sp.cbo_margin.currentText())
        lay.addWidget(self._mrg)

        # Auto-calc status mirror
        self._auto_lbl = QLabel("")
        self._auto_lbl.setWordWrap(True)
        self._auto_lbl.setStyleSheet(f"color:{BLUE_HI}; font-size:9px;")
        lay.addWidget(self._auto_lbl)

        # Leverage
        lay.addWidget(self._lbl("Leverage"))
        lev_h = QHBoxLayout(); lev_h.setContentsMargins(0,0,0,0); lev_h.setSpacing(3)
        self._lev = QComboBox()
        for v in LEVERAGE_OPTIONS:
            self._lev.addItem(str(v), v)
        self._lev.setCurrentText(self._sp.cbo_leverage.currentText())
        lev_h.addWidget(self._lev)
        self._lev_auto = QPushButton("A")
        self._lev_auto.setFixedSize(22, 22)
        self._lev_auto.setCheckable(True)
        self._lev_auto.setChecked(self._sp._btn_lev_auto.isChecked())
        self._lev_auto.setToolTip("AUTO leverage")
        self._style_auto_btn(self._lev_auto)
        lev_h.addWidget(self._lev_auto)
        lev_w = QWidget(); lev_w.setLayout(lev_h)
        lay.addWidget(lev_w)

        # TP
        lay.addWidget(self._lbl("\U0001f3af Take Profit %"))
        tp_h = QHBoxLayout(); tp_h.setContentsMargins(0,0,0,0); tp_h.setSpacing(3)
        self._tp = QDoubleSpinBox()
        self._tp.setRange(0.1, 50); self._tp.setSingleStep(0.05)
        self._tp.setValue(self._sp.spn_tp.value())
        tp_h.addWidget(self._tp)
        self._tp_auto = QPushButton("A")
        self._tp_auto.setFixedSize(22, 22)
        self._tp_auto.setCheckable(True)
        self._tp_auto.setChecked(self._sp._btn_tp_auto.isChecked())
        self._style_auto_btn(self._tp_auto)
        tp_h.addWidget(self._tp_auto)
        tp_w = QWidget(); tp_w.setLayout(tp_h)
        lay.addWidget(tp_w)

        # SL
        lay.addWidget(self._lbl("\U0001f6e1 Stop Loss %"))
        sl_h = QHBoxLayout(); sl_h.setContentsMargins(0,0,0,0); sl_h.setSpacing(3)
        self._sl = QDoubleSpinBox()
        self._sl.setRange(0.1, 50); self._sl.setSingleStep(0.05)
        self._sl.setValue(self._sp.spn_sl.value())
        sl_h.addWidget(self._sl)
        self._sl_auto = QPushButton("A")
        self._sl_auto.setFixedSize(22, 22)
        self._sl_auto.setCheckable(True)
        self._sl_auto.setChecked(self._sp._btn_sl_auto.isChecked())
        self._style_auto_btn(self._sl_auto)
        sl_h.addWidget(self._sl_auto)
        sl_w = QWidget(); sl_w.setLayout(sl_h)
        lay.addWidget(sl_w)

        # ── Signal / TF ───────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{DARK_BORDER};"); lay.addWidget(sep)
        self._add_section(lay, "\U0001f4ca  Signal")

        lay.addWidget(self._lbl("Threshold (0-10)"))
        self._thr = QDoubleSpinBox()
        self._thr.setRange(0, 10); self._thr.setSingleStep(0.5)
        self._thr.setValue(self._sp.spn_thresh.value())
        lay.addWidget(self._thr)

        self._dual_tf = QCheckBox("Dual TF (1m+5m)")
        self._dual_tf.setChecked(self._sp.chk_dual_tf.isChecked())
        lay.addWidget(self._dual_tf)

        # ── Modes ─────────────────────────────────────────────────────────
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{DARK_BORDER};"); lay.addWidget(sep2)
        self._add_section(lay, "\U0001f319  Modes")

        self._adaptive = QCheckBox("Adaptive Threshold")
        self._adaptive.setChecked(self._sp.chk_adaptive.isChecked())
        lay.addWidget(self._adaptive)

        self._overnight = QCheckBox("Overnight Mode")
        self._overnight.setChecked(self._sp.chk_overnight.isChecked())
        lay.addWidget(self._overnight)

        self._anti_chase = QCheckBox("Anti-Chase Entries")
        self._anti_chase.setToolTip("Skip overextended / into-resistance entries")
        self._anti_chase.setChecked(self._sp.chk_anti_chase.isChecked())
        lay.addWidget(self._anti_chase)

        # ── Assets ────────────────────────────────────────────────────────
        sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine)
        sep3.setStyleSheet(f"color:{DARK_BORDER};"); lay.addWidget(sep3)
        self._add_section(lay, "\U0001f4b9  Assets")
        self._asset_chks = {}
        # 3-column grid so the asset list doesn't dominate the sidebar.
        asset_w = QWidget()
        agrid = QGridLayout(asset_w)
        agrid.setContentsMargins(0, 0, 0, 0)
        agrid.setHorizontalSpacing(4); agrid.setVerticalSpacing(2)
        COLS = 3
        for i, sym in enumerate(TOP_ASSETS):
            short = sym.replace("_USDT", "")
            chk = QCheckBox(short)
            chk.setStyleSheet("font-size:10px; spacing:3px;")
            chk.setChecked(self._sp._asset_chks[sym].isChecked())
            self._asset_chks[sym] = chk
            chk.toggled.connect(lambda v, s=sym: self._sync_asset(s, v))
            agrid.addWidget(chk, i // COLS, i % COLS)
        lay.addWidget(asset_w)

        lay.addStretch()

        # ── Apply button ──────────────────────────────────────────────────
        btn_apply = QPushButton("⚡ Apply")
        btn_apply.setStyleSheet(
            f"background:#0a3d1f; border:1px solid {GREEN_HI}; color:{GREEN_HI}; "
            f"font-weight:bold; padding:5px; border-radius:3px;"
        )
        btn_apply.clicked.connect(self._apply)
        outer.addWidget(btn_apply)

        # Wire changes → immediate sync
        self._mrg.currentTextChanged.connect(self._on_margin)
        self._lev.currentIndexChanged.connect(self._sync_to_main)
        self._tp.valueChanged.connect(self._sync_to_main)
        self._sl.valueChanged.connect(self._sync_to_main)
        self._thr.valueChanged.connect(self._sync_to_main)
        self._dual_tf.toggled.connect(self._sync_to_main)
        self._adaptive.toggled.connect(self._sync_to_main)
        self._overnight.toggled.connect(self._sync_to_main)
        self._anti_chase.toggled.connect(self._sync_to_main)
        self._lev_auto.toggled.connect(self._on_auto)
        self._tp_auto.toggled.connect(self._on_auto)
        self._sl_auto.toggled.connect(self._on_auto)

        # Pull updates from main settings panel when it changes
        self._sp.settings_changed.connect(self._pull_from_main)

    def _lbl(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{TEXT_SEC}; font-size:10px; margin-top:2px;")
        return l

    def _add_section(self, layout, title):
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color:{BLUE_HI}; font-size:10px; font-weight:bold;")
        layout.addWidget(lbl)

    def _style_auto_btn(self, btn):
        btn.setStyleSheet(
            "QPushButton{background:#0a2a3d;border:1px solid #40c4ff;color:#40c4ff;"
            "font-size:9px;border-radius:2px;font-weight:bold;}"
            "QPushButton:!checked{background:#191d27;border:1px solid #2a2f3e;color:#4a5366;}"
        )

    def _on_margin(self, text):
        """Sync margin change to main settings panel (which runs auto-calc)."""
        self._sp.cbo_margin.setCurrentText(text)
        # Mirror auto-calc label
        self._pull_from_main()

    def _on_auto(self):
        """Sync auto toggles to main panel and re-run calc."""
        self._sp._btn_lev_auto.setChecked(self._lev_auto.isChecked())
        self._sp._btn_tp_auto.setChecked(self._tp_auto.isChecked())
        self._sp._btn_sl_auto.setChecked(self._sl_auto.isChecked())
        self._sp._on_margin_changed(self._mrg.currentText())
        self._pull_from_main()

    def _sync_asset(self, sym, val):
        self._sp._asset_chks[sym].setChecked(val)

    def _sync_to_main(self):
        """Push sidebar values → main SettingsPanel without triggering loops."""
        if not self._lev_auto.isChecked():
            self._sp.cbo_leverage.setCurrentText(self._lev.currentText())
        if not self._tp_auto.isChecked():
            self._sp.spn_tp.setValue(self._tp.value())
        if not self._sl_auto.isChecked():
            self._sp.spn_sl.setValue(self._sl.value())
        self._sp.spn_thresh.setValue(self._thr.value())
        self._sp.chk_dual_tf.setChecked(self._dual_tf.isChecked())
        self._sp.chk_adaptive.setChecked(self._adaptive.isChecked())
        self._sp.chk_overnight.setChecked(self._overnight.isChecked())
        self._sp.chk_anti_chase.setChecked(self._anti_chase.isChecked())
        # Reflect the recomputed auto TP/SL (e.g. after a leverage change) back
        # into the sidebar so what's shown matches what the main panel calculated.
        self._pull_from_main()

    def _pull_from_main(self):
        """Pull current values from main SettingsPanel into sidebar."""
        self._lev.blockSignals(True)
        self._lev.setCurrentText(self._sp.cbo_leverage.currentText())
        self._lev.blockSignals(False)
        self._tp.blockSignals(True); self._tp.setValue(self._sp.spn_tp.value()); self._tp.blockSignals(False)
        self._sl.blockSignals(True); self._sl.setValue(self._sp.spn_sl.value()); self._sl.blockSignals(False)
        self._thr.blockSignals(True); self._thr.setValue(self._sp.spn_thresh.value()); self._thr.blockSignals(False)
        auto_text = self._sp._lbl_auto.text()
        self._auto_lbl.setText(auto_text)
        color = self._sp._lbl_auto.styleSheet()
        self._auto_lbl.setStyleSheet(color.replace("font-size:10px", "font-size:9px"))

    def _apply(self):
        self._sync_to_main()
        self.settings_changed.emit()


# ─── MAIN WINDOW ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VER}")
        self.resize(1600, 960)
        self.setStyleSheet(STYLE_SHEET)

        # State
        self._bot_running    = False
        self._paper_mode     = True
        self._ws_connected   = False
        self._session_start  = None
        self._paper_trades   = []   # paper-only realized trades
        self._live_trades    = []   # live-only realized trades
        self._last_signal    = "—"
        self._top_signal_symbol = None   # strongest current signal (for click-nav)
        self._cur_prices     = {}
        self._candle_cache   = {}
        self._scan_results   = {}
        self._uptime_secs    = 0
        self._live_balance   = None   # last fetched MEXC futures USDT equity
        self._live_avail     = None   # last fetched MEXC futures available balance
        self._contract_info  = {}     # symbol -> contract spec (size/scales/limits)

        # Engines
        self._signal_engine  = SignalEngine()
        self._panel_engine   = IndicatorPanelEngine()   # used when Signal Engine = Indicator Lab
        self._paper_engine   = PaperEngine()
        self._thread_pool    = QThreadPool()
        self._thread_pool.setMaxThreadCount(8)
        self._client         = MexcClient()
        self._live_mgr       = LiveManager(self._client, self._log_risk)
        self._live_positions = []     # normalized live positions for the UI
        self._live_open_syms = set()  # symbols with a live order placed/open
        self._claude         = ClaudeAnalyser("")
        self._claude.analysis_done.connect(self._on_claude_done)

        # WebSocket
        self._ws_mgr         = None

        self._build_ui()
        self._build_timers()

        # Populate charts immediately on open (public klines, no bot/keys needed)
        QTimer.singleShot(150, self._initial_chart_load)
        # Connect the public market-data WebSocket on open so live prices/candles
        # flow right away — independent of whether the bot has been started.
        QTimer.singleShot(300, self._ensure_ws)
        # Load contract specs (contractSize etc.) so order sizing is correct and
        # paper matches live. Public endpoint, runs once off the UI thread.
        QTimer.singleShot(200, self._load_contract_specs)

    # ─────────────────────────── UI BUILD ────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6,6,6,6)
        root.setSpacing(6)

        # ── Status bar (always visible) ───────────────────────────────────────
        self._build_top_bar(root)

        # ── Main splitter: left sidebar + right content ───────────────────────
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # LEFT: controls + stats
        left = QWidget(); left.setMaximumWidth(300); left.setMinimumWidth(240)
        lv = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(6)
        self._build_left_panel(lv)
        splitter.addWidget(left)

        # RIGHT: tabs
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.North)
        splitter.addWidget(self._tabs)
        splitter.setSizes([280, 1300])

        self._build_tabs()

    def _build_top_bar(self, parent_layout):
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background:{DARK_PANEL}; border-bottom:1px solid {DARK_BORDER};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8,4,8,4)
        h.setSpacing(16)

        # Mode indicator
        self._lbl_mode = QLabel("● PAPER")
        self._lbl_mode.setStyleSheet(f"color:{AMBER_HI}; font-weight:bold;")
        h.addWidget(self._lbl_mode)

        # Run-state indicator (clear active/idle signal)
        self._lbl_status = QLabel("● STOPPED")
        self._lbl_status.setStyleSheet(f"color:{TEXT_DIM}; font-weight:bold;")
        self._lbl_status.setToolTip("Bot run state")
        h.addWidget(self._lbl_status)

        self._btn_paper = QPushButton("Paper")
        self._btn_paper.setCheckable(True); self._btn_paper.setChecked(True)
        self._btn_paper.clicked.connect(lambda: self._set_mode(True))
        self._btn_live = QPushButton("Live")
        self._btn_live.setCheckable(True)
        self._btn_live.clicked.connect(lambda: self._set_mode(False))
        h.addWidget(self._btn_paper)
        h.addWidget(self._btn_live)

        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color:{DARK_BORDER};"); h.addWidget(sep)

        # WS indicator
        self._lbl_ws = QLabel("◉ WS: OFF")
        self._lbl_ws.setStyleSheet(f"color:{RED_HI};")
        h.addWidget(self._lbl_ws)

        # Overnight-mode indicator (hidden unless the mode is enabled)
        self._lbl_overnight = QLabel("🌙 NIGHT")
        self._lbl_overnight.setToolTip("Overnight mode — lowers the signal threshold during GMT 22:00–07:00")
        self._lbl_overnight.setVisible(False)
        h.addWidget(self._lbl_overnight)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet(f"color:{DARK_BORDER};"); h.addWidget(sep2)

        # Stats
        for attr, label, default in [
            ("_lbl_bal",    "Balance",  "—"),
            ("_lbl_avail",  "Available","—"),
            ("_lbl_pnl",    "P&L",      "$0.00"),
            ("_lbl_wr",     "Win Rate", "—"),
            ("_lbl_trades", "Trades",   "0"),
            ("_lbl_uptime", "Uptime",   "00:00:00"),
            ("_lbl_sig",    "Last Sig", "—"),
        ]:
            box = QWidget()
            bv  = QVBoxLayout(box); bv.setContentsMargins(0,0,0,0); bv.setSpacing(0)
            lbl_l = QLabel(label); lbl_l.setObjectName("statLbl")
            lbl_v = QLabel(default); lbl_v.setObjectName("statVal")
            lbl_v.setStyleSheet("font-size:13px; font-weight:bold;")
            bv.addWidget(lbl_l); bv.addWidget(lbl_v)
            setattr(self, attr, lbl_v)
            h.addWidget(box)

        # "Last Sig" shows the current strongest signal and is clickable →
        # jumps to that asset's chart.
        self._lbl_sig.setCursor(Qt.PointingHandCursor)
        self._lbl_sig.setToolTip("Strongest current signal — click to open its chart")
        self._lbl_sig.mousePressEvent = lambda _e: self._open_top_signal_chart()

        h.addStretch()

        # Start / Stop
        self._btn_start = QPushButton("▶ START")
        self._btn_start.setObjectName("btnStart")
        self._btn_start.setFixedWidth(90)
        self._btn_start.clicked.connect(self._start_bot)
        self._btn_stop  = QPushButton("■ STOP")
        self._btn_stop.setObjectName("btnStop")
        self._btn_stop.setFixedWidth(90)
        self._btn_stop.clicked.connect(self._stop_bot)
        self._btn_stop.setEnabled(False)
        h.addWidget(self._btn_start)
        h.addWidget(self._btn_stop)

        parent_layout.addWidget(bar)

    def _build_left_panel(self, layout):
        # Full positions panel — lives in the "Positions" tab (added in _build_tabs).
        self._positions_panel = PositionsPanel(paper=True)
        self._positions_panel.close_requested.connect(self._manual_close)
        self._positions_panel.hedge_requested.connect(self._manual_hedge)

        # Open positions — compact, always-visible sidebar summary.
        # NOTE: must be a SEPARATE widget from _positions_panel; a Qt widget can
        # only have one parent, so reusing the same panel here would empty it
        # the moment it's added to the Positions tab.
        grp_pos = QGroupBox("Open Positions")
        gv = QVBoxLayout(grp_pos)
        gv.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self._pos_cards_layout = QVBoxLayout(holder)
        self._pos_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._pos_cards_layout.setSpacing(5)
        self._pos_cards_layout.addStretch()
        scroll.setWidget(holder)
        gv.addWidget(scroll)
        self._pos_empty = QLabel("No open positions")
        self._pos_empty.setStyleSheet(f"color:{TEXT_DIM}; font-size:10px; padding:6px;")
        self._pos_empty.setAlignment(Qt.AlignCenter)
        self._pos_cards_layout.insertWidget(0, self._pos_empty)
        self._pos_cards = {}        # pos-key -> {"frame":..., label refs...}
        self._pos_card_keys = None  # last-built set, to avoid rebuild churn
        layout.addWidget(grp_pos, 2)   # give it more height than before

        # Signal overview table — compact (smaller text + tighter rows)
        grp_sig = QGroupBox("Signal Scores")
        gv2 = QVBoxLayout(grp_sig)
        gv2.setContentsMargins(4, 4, 4, 4)
        self._sig_tbl = QTableWidget(len(TOP_ASSETS), 3)
        self._sig_tbl.setHorizontalHeaderLabels(["Asset","Score","Dir"])
        self._sig_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._sig_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._sig_tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._sig_tbl.setStyleSheet("QTableWidget{font-size:10px;} QHeaderView::section{font-size:9px;}")
        self._sig_tbl.verticalHeader().setVisible(False)
        self._sig_tbl.verticalHeader().setDefaultSectionSize(17)
        self._sig_tbl.setFixedHeight(190)
        self._sig_tbl.setCursor(Qt.PointingHandCursor)
        self._sig_tbl.setToolTip("Sorted strongest-first — click a row to open its chart")
        self._sig_tbl.cellClicked.connect(self._on_sig_row_clicked)
        for r, sym in enumerate(TOP_ASSETS):
            self._sig_tbl.setItem(r,0,QTableWidgetItem(sym.replace("_USDT","")))
            self._sig_tbl.setItem(r,1,QTableWidgetItem("—"))
            self._sig_tbl.setItem(r,2,QTableWidgetItem("—"))
        gv2.addWidget(self._sig_tbl)
        layout.addWidget(grp_sig)

    def _build_tabs(self):
        # ── Asset chart tabs with live settings sidebar ───────────────────────
        self._chart_widgets = {}
        chart_outer = QWidget()
        chart_outer_h = QHBoxLayout(chart_outer)
        chart_outer_h.setContentsMargins(0, 0, 0, 0)
        chart_outer_h.setSpacing(0)

        # Build settings first (needed for sidebar reference)
        self._settings = SettingsPanel()
        self._settings.settings_changed.connect(self._apply_settings)

        # Live sidebar
        self._live_sidebar = LiveSettingsSidebar(self._settings)
        self._live_sidebar.settings_changed.connect(self._apply_settings)

        asset_tabs = QTabWidget()
        asset_tabs.setTabPosition(QTabWidget.North)
        for sym in TOP_ASSETS:
            cw = CandleChart(sym)
            self._chart_widgets[sym] = cw
            asset_tabs.addTab(cw, sym.replace("_USDT",""))
        self._asset_tabs = asset_tabs
        # Refresh the visible chart as soon as the user switches to it
        asset_tabs.currentChanged.connect(lambda _i: self._refresh_visible_chart())
        chart_outer_h.addWidget(asset_tabs, 1)
        chart_outer_h.addWidget(self._live_sidebar)
        self._tabs.addTab(chart_outer, "Charts")

        # ── Positions ─────────────────────────────────────────────────────────
        self._tabs.addTab(self._positions_panel, "Positions")

        # ── Trade History ─────────────────────────────────────────────────────
        self._history_tbl = TradeHistoryTable()
        self._tabs.addTab(self._history_tbl, "Trade History")

        # ── AI Analysis ───────────────────────────────────────────────────────
        self._ai_tab = AIAnalysisTab()
        self._tabs.addTab(self._ai_tab, "AI Analysis")

        # ── Scan Log ──────────────────────────────────────────────────────────
        self._scan_log = ScanLog()
        self._tabs.addTab(self._scan_log, "Scan Log")

        # ── Settings ──────────────────────────────────────────────────────────
        self._tabs.addTab(self._settings, "Settings")

    # ─────────────────────────── TIMERS ───────────────────────────────────────

    def _build_timers(self):
        # Uptime
        self._uptime_timer = QTimer()
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._tick_uptime)

        # Scan timer
        self._scan_timer = QTimer()
        self._scan_timer.setInterval(SCAN_INTERVAL_MS)
        self._scan_timer.timeout.connect(self._run_scan)

        # UI refresh (positions P&L, etc.) — 3 Hz
        self._ui_timer = QTimer()
        self._ui_timer.setInterval(333)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()

        # Risk lifecycle tick — 1 Hz. Always on: live position management
        # (breakeven / partial / trailing) must keep running even after the
        # bot is "stopped", so open positions stay protected.
        self._paper_timer = QTimer()
        self._paper_timer.setInterval(1000)
        self._paper_timer.timeout.connect(self._risk_tick)
        self._paper_timer.start()

        # Chart refresh (visible chart only) — runs always, even when bot stopped
        self._chart_timer = QTimer()
        self._chart_timer.setInterval(10000)   # 10 s
        self._chart_timer.timeout.connect(self._refresh_visible_chart)
        self._chart_timer.start()

        # Live balance poll — runs always, fetches only in live mode with keys
        self._balance_timer = QTimer()
        self._balance_timer.setInterval(15000)  # 15 s
        self._balance_timer.timeout.connect(self._fetch_live_balance)
        self._balance_timer.start()

        # Ongoing AI management — adaptive cadence (see _run_manage_checks):
        # the timer ticks every 10 s, and each open position is re-checked
        # 20–90 s apart depending on how close it is to its TP/SL. Always on;
        # no-ops when there's no Claude key.
        self._manage_timer = QTimer()
        self._manage_timer.setInterval(10000)  # 10 s base tick
        self._manage_timer.timeout.connect(self._run_manage_checks)
        self._manage_timer.start()

    # ─────────────────────────── CONTRACT SPECS ───────────────────────────────

    def _load_contract_specs(self):
        """Fetch contract specs once (contractSize, vol/price scales, min vol,
        max leverage). Needed for correct order sizing — vol is in CONTRACTS,
        and quantity = vol × contractSize. Runs off the UI thread."""
        def worker():
            try:
                details = MexcClient().contract_detail()   # public, all symbols
            except Exception:
                details = []
            info = {}
            for c in details:
                sym = c.get("symbol")
                if not sym:
                    continue
                info[sym] = {
                    "contractSize": float(c.get("contractSize", 0) or 0),
                    "priceScale":   int(c.get("priceScale", c.get("priceUnit", 6)) or 6),
                    "volScale":     int(c.get("volScale", c.get("volUnit", 0)) or 0),
                    "minVol":       float(c.get("minVol", 1) or 1),
                    "maxLeverage":  int(c.get("maxLeverage", 0) or 0),
                }
            self._contract_info = info
            self._scan_log.log(
                f"Loaded specs for {len(info)} contracts." if info
                else "Contract specs unavailable (using fallbacks).",
                BLUE_HI if info else AMBER_HI
            )
        threading.Thread(target=worker, daemon=True).start()

    def _calc_vol(self, symbol: str, margin: float, lev: int, price: float):
        """Convert margin/leverage/price into MEXC order volume (# of contracts).
        Returns a float vol respecting the contract's vol scale and min vol, or
        None if specs/price are missing."""
        info = self._contract_info.get(symbol)
        if not info or not price:
            return None
        cs = info.get("contractSize", 0)
        if not cs:
            return None
        raw   = (margin * lev) / (cs * price)
        scale = info.get("volScale", 0)
        vol   = round(raw, scale) if scale > 0 else float(int(raw))
        minv  = info.get("minVol", 0)
        if minv and vol < minv:
            vol = minv
        return vol if vol > 0 else None

    def _round_price(self, symbol: str, price: float) -> float:
        scale = self._contract_info.get(symbol, {}).get("priceScale", 6)
        return round(price, scale)

    @staticmethod
    def _order_ok(r) -> bool:
        """MEXC contract success: {"success":true,"code":0,"data":<orderId>}."""
        return isinstance(r, dict) and r.get("success") is True and not r.get("error")

    @staticmethod
    def _order_err(r) -> str:
        if not isinstance(r, dict):
            return str(r)
        return str(r.get("message") or r.get("msg") or r.get("error")
                   or f"code={r.get('code')}" or r)

    # ─────────────────────────── CHART LOADING ────────────────────────────────

    def _initial_chart_load(self):
        """Fetch klines for every asset once at startup so charts are populated
        immediately — independent of whether the bot has been started. Uses the
        chart-only worker so it never touches the bot's signal state."""
        self._scan_log.log("Loading charts…", BLUE_HI)
        for sym in TOP_ASSETS:
            worker = ChartWorker(sym, self._client)
            worker.signals.done.connect(self._on_chart_data)
            self._thread_pool.start(worker)

    def _refresh_visible_chart(self):
        """Reload klines for the currently selected asset chart only.

        Display-only: does not feed the scan pipeline, so switching tabs or
        timeframes can't influence the bot's signals or trading decisions.
        """
        tabs = getattr(self, "_asset_tabs", None)
        if not tabs:
            return
        w   = tabs.currentWidget()
        sym = getattr(w, "symbol", None)
        if not sym:
            return
        worker = ChartWorker(sym, self._client)
        worker.signals.done.connect(self._on_chart_data)
        self._thread_pool.start(worker)

    @pyqtSlot(str, list, list)
    def _on_chart_data(self, symbol: str, c1m: list, c5m: list):
        """Render fetched candles into the chart widget. Updates nothing else —
        no scan results, no signal scores, no scan log, no trades."""
        cw = self._chart_widgets.get(symbol)
        if cw and (c1m or c5m):
            cw.update_candles(c1m, c5m)
            cw.set_levels(self._chart_levels(symbol))

    def _chart_levels(self, symbol: str) -> list:
        """Entry / TP / SL prices of any open position(s) on this symbol, for the
        chart overlay. One per symbol (dedup), paper or live."""
        out = []
        if self._paper_mode:
            for p in self._paper_engine.positions:
                if p["symbol"] == symbol:
                    out.append({"entry": p["entry"], "tp": p["tp"],
                                "sl": p["sl"], "direction": p["direction"]})
        else:
            rec = self._live_mgr.state.get(symbol)
            if rec:
                out.append({"entry": rec["entry"], "tp": rec["tp"],
                            "sl": rec["sl"], "direction": rec["direction"]})
        return out

    def _open_chart(self, symbol: str):
        """Switch to the Charts tab and select the given asset's chart."""
        if symbol not in self._chart_widgets:
            return
        self._tabs.setCurrentIndex(0)            # Charts is the first tab
        try:
            self._asset_tabs.setCurrentIndex(TOP_ASSETS.index(symbol))
        except ValueError:
            pass

    def _on_sig_row_clicked(self, row: int, _col: int):
        item = self._sig_tbl.item(row, 0)
        if item:
            self._open_chart(item.data(Qt.UserRole) or f"{item.text()}_USDT")

    def _open_top_signal_chart(self):
        if self._top_signal_symbol:
            self._open_chart(self._top_signal_symbol)

    # ─────────────────────────── LIVE BALANCE ─────────────────────────────────

    def _fetch_live_balance(self):
        """Poll MEXC futures balance (live mode only). Runs off the UI thread."""
        if self._paper_mode:
            return
        cfg = self._settings.get_config()
        if not cfg["mexc_key"] or not cfg["mexc_secret"]:
            self._lbl_bal.setText("no keys")
            return
        # Ensure the client carries current credentials
        self._client = MexcClient(cfg["mexc_key"], cfg["mexc_secret"])
        self._live_mgr.set_client(self._client)
        worker = BalanceWorker(self._client)
        worker.signals.done.connect(self._on_balance)
        worker.signals.error.connect(self._on_balance_error)
        self._thread_pool.start(worker)

    @pyqtSlot(float, float)
    def _on_balance(self, bal: float, avail: float):
        self._live_balance = bal
        self._live_avail   = avail
        if not self._paper_mode:
            self._lbl_bal.setText(f"${bal:.2f}")
            self._lbl_avail.setText(f"${avail:.2f}")

    @pyqtSlot(str)
    def _on_balance_error(self, msg: str):
        self._scan_log.log(f"Balance fetch failed: {msg}", RED_HI)
        if not self._paper_mode and self._live_balance is None:
            self._lbl_bal.setText("err")

    def _seed_paper_balance(self):
        """Every fresh paper session starts from a fixed, known bankroll so test
        results are comparable run-to-run. (Previously seeded from the live
        account, which could be a few dollars and drove the balance negative.)"""
        if self._paper_trades or self._paper_engine.positions:
            return
        self._paper_engine.balance = PAPER_START_BALANCE
        self._scan_log.log(
            f"Paper session balance: ${PAPER_START_BALANCE:.2f}", BLUE_HI)

    def _tick_uptime(self):
        self._uptime_secs += 1
        h = self._uptime_secs // 3600
        m = (self._uptime_secs % 3600) // 60
        s = self._uptime_secs % 60
        self._lbl_uptime.setText(f"{h:02d}:{m:02d}:{s:02d}")

    # ─────────────────────────── BOT CONTROL ──────────────────────────────────

    def _start_bot(self):
        cfg = self._settings.get_config()
        apply_advanced_config(cfg)          # state-sync: push Advanced settings into the engine
        if not cfg["active_assets"]:
            QMessageBox.warning(self,"No Assets","Select at least one asset.")
            return

        self._client = MexcClient(cfg["mexc_key"], cfg["mexc_secret"])
        self._live_mgr.set_client(self._client)
        self._claude.set_key(cfg["claude_key"])
        if not self._claude.isRunning():
            self._claude.start()

        # Market-data WebSocket is connected on app open and kept alive; just
        # make sure it's up (no-op if already running).
        self._ensure_ws()

        # In paper mode, start the simulated balance from the real account so
        # results scale like live (no-op if no keys / session already underway).
        if self._paper_mode:
            self._seed_paper_balance()

        self._bot_running   = True
        self._session_start = time.time()
        self._uptime_secs   = 0
        self._uptime_timer.start()
        self._scan_timer.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._lbl_status.setText("● RUNNING")
        self._lbl_status.setStyleSheet(f"color:{GREEN_HI}; font-weight:bold;")
        self._scan_log.log("Bot started.", GREEN_HI)
        # Immediate first scan
        self._run_scan()

    def _stop_bot(self):
        self._bot_running = False
        self._scan_timer.stop()
        self._uptime_timer.stop()
        # Risk tick stays running so live positions keep their breakeven /
        # trailing protection after the bot is stopped.
        # Leave the market-data WebSocket running so charts, prices and open
        # positions keep updating after the bot is stopped.
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._lbl_status.setText("● STOPPED")
        self._lbl_status.setStyleSheet(f"color:{RED_HI}; font-weight:bold;")
        self._scan_log.log("Bot stopped.", AMBER_HI)

    def _set_mode(self, paper: bool):
        if paper == self._paper_mode:
            return   # no change
        self._paper_mode = paper
        self._btn_paper.setChecked(paper)
        self._btn_live.setChecked(not paper)
        # Repopulate trade history with the trades for the selected mode
        self._history_tbl.populate(
            self._paper_trades if paper else self._live_trades)
        if paper:
            self._lbl_mode.setText("● PAPER")
            self._lbl_mode.setStyleSheet(f"color:{AMBER_HI}; font-weight:bold;")
        else:
            self._lbl_mode.setText("● LIVE")
            self._lbl_mode.setStyleSheet(f"color:{RED_HI}; font-weight:bold;")
            # Pull the real futures balance straight away on switching to live
            self._live_balance = None
            self._lbl_bal.setText("…")
            self._fetch_live_balance()

    def _apply_settings(self):
        cfg = self._settings.get_config()
        apply_advanced_config(cfg)          # state-sync: live-apply Advanced settings
        self._claude.set_key(cfg["claude_key"])
        self._client = MexcClient(cfg["mexc_key"], cfg["mexc_secret"])
        self._live_mgr.set_client(self._client)

    # ─────────────────────────── WEBSOCKET ────────────────────────────────────

    def _ensure_ws(self):
        """Start (or keep alive) the public market-data WebSocket.

        Runs independently of the bot: subscribes to deal (trade) ticks for all
        assets so live prices flow as soon as the app opens. Klines/charts use
        REST to stay under MEXC's 30-subscription limit. No API keys needed.
        """
        if not HAS_WS:
            self._lbl_ws.setText("◉ WS: N/A")
            self._lbl_ws.setStyleSheet(f"color:{AMBER_HI};")
            self._scan_log.log(
                "WebSocket unavailable — install 'websocket-client' for live "
                "prices (pip install websocket-client).", AMBER_HI
            )
            return
        if self._ws_mgr and self._ws_mgr.isRunning():
            return
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
        ch = data.get("channel", "")
        d  = data.get("data")
        # push.deal payload is either a single deal dict or a list of deals.
        if "deal" in ch:
            deal = d[-1] if isinstance(d, list) and d else d
            if isinstance(deal, dict):
                price = deal.get("p") or deal.get("price")
                if price:
                    try:
                        self._cur_prices[symbol] = float(price)
                    except (TypeError, ValueError):
                        pass

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
        if not self._bot_running:
            return
        cfg = self._settings.get_config()

        # Engine selection: classic 7-signal (default) or the experimental
        # 26-indicator panel. The panel engine's enabled set / weights are
        # refreshed from the settings every cycle so UI edits apply live.
        engine = self._signal_engine
        if cfg.get("signal_engine") == "panel" and HAS_IND_LIB:
            self._panel_engine.enabled = cfg.get("ind_enabled", [])
            self._panel_engine.weights = cfg.get("ind_weights", {})
            engine = self._panel_engine

        eng_tag = "panel" if engine is self._panel_engine else "classic"
        self._scan_log.log(
            f"Scan cycle — {len(cfg['active_assets'])} assets [{eng_tag} engine]",
            BLUE_HI)
        for sym in cfg["active_assets"]:
            worker = ScanWorker(sym, self._client, engine,
                                cfg["dual_tf"], self._candle_cache)
            worker.signals.done.connect(self._on_scan_done)
            self._thread_pool.start(worker)

    @pyqtSlot(str, dict)
    def _on_scan_done(self, symbol: str, result: dict):
        self._scan_results[symbol] = result
        score  = result.get("score", 0)
        dirn   = result.get("direction","NONE")
        price  = result.get("price", 0)
        cfg    = self._settings.get_config()

        # NOTE: charts are driven by a separate, display-only pipeline
        # (ChartWorker / _on_chart_data). The scan handler deliberately does
        # NOT redraw charts, so the bot never swaps what the user is viewing.

        # Seed the live-price map from the scan so TP/SL checks and P&L work
        # even if the WebSocket is unavailable (WS just refreshes faster).
        if price > 0:
            self._cur_prices.setdefault(symbol, price)
            # Only let the slower REST price overwrite when WS isn't feeding.
            if not self._ws_connected:
                self._cur_prices[symbol] = price

        # Compute effective threshold
        threshold = cfg["threshold"]
        if cfg["adaptive"]:
            atr_pct = result.get("atr_pct", 0)
            wr = self._session_winrate()
            if atr_pct < 0.1:               # dead market
                threshold += 0.5
            elif atr_pct > 2.0:             # strong breakout
                threshold = max(threshold - 0.3, 1.0)
            if wr < 40 and len(self._full_trades()) >= 5:
                threshold += 0.3

        # Toggle ON = force overnight mode always; toggle OFF = auto by UTC time (22:00-07:00)
        if cfg["overnight"] or is_overnight():
            threshold = max(threshold - OVERNIGHT_THRESHOLD_DROP, 1.0)

        self._scan_log.log(
            f"{symbol}: score={score:.1f}/{threshold:.1f} {dirn} @ {price:.4f}",
            GREEN_HI if score >= threshold else TEXT_DIM
        )
        # "Last Sig" is set to the strongest signal in _refresh_ui (not the
        # last-scanned symbol), so nothing to update here.

        # Signal gate — only act on signals while the bot is running.
        # (Chart-load / idle scans reach here too and must not place trades.)
        if self._bot_running and score >= threshold and dirn != "NONE" and price > 0:
            self._execute_trade(symbol, dirn, price, score, cfg, result)

    def _open_symbols(self) -> set:
        """Symbols that currently have an open position (paper or live)."""
        if self._paper_mode:
            return {p["symbol"] for p in self._paper_engine.positions}
        # Live: managed state, plus orders just placed but not yet synced.
        return set(self._live_open_syms) | set(self._live_mgr.state.keys())

    def _is_chasing(self, symbol: str, direction: str, price: float, atr_pct: float):
        """Return a short reason string if this entry is 'chasing' an already-
        extended move (too far from EMA / spiked last candle / into a recent
        high), else '' . Uses cached 1m candles; never blocks if data is thin."""
        candles = (self._candle_cache.get(symbol, {}) or {}).get("1m") or []
        if len(candles) < 12:
            return ""                                  # not enough data — don't block
        atr = atr_pct if atr_pct and atr_pct > 0 else 0.3
        is_long = direction == "LONG"
        closes  = [c["c"] for c in candles]

        # 1) Stretched too far from the EMA in the trade direction
        ema = self._signal_engine.ema(closes, 9)
        if ema:
            e = ema[-1]
            dist = (price - e) / e * 100 * (1 if is_long else -1)
            if dist > ANTI_CHASE_EMA_ATR * atr:
                return f"price {dist:.2f}% beyond EMA (> {ANTI_CHASE_EMA_ATR}×ATR)"

        # 2) Last closed candle already spiked in the trade direction
        last = candles[-1]
        if last.get("o"):
            move = (last["c"] - last["o"]) / last["o"] * 100 * (1 if is_long else -1)
            if move > ANTI_CHASE_SPIKE_ATR * atr:
                return f"last candle spiked {move:.2f}% (> {ANTI_CHASE_SPIKE_ATR}×ATR)"

        # 3) Buying right into a recent high (or selling into a recent low)
        window = candles[-ANTI_CHASE_HIGH_LOOKBACK:]
        if is_long:
            hi = max(c["h"] for c in window)
            if price >= hi * (1 - 0.10 * atr / 100):   # within ~0.1×ATR of the high
                return "into recent high (resistance)"
        else:
            lo = min(c["l"] for c in window)
            if price <= lo * (1 + 0.10 * atr / 100):
                return "into recent low (support)"
        return ""

    def _execute_trade(self, symbol: str, direction: str, price: float,
                       score: float, cfg: dict, result: dict):
        # ── Position limits — the fix for dozens of duplicate, fee-bleeding trades ──
        open_syms = self._open_symbols()
        if symbol in open_syms:
            return                                   # one position per symbol — no stacking
        max_pos = cfg.get("max_positions", MAX_OPEN_POSITIONS)
        if len(open_syms) >= max_pos:
            self._scan_log.log(
                f"  ⊘ {symbol}: max positions ({max_pos}) reached — skipped", TEXT_DIM)
            return

        # ── Anti-chase: don't buy the top of a move (toggleable) ──
        if cfg.get("anti_chase", True):
            why = self._is_chasing(symbol, direction, price,
                                   result.get("atr_pct", 0.3))
            if why:
                self._scan_log.log(f"  ⊘ {symbol}: anti-chase — {why}, skipped", AMBER_HI)
                return

        # Determine leverage (cap to asset max)
        base_lev    = cfg["leverage"]
        max_lev     = ASSET_MAX_LEV.get(symbol, 100)
        lev         = min(base_lev, max_lev)
        margin      = cfg["margin"]
        tp_pct      = cfg["tp_pct"]
        sl_pct      = cfg["sl_pct"]
        atr_pct     = result.get("atr_pct", 0.3)

        # Warn in scan log if leverage was capped below what the user set
        if lev < base_lev:
            self._scan_log.log(
                f"  ⚡ {symbol}: leverage capped {base_lev}× → {lev}× (asset max)",
                AMBER_HI)

        # Respect the contract's own max leverage too, when specs are loaded.
        spec_max = self._contract_info.get(symbol, {}).get("maxLeverage", 0)
        if spec_max and lev > spec_max:
            self._scan_log.log(
                f"  ⚡ {symbol}: leverage capped {lev}× → {spec_max}× (contract spec)",
                AMBER_HI)
            lev = min(lev, spec_max)

        # ── AUTO TP/SL: fit the COIN'S volatility, bounded by leverage safety ──
        # Targets are sized to the asset's real ATR so they're actually hittable
        # (a calm coin like BNB gets a tight target, not a flat 1%). They are then
        # clamped: never below the fee floor (must clear costs), and never above
        # the leverage band (which keeps the SL safely inside liquidation at high
        # leverage). Manual TP/SL overrides are still respected.
        band = calc_smart_params(margin, symbol, leverage=lev)   # leverage ceiling
        atr = atr_pct if atr_pct and atr_pct > 0 else 0.3
        if cfg.get("tp_auto", True):
            tp_pct = round(min(band["tp_pct"], max(ATR_TP_FLOOR, atr * TP_ATR_MULT)), 3)
        if cfg.get("sl_auto", True):
            sl_pct = round(min(band["sl_pct"], max(ATR_SL_FLOOR, atr * SL_ATR_MULT)), 3)

        # Order size in CONTRACTS (vol). quantity = vol × contractSize.
        # Identical calc for paper and live so paper mirrors live sizing.
        vol = self._calc_vol(symbol, margin, lev, price)

        # One position per symbol (see dedup gate above) — never stack contracts.
        n_contracts = 1

        for i in range(n_contracts):
            tp_p = price * (1 + tp_pct/100) if direction == "LONG" else price * (1 - tp_pct/100)
            sl_p = price * (1 - sl_pct/100) if direction == "LONG" else price * (1 + sl_pct/100)
            tp_p = self._round_price(symbol, tp_p)
            sl_p = self._round_price(symbol, sl_p)
            order_type_label = "LIMIT(maker)"

            if self._paper_mode:
                # Simulate a realistic maker fill just inside the mid (0.05%).
                fill_offset = price * 0.0005
                limit_price = (price - fill_offset) if direction == "LONG" else (price + fill_offset)
                limit_price = self._round_price(symbol, limit_price)
                pos = self._paper_engine.place(symbol, direction, limit_price,
                                               margin, lev, tp_pct, sl_pct,
                                               vol=vol, atr_pct=atr_pct)
                if pos is None:
                    self._scan_log.log(
                        f"  ⊘ {symbol}: insufficient paper balance "
                        f"(${self._paper_engine.balance:.2f}) — skipped", TEXT_DIM)
                    return
                trade_id   = pos["id"]
                fill_price = limit_price
            else:
                if vol is None:
                    self._scan_log.log(
                        f"  ✗ {symbol}: missing contract spec/price — cannot size "
                        f"order safely, skipped.", RED_HI)
                    return
                # Gate on available live balance — don't send orders MEXC will reject
                if self._live_balance is not None and self._live_balance < margin:
                    self._scan_log.log(
                        f"  ⊘ {symbol}: insufficient live balance "
                        f"(${self._live_balance:.2f} < ${margin:.2f} margin) — skipped",
                        AMBER_HI)
                    return
                side = 1 if direction == "LONG" else 3

                # ── MAKER-FIRST LIMIT ORDER STRATEGY ────────────────────────
                # Place limit just inside the spread so it rests as a maker
                # order (0.04% fee vs 0.06% taker). Tighten offset when volatile.
                spread_offset_pct = max(0.01, min(0.05, atr_pct * 0.05))
                if direction == "LONG":
                    limit_price = self._round_price(symbol, price * (1 - spread_offset_pct / 100))
                else:
                    limit_price = self._round_price(symbol, price * (1 + spread_offset_pct / 100))

                # MEXC needs leverage set for the (isolated) position first.
                self._client.set_leverage(symbol, lev)

                # ── DISASTER-FLOOR server stops ─────────────────────────────
                # The bot manages the tight tp_pct/sl_pct client-side (breakeven,
                # partial, trailing). The server only carries WIDER stops as a
                # safety net that survives app/network death — the bot's virtual
                # stop always sits closer to price and fires first while alive.
                safe_tp_pct = tp_pct * SAFETY_TP_MULT
                safe_sl_pct = sl_pct * SAFETY_SL_MULT
                safe_tp = price * (1 + safe_tp_pct/100) if direction == "LONG" else price * (1 - safe_tp_pct/100)
                safe_sl = price * (1 - safe_sl_pct/100) if direction == "LONG" else price * (1 + safe_sl_pct/100)
                safe_tp = self._round_price(symbol, safe_tp)
                safe_sl = self._round_price(symbol, safe_sl)

                self._scan_log.log(
                    f"  → LIMIT {direction} {symbol} {vol} cont @ {limit_price} "
                    f"(mid={price:.4f}, off={spread_offset_pct:.3f}%) "
                    f"safetyTP={safe_tp_pct:.2f}% safetySL={safe_sl_pct:.2f}%",
                    BLUE_HI
                )

                r = self._client.place_order(
                    symbol, side, limit_price, vol, lev,
                    order_type=1,   # 1 = limit (maker)
                    take_profit=safe_tp, stop_loss=safe_sl
                )
                if not self._order_ok(r):
                    self._scan_log.log(
                        f"  ✗ ORDER REJECTED {symbol}: {self._order_err(r)}", RED_HI)
                    return
                order_id = str(r.get("data", "?"))
                trade_id = order_id
                fill_price = limit_price

                # Mark the symbol busy immediately so the next scan cycle won't
                # re-enter it before the 2 s position sync sees the fill.
                self._live_open_syms.add(symbol)

                # Hand the tight, real targets to the live manager — it drives
                # breakeven / partial / trailing off the actual filled position.
                self._live_mgr.register(symbol, direction, tp_pct, sl_pct, atr_pct)

                # ── FILL WATCHER: fallback to market after 8 s if unfilled ──
                def _watch_fill(oid=order_id, sym=symbol, s=side, v=vol,
                                lev_=lev, tp=safe_tp, sl=safe_sl, dir_=direction):
                    time.sleep(8)
                    try:
                        od = self._client.get_order(oid)
                        state = od.get("data", {}).get("state", -1)
                        # state 2=filled, 4=cancelled; 1=partial, 0=pending
                        if state not in (2,):
                            self._client.cancel_order(oid, sym)
                            # Fallback: market order (taker)
                            self._client.place_order(
                                sym, s, 0, v, lev_,
                                order_type=5,   # 5 = market (taker)
                                take_profit=tp, stop_loss=sl
                            )
                            self._scan_log.log(
                                f"  → LIMIT unfilled → MARKET fallback {dir_} {sym}",
                                AMBER_HI
                            )
                    except Exception as e:
                        self._scan_log.log(f"  → Fill watcher error: {e}", RED_HI)

                threading.Thread(target=_watch_fill, daemon=True).start()

            notional = margin * lev
            est_fee  = notional * ROUND_TRIP_FEE   # both legs
            lev_note = f"{lev}x" if lev == base_lev else f"{lev}x (capped from {base_lev}x)"
            self._scan_log.log(
                f"TRADE {'[x2]' if n_contracts>1 else ''} {order_type_label} "
                f"{direction} {symbol} @ {fill_price} vol={vol} "
                f"lev={lev_note} margin=${margin} TP={tp_pct}% SL={sl_pct}% "
                f"est_fee=${est_fee:.3f}",
                GREEN_HI
            )

            # Queue Claude analysis with richer context
            ctx = {
                "symbol": symbol, "direction": direction,
                "entry_price": fill_price, "mid_price": price,
                "score": score, "leverage": lev, "margin": margin,
                "tp_pct": tp_pct, "sl_pct": sl_pct, "vol": vol,
                "signals": result.get("signals", []),
                "atr_pct": atr_pct,
                "rsi": result.get("rsi", 50),
                "order_type": order_type_label,
                "est_fee_usd": round(est_fee, 4),
                "notional_usd": round(notional, 2),
                "tp_price": round(fill_price*(1+tp_pct/100) if direction=="LONG" else fill_price*(1-tp_pct/100), 4),
                "sl_price": round(fill_price*(1-sl_pct/100) if direction=="LONG" else fill_price*(1+sl_pct/100), 4),
                "net_profit_if_tp": round(notional * (tp_pct/100) - est_fee, 4),
                "max_loss_if_sl":   round(notional * (sl_pct/100) + est_fee/2, 4),
            }
            self._claude.enqueue(f"{symbol}-{trade_id}", ctx)

    # ─────────────────────────── RISK LIFECYCLE ───────────────────────────────

    def _log_risk(self, msg: str, color: str = None):
        """Log callback handed to the LiveManager (scan log may not exist yet)."""
        if getattr(self, "_scan_log", None):
            self._scan_log.log(msg, color or BLUE_HI)

    def _risk_tick(self):
        """1 Hz dispatcher. Paper runs only while the bot is active; live
        position management runs whenever there are positions, even if stopped."""
        if self._paper_mode:
            if self._bot_running:
                self._check_paper_tpsl()
        else:
            self._manage_live_positions()

    def _book_event(self, ev: dict):
        """Record one realized event (partial or full) into history + session."""
        if self._paper_mode:
            self._paper_trades.append(ev)
        else:
            self._live_trades.append(ev)
        self._history_tbl.add_trade(ev)
        pnl   = ev.get("pnl_usd", 0)
        label = "PARTIAL" if ev.get("partial") else "CLOSED"
        self._scan_log.log(
            f"{label} {ev['symbol']} {ev['direction']} "
            f"reason={ev['reason']} pnl={fmt_pnl(pnl)}",
            GREEN_HI if pnl >= 0 else RED_HI
        )
        # On a full close, move the AI analysis entry from LIVE → HISTORY
        if not ev.get("partial"):
            sym = ev.get("symbol", "")
            # Find the matching active trade_id by symbol prefix
            for tid in list(self._ai_tab._active_ids):
                if tid.startswith(sym + "-") or tid == sym:
                    self._ai_tab.mark_closed(tid)
                    break

    def _check_paper_tpsl(self):
        for ev in self._paper_engine.update_prices(self._cur_prices):
            self._book_event(ev)

    def _manage_live_positions(self):
        """Drive breakeven / partial / trailing on real MEXC positions and keep
        the normalized list the UI renders from. Polls open_positions every ~2s
        to stay well within MEXC's private-endpoint rate limits (the server-side
        safety stop is the backstop between polls)."""
        self._live_poll_ctr = getattr(self, "_live_poll_ctr", 0) + 1
        if self._live_poll_ctr % 2:
            return
        norm, events = self._live_mgr.sync_and_manage(self._cur_prices)
        self._live_positions = norm
        # Reconcile the dedup set to the exchange's truth (drops filled/closed
        # ghosts and any rejected orders that never became positions).
        self._live_open_syms = set(self._live_mgr.state.keys())
        for ev in events:
            self._book_event(ev)

    # ─────────────────────────── MANUAL OPS ───────────────────────────────────

    def _manual_close(self, pos_id: str, symbol: str, price: float):
        if self._paper_mode:
            self._paper_engine.close_manual(pos_id, price)
            self._scan_log.log(f"Manual close {symbol} @ {price:.4f}", AMBER_HI)
        else:
            # Find the live position and close the full remaining size with a
            # reduce-only market order (correct side for LONG or SHORT).
            pos = next((p for p in self._client.get_positions()
                        if str(p.get("positionId",""))==pos_id or p.get("symbol")==symbol), None)
            if pos:
                direction = "LONG" if pos.get("positionType") == 1 else "SHORT"
                vol = pos.get("holdVol") or pos.get("vol", 1)
                r = self._client.market_close(symbol, direction, int(vol),
                                              str(pos.get("positionId","")))
                ok = isinstance(r, dict) and (r.get("success") or r.get("code") == 0)
                self._scan_log.log(
                    f"Manual close {symbol} {direction} vol={int(vol)} "
                    f"{'sent' if ok else 'REJECTED: '+str(r)}",
                    AMBER_HI if ok else RED_HI)
                self._live_mgr.state.pop(symbol, None)

    def _manual_hedge(self, pos_id: str, symbol: str, price: float):
        # Open opposite position at 50% of original margin, scaled by ATR
        pos = next((p for p in self._paper_engine.positions if p["id"]==pos_id), None)
        if not pos:
            return
        atr_pct = self._scan_results.get(symbol,{}).get("atr_pct", 0.5)
        hedge_ratio = min(0.5, max(0.2, atr_pct / 2))  # dynamic, not hardcoded
        hedge_margin = pos["margin"] * hedge_ratio
        opp_dir = "SHORT" if pos["direction"]=="LONG" else "LONG"
        if self._paper_mode:
            cfg = self._settings.get_config()
            self._paper_engine.place(symbol, opp_dir, price, hedge_margin,
                                     pos["leverage"], cfg["tp_pct"], cfg["sl_pct"])
            self._scan_log.log(
                f"HEDGE {opp_dir} {symbol} @ {price:.4f} margin=${hedge_margin:.1f} "
                f"({hedge_ratio*100:.0f}% of original)",
                AMBER_HI
            )

    # ─────────────────────────── CLAUDE CALLBACK ──────────────────────────────

    @pyqtSlot(str, str)
    def _on_claude_done(self, trade_id: str, analysis: str):
        self._ai_tab.add_analysis(trade_id, analysis)
        try:
            parsed = json.loads(analysis)
        except Exception:
            return
        # Ongoing-management verdicts carry an "action" — route them separately.
        if "action" in parsed:
            self._apply_management(trade_id, parsed)
            return
        # Apply dynamic TP/SL adjustments if Claude says so
        try:
            sym = trade_id.split("-")[0]
            for pos in self._paper_engine.positions:
                if pos["symbol"] == sym and trade_id.split("-")[1] in pos["id"]:
                    tp_adj = parsed.get("tp_adj","keep")
                    sl_adj = parsed.get("sl_adj","keep")
                    if tp_adj != "keep":
                        adj = float(tp_adj)
                        if pos["direction"]=="LONG":
                            pos["tp"] *= (1 + adj/100)
                        else:
                            pos["tp"] *= (1 - adj/100)
                    if sl_adj != "keep":
                        adj = float(sl_adj)
                        if pos["direction"]=="LONG":
                            pos["sl"] *= (1 - adj/100)
                        else:
                            pos["sl"] *= (1 + adj/100)
                    # Hedge recommendation
                    if parsed.get("hedge") and not (cfg.get("overnight") or is_overnight()):
                        price = self._cur_prices.get(sym, pos["entry"])
                        self._manual_hedge(pos["id"], sym, price)
            # Claude can nudge global TP/SL for next trades (if AUTO mode on)
            if "suggested_tp" in parsed or "suggested_sl" in parsed or "suggested_lev" in parsed:
                self._settings.apply_claude_override(
                    leverage=parsed.get("suggested_lev"),
                    tp_pct=parsed.get("suggested_tp"),
                    sl_pct=parsed.get("suggested_sl"),
                )
                self._live_sidebar._pull_from_main()
        except:
            pass

    # ─────────────────── ONGOING AI TRADE MANAGEMENT ──────────────────────────

    def _run_manage_checks(self):
        """Ask Claude to re-evaluate open positions on an ADAPTIVE cadence — each
        position carries its own interval (20s near TP/SL, up to 90s when quiet).
        The timer ticks fast; this gates which positions are actually due."""
        if not self._settings.get_config().get("claude_key"):
            return
        now  = time.time()
        last = getattr(self, "_manage_last", None)
        if last is None:
            last = self._manage_last = {}
        contexts = self._manage_contexts()
        live = {c["_tid"] for c in contexts}
        for ctx in contexts:
            tid = ctx["_tid"]
            if now - last.get(tid, 0.0) >= ctx["interval"]:
                self._claude.enqueue(tid, ctx)
                last[tid] = now
        for tid in list(last):          # forget closed positions
            if tid not in live:
                last.pop(tid, None)

    def _manage_contexts(self) -> list:
        """Build a management context for every open position (paper or live)."""
        out = []
        now = time.time()
        if self._paper_mode:
            items = [(p["symbol"], p["id"], p["direction"], p["entry"],
                      p["tp"], p["sl"], p["margin"], p["leverage"],
                      p.get("opened_at", "")) for p in self._paper_engine.positions]
        else:
            items = [(s, r.get("pos_id", s), r["direction"], r["entry"],
                      r["tp"], r["sl"], r.get("margin", 0), r.get("leverage", 1),
                      r.get("opened_at", "")) for s, r in self._live_mgr.state.items()]
        for sym, pid, dirn, entry, tp, sl, margin, lev, opened in items:
            price = self._cur_prices.get(sym, entry)
            if not entry or not price:
                continue
            move = ((price - entry) / entry) * (1 if dirn == "LONG" else -1)
            net_pct = move * 100 * lev - ROUND_TRIP_FEE * 100 * lev
            age_min = self._age_minutes(opened, now)
            sc = self._scan_results.get(sym, {})

            # ── Adaptive cadence: re-check faster the closer price is to a
            # decision point (TP or SL), slower when it's sitting mid-range. ──
            span_tp = tp - entry
            span_sl = sl - entry
            prog_tp = (price - entry) / span_tp if span_tp else 0.0
            prog_sl = (price - entry) / span_sl if span_sl else 0.0
            proximity = max(prog_tp, prog_sl, 0.0)   # fraction toward nearest level
            if proximity >= 0.70:    interval = 20    # near TP/SL → watch closely
            elif proximity >= 0.40:  interval = 45
            else:                    interval = 90    # quiet → conserve API calls

            out.append({
                "mode": "manage", "_tid": f"{sym}-{pid}", "interval": interval,
                "symbol": sym, "direction": dirn, "leverage": lev,
                "margin": round(margin, 2), "entry_price": round(entry, 6),
                "current_price": round(price, 6),
                "unrealized_pnl_pct_margin": round(net_pct, 2),
                "unrealized_pnl_usd": round(margin * net_pct / 100, 4),
                "time_in_trade_min": age_min,
                "tp_price": round(tp, 6), "sl_price": round(sl, 6),
                "dist_to_tp_pct": round(abs(tp - price) / price * 100, 3),
                "dist_to_sl_pct": round(abs(price - sl) / price * 100, 3),
                "progress_to_nearest_level": round(proximity, 2),
                "current_score": sc.get("score", 0),
                "current_direction": sc.get("direction", "NONE"),
                "atr_pct": sc.get("atr_pct", 0), "rsi": sc.get("rsi", 50),
            })
        return out

    @staticmethod
    def _age_minutes(opened_iso: str, now_ts: float) -> float:
        try:
            t0 = datetime.fromisoformat(opened_iso).replace(tzinfo=timezone.utc).timestamp()
            return round(max(0.0, now_ts - t0) / 60, 1)
        except Exception:
            return 0.0

    def _apply_management(self, trade_id: str, parsed: dict):
        """Act on Claude's ongoing-trade verdict: close early, or retune TP/SL."""
        action = str(parsed.get("action", "HOLD")).upper()
        sym    = trade_id.split("-")[0]
        reason = str(parsed.get("reasoning", ""))[:90]
        price  = self._cur_prices.get(sym, 0)

        if self._paper_mode:
            pos = next((p for p in self._paper_engine.positions if p["symbol"] == sym), None)
            if not pos:
                return
            entry, direction, pid = pos["entry"], pos["direction"], pos["id"]
        else:
            rec = self._live_mgr.state.get(sym)
            if not rec:
                return
            entry, direction, pid = rec["entry"], rec["direction"], rec.get("pos_id", sym)

        if action == "CLOSE":
            self._scan_log.log(f"🤖 Claude CLOSE {sym}: {reason}", AMBER_HI)
            self._manual_close(pid, sym, price or entry)
            return

        # Retune TP/SL — distances are % FROM ENTRY (None = leave as-is).
        new_tp = parsed.get("new_tp_pct")
        new_sl = parsed.get("new_sl_pct")
        msg = []
        if new_tp is not None:
            try:
                tp_price = entry * (1 + float(new_tp)/100) if direction == "LONG" \
                           else entry * (1 - float(new_tp)/100)
                self._set_pos_level(sym, "tp", tp_price)
                msg.append(f"TP→{float(new_tp):.2f}%")
            except (TypeError, ValueError):
                pass
        if new_sl is not None:
            try:
                sl_price = entry * (1 - float(new_sl)/100) if direction == "LONG" \
                           else entry * (1 + float(new_sl)/100)
                self._set_pos_level(sym, "sl", sl_price)
                msg.append(f"SL→{float(new_sl):.2f}%")
            except (TypeError, ValueError):
                pass
        if msg:
            self._scan_log.log(f"🤖 Claude retune {sym}: {', '.join(msg)} — {reason}", BLUE_HI)

    def _set_pos_level(self, symbol: str, which: str, price: float):
        """Update a TP or SL price on the open position (paper or live mgr rec)."""
        if self._paper_mode:
            for p in self._paper_engine.positions:
                if p["symbol"] == symbol:
                    p[which] = price
        else:
            rec = self._live_mgr.state.get(symbol)
            if rec:
                rec[which] = price

    # ─────────────────────────── UI REFRESH ───────────────────────────────────

    def _mode_trades(self) -> list:
        """All realized trades for the current mode (paper or live)."""
        return self._paper_trades if self._paper_mode else self._live_trades

    def _full_trades(self) -> list:
        """Realized trades excluding partial bank-outs (one per position)."""
        return [t for t in self._mode_trades() if not t.get("partial")]

    def _session_winrate(self) -> float:
        full = self._full_trades()
        wins = sum(1 for t in full if t.get("pnl_usd", 0) > 0)
        return (wins / len(full) * 100) if full else 0

    def _refresh_ui(self):
        # Update signal score table — sorted strongest-first.
        cfg  = self._settings.get_config()
        thr  = cfg["threshold"]

        # Overnight-mode indicator: bright when the GMT window is live, dim when
        # the mode is merely enabled, hidden when off.
        if cfg.get("overnight"):
            self._lbl_overnight.setVisible(True)
            if is_overnight():
                self._lbl_overnight.setText("🌙 NIGHT ON")
                self._lbl_overnight.setStyleSheet(f"color:{BLUE_HI}; font-weight:bold;")
            else:
                self._lbl_overnight.setText("🌙 night")
                self._lbl_overnight.setStyleSheet(f"color:{TEXT_DIM};")
        else:
            self._lbl_overnight.setVisible(False)

        rows = [(sym, self._scan_results.get(sym, {}).get("score", 0),
                 self._scan_results.get(sym, {}).get("direction", "—"))
                for sym in TOP_ASSETS]
        rows.sort(key=lambda x: x[1], reverse=True)

        self._sig_tbl.setRowCount(len(rows))
        for r, (sym, score, dirn) in enumerate(rows):
            asset_item = QTableWidgetItem(sym.replace("_USDT", ""))
            asset_item.setData(Qt.UserRole, sym)
            self._sig_tbl.setItem(r, 0, asset_item)

            score_item = QTableWidgetItem(f"{score:.1f}")
            if score >= thr:
                score_item.setForeground(QColor(GREEN_HI))
            elif score >= thr * 0.8:
                score_item.setForeground(QColor(AMBER_HI))
            else:
                score_item.setForeground(QColor(TEXT_DIM))
            self._sig_tbl.setItem(r, 1, score_item)

            dir_item = QTableWidgetItem(dirn)
            if dirn == "LONG":
                dir_item.setForeground(QColor(GREEN_HI))
            elif dirn == "SHORT":
                dir_item.setForeground(QColor(RED_HI))
            self._sig_tbl.setItem(r, 2, dir_item)

        # "Last Sig" = strongest signal: highest score, preferring an actionable
        # direction (LONG/SHORT) over NONE.
        top = next((x for x in rows if x[2] in ("LONG", "SHORT")), rows[0] if rows else None)
        if top:
            self._top_signal_symbol = top[0]
            self._lbl_sig.setText(f"{top[0].replace('_USDT','')} {top[1]:.1f} {top[2]}")
            self._lbl_sig.setStyleSheet(
                f"font-size:13px; font-weight:bold; "
                f"color:{GREEN_HI if top[1] >= thr else TEXT_PRI};"
            )

        # P&L — realized (already baked into the balance) + open unrealised.
        # Keep them SEPARATE: equity must add only unrealised, since the paper
        # balance already reflects realized P&L (adding it again double-counts).
        realized = sum(t.get("pnl_usd",0) for t in self._mode_trades()
                       if not t.get("partial"))
        unreal = 0.0
        open_positions = self._paper_engine.positions if self._paper_mode else self._live_positions
        for pos in open_positions:
            sym    = pos.get("symbol","")
            price  = self._cur_prices.get(sym, pos.get("entry",0))
            entry  = pos.get("entry",0)
            lev    = pos.get("leverage",1)
            margin = pos.get("margin",0)
            if entry:
                dir_mul = 1 if pos.get("direction","LONG")=="LONG" else -1
                pnl_pct = (price - entry)/entry * dir_mul * lev * 100
                net_pct = pnl_pct - ROUND_TRIP_FEE * 100 * lev
                unreal += margin * net_pct / 100
        total_pnl = realized + unreal

        self._lbl_pnl.setText(fmt_pnl(total_pnl))
        self._lbl_pnl.setStyleSheet(
            f"font-size:13px; font-weight:bold; color:{'#00e676' if total_pnl>=0 else '#ff1744'};"
        )

        wr = self._session_winrate()
        self._lbl_wr.setText(f"{wr:.0f}%")
        self._lbl_trades.setText(str(len(self._full_trades())))

        # Reference bankroll for the Trade-History "Total %" figure.
        self._history_tbl._ref_balance = (
            PAPER_START_BALANCE if self._paper_mode
            else (self._live_balance or PAPER_START_BALANCE))

        # Balance — show total equity AND free/available side-by-side.
        if self._paper_mode:
            free     = self._paper_engine.balance               # cash (incl. realized)
            deployed = sum(p.get("margin", 0) for p in self._paper_engine.positions)
            equity   = free + deployed + unreal                 # add only UNREALISED
            self._lbl_bal.setText(f"${equity:.2f}")
            self._lbl_avail.setText(f"${free:.2f}")
        else:
            # Live: equity + availableBalance polled from MEXC futures.
            if self._live_balance is not None:
                self._lbl_bal.setText(f"${self._live_balance:.2f}")
            if self._live_avail is not None:
                self._lbl_avail.setText(f"${self._live_avail:.2f}")

        # Update positions panel (full tab) + the always-visible sidebar summary
        positions = self._paper_engine.positions if self._paper_mode else self._live_positions
        self._positions_panel.update_positions(positions, self._cur_prices)
        self._update_pos_sidebar(positions)

        # Keep the visible chart's entry/TP/SL overlay current (guarded so it
        # only redraws when the levels actually change — e.g. trailing SL moves).
        tabs = getattr(self, "_asset_tabs", None)
        if tabs:
            w   = tabs.currentWidget()
            sym = getattr(w, "symbol", None)
            if sym in self._chart_widgets:
                self._chart_widgets[sym].set_levels(self._chart_levels(sym))

    def _pos_full(self, pos: dict) -> dict:
        """Merge full detail for a position. Live normalized dicts lack TP/SL/
        open-time, so pull those from the live manager's state."""
        info = dict(pos)
        if not self._paper_mode:
            rec = self._live_mgr.state.get(pos.get("symbol"))
            if rec:
                info["tp"] = rec.get("tp")
                info["sl"] = rec.get("sl")
                info["opened_at"] = rec.get("opened_at", "")
        return info

    @staticmethod
    def _fmt_duration(opened_iso: str) -> str:
        try:
            t0 = datetime.fromisoformat(opened_iso).replace(tzinfo=timezone.utc).timestamp()
            secs = max(0, int(time.time() - t0))
        except Exception:
            return "—"
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        if h:   return f"{h}h {m}m"
        if m:   return f"{m}m {s:02d}s"
        return f"{s}s"

    @staticmethod
    def _fmt_open_time(opened_iso: str) -> str:
        try:
            return (datetime.fromisoformat(opened_iso)
                    .replace(tzinfo=timezone.utc).strftime("%H:%M:%S"))
        except Exception:
            return "—"

    def _build_pos_card(self, info: dict) -> dict:
        """One open-position card: symbol/dir/lev, P&L, entry, margin, TP/SL,
        open time + duration, and a Close button."""
        sym = info.get("symbol", ""); pid = str(info.get("id") or sym)
        dirc = info.get("direction", "?")
        dcol = GREEN_HI if dirc == "LONG" else RED_HI

        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame{{background:{DARK_CARD};border:1px solid {DARK_BORDER};border-radius:4px;}}"
            f"QFrame:hover{{border:1px solid {BLUE_HI};}}"
            f"QLabel{{border:0;}}")
        frame.setCursor(Qt.PointingHandCursor)
        frame.setToolTip(f"Click to open {sym.replace('_USDT','')} chart")
        # Click the card (anywhere but the Close button) to open its chart.
        frame.mousePressEvent = lambda _e, s=sym: self._open_chart(s)
        v = QVBoxLayout(frame)
        v.setContentsMargins(7, 5, 7, 5); v.setSpacing(2)

        # Row 1: symbol · dir · lev      |   P&L $
        r1 = QHBoxLayout(); r1.setSpacing(4)
        head = QLabel(f"{sym.replace('_USDT','')}  "
                      f"<span style='color:{dcol}'>{dirc}</span>  "
                      f"<span style='color:{TEXT_DIM}'>{info.get('leverage',1)}x</span>")
        head.setStyleSheet("font-weight:bold; font-size:11px;")
        pnl_usd = QLabel("—"); pnl_usd.setStyleSheet("font-weight:bold;")
        pnl_usd.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        r1.addWidget(head); r1.addStretch(); r1.addWidget(pnl_usd)
        v.addLayout(r1)

        # Row 2: P&L %                    |   [Close]
        r2 = QHBoxLayout(); r2.setSpacing(4)
        pnl_pct = QLabel("—")
        btn = QPushButton("✕ Close"); btn.setFixedHeight(20)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton{background:#3a1d24;border:1px solid #ff1744;color:#ff5a76;"
            "font-size:9px;border-radius:2px;padding:1px 6px;}"
            "QPushButton:hover{background:#ff1744;color:white;}")
        btn.clicked.connect(lambda _=False, p=pid, s=sym: self._close_from_card(p, s))
        r2.addWidget(pnl_pct); r2.addStretch(); r2.addWidget(btn)
        v.addLayout(r2)

        def small(text):
            l = QLabel(text); l.setStyleSheet(f"color:{TEXT_SEC}; font-size:9px;"); return l

        entry = info.get("entry", 0); margin = info.get("margin", 0)
        v.addWidget(small(f"Entry {entry:.4f}   ·   Mgn ${margin:.1f}"))
        tp_lbl = small(f"TP {info.get('tp') or 0:.4f}")
        sl_lbl = small(f"SL {info.get('sl') or 0:.4f}")
        rtp = QHBoxLayout(); rtp.setSpacing(4)
        tp_lbl.setStyleSheet(f"color:{GREEN_HI}; font-size:9px;")
        sl_lbl.setStyleSheet(f"color:{RED_HI}; font-size:9px;")
        rtp.addWidget(tp_lbl); rtp.addStretch(); rtp.addWidget(sl_lbl)
        v.addLayout(rtp)
        dur_lbl = small(f"Open {self._fmt_open_time(info.get('opened_at',''))}  ·  —")
        v.addWidget(dur_lbl)

        return {"frame": frame, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
                "tp": tp_lbl, "sl": sl_lbl, "dur": dur_lbl}

    def _rebuild_pos_cards(self, positions: list):
        for card in self._pos_cards.values():
            card["frame"].setParent(None)
        self._pos_cards.clear()
        self._pos_empty.setVisible(not positions)
        for pos in positions:
            info = self._pos_full(pos)
            card = self._build_pos_card(info)
            key  = str(pos.get("id") or pos.get("symbol"))
            self._pos_cards[key] = card
            # insert before the trailing stretch
            self._pos_cards_layout.insertWidget(
                self._pos_cards_layout.count() - 1, card["frame"])

    def _close_from_card(self, pid: str, symbol: str):
        price = self._cur_prices.get(symbol, 0)
        self._manual_close(pid, symbol, price)

    def _update_pos_sidebar(self, positions: list):
        """Open-position cards in the always-visible sidebar — full detail
        (margin, entry, TP/SL, open time, duration, live P&L) + a Close button.
        Rebuilds only when the set of positions changes; otherwise updates the
        live fields in place."""
        keys = [str(p.get("id") or p.get("symbol")) for p in positions]
        if keys != self._pos_card_keys:
            self._rebuild_pos_cards(positions)
            self._pos_card_keys = keys

        for pos in positions:
            key  = str(pos.get("id") or pos.get("symbol"))
            card = self._pos_cards.get(key)
            if not card:
                continue
            info  = self._pos_full(pos)
            sym   = info.get("symbol", "")
            entry = info.get("entry", 0)
            price = self._cur_prices.get(sym, entry)
            dirc  = info.get("direction", "?")
            lev   = info.get("leverage", 1)
            margin= info.get("margin", 0)
            net_pct = (((price-entry)/entry*100)*(1 if dirc=="LONG" else -1)*lev
                       - ROUND_TRIP_FEE*100*lev) if entry else 0
            net_usd = margin * net_pct / 100
            col = GREEN_HI if net_usd >= 0 else RED_HI
            card["pnl_usd"].setText(fmt_pnl(net_usd))
            card["pnl_usd"].setStyleSheet(f"color:{col}; font-weight:bold;")
            card["pnl_pct"].setText(fmt_pct(net_pct))
            card["pnl_pct"].setStyleSheet(f"color:{col}; font-size:11px;")
            if info.get("tp"):
                card["tp"].setText(f"TP {info['tp']:.4f}")
            if info.get("sl"):
                card["sl"].setText(f"SL {info['sl']:.4f}")
            card["dur"].setText(
                f"Open {self._fmt_open_time(info.get('opened_at',''))}  ·  "
                f"{self._fmt_duration(info.get('opened_at',''))}")

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def main():
    if not HAS_PYQT:
        print("Install PyQt5 and pyqtgraph first:\n  pip install PyQt5 pyqtgraph websocket-client anthropic requests")
        sys.exit(1)

    # High-DPI support MUST be set before QApplication is created
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
