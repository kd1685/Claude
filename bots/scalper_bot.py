#!/usr/bin/env python3
"""
MEXC Futures Scalping Bot
Requires: pip install PyQt5 pyqtgraph websocket-client requests

Usage:
  GUI mode (Windows):  python scalper_bot.py
  Headless mode (VPS): python scalper_bot.py --headless
"""

import sys, os, json, time, hmac, hashlib, threading, argparse, logging
import requests
from datetime import datetime
from collections import deque

# ── CLI args ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--headless', action='store_true', help='Run without GUI')
parser.add_argument('--symbol', default='BTC_USDT', help='Futures symbol')
parser.add_argument('--leverage', type=int, default=5)
parser.add_argument('--max-pos', type=float,
                    default=float(os.getenv('MAX_POSITION_USDT', 100)))
args = parser.parse_args()

HEADLESS = args.headless
SYMBOL   = args.symbol
LEVERAGE = args.leverage
MAX_POS  = args.max_pos

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('scalper')

# ── MEXC REST helpers ────────────────────────────────────────────────────────
BASE = 'https://contract.mexc.com'

class MexcClient:
    def __init__(self, api_key: str, api_secret: str):
        self.key    = api_key
        self.secret = api_secret
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def _sign(self, params: dict) -> dict:
        ts = str(int(time.time() * 1000))
        params['timestamp'] = ts
        params['api_key']   = self.key
        sorted_params = sorted(params.items())
        query = '&'.join(f'{k}={v}' for k, v in sorted_params)
        sig = hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params['sign'] = sig
        return params

    def get_account(self):
        params = self._sign({})
        r = self.session.get(f'{BASE}/api/v1/private/account/assets', params=params)
        r.raise_for_status()
        return r.json()

    def set_leverage(self, symbol: str, leverage: int, side: int = 1):
        """side: 1=long, 2=short, 3=both"""
        data = self._sign({'symbol': symbol, 'leverage': leverage, 'openType': 1, 'positionType': side})
        r = self.session.post(f'{BASE}/api/v1/private/position/change_leverage', json=data)
        return r.json()

    def place_order(self, symbol: str, side: int, vol: float,
                    order_type: int = 5, price: float = 0.0):
        """
        side:  1=open_long 2=close_short 3=open_short 4=close_long
        type:  1=limit 5=market
        vol:   quantity in contracts
        """
        data = {
            'symbol':    symbol,
            'side':      side,
            'openType':  1,          # isolated
            'type':      order_type,
            'vol':       vol,
            'leverage':  LEVERAGE,
        }
        if order_type == 1:
            data['price'] = price
        data = self._sign(data)
        r = self.session.post(f'{BASE}/api/v1/private/order/submit', json=data)
        r.raise_for_status()
        return r.json()

    def get_open_positions(self, symbol: str):
        params = self._sign({'symbol': symbol})
        r = self.session.get(f'{BASE}/api/v1/private/position/open_positions', params=params)
        r.raise_for_status()
        return r.json().get('data', [])

    def close_position(self, symbol: str, pos: dict):
        side  = 4 if pos['positionType'] == 1 else 2   # close long / close short
        vol   = pos['holdVol']
        return self.place_order(symbol, side, vol)

    def get_ticker(self, symbol: str) -> float:
        r = self.session.get(f'{BASE}/api/v1/contract/ticker?symbol={symbol}')
        r.raise_for_status()
        data = r.json().get('data', {})
        return float(data.get('lastPrice', 0))


# ── Strategy ─────────────────────────────────────────────────────────────────

class ScalpStrategy:
    """
    Simple momentum scalp:
    - Keep a rolling window of recent prices.
    - If price moves up  > THRESH % in WINDOW ticks → open long.
    - If price moves down > THRESH % in WINDOW ticks → open short.
    - Exit when P&L reaches TP or SL (in %).
    """
    WINDOW = 20        # ticks
    THRESH = 0.05      # 0.05 % move to trigger entry
    TP     = 0.15      # take-profit %
    SL     = 0.10      # stop-loss %

    def __init__(self, client: MexcClient, symbol: str):
        self.client  = client
        self.symbol  = symbol
        self.prices  = deque(maxlen=self.WINDOW)
        self.in_pos  = False
        self.entry   = 0.0
        self.pos_side = None   # 'long' | 'short'

    def on_tick(self, price: float):
        self.prices.append(price)
        if self.in_pos:
            self._check_exit(price)
        elif len(self.prices) == self.WINDOW:
            self._check_entry(price)

    def _pct(self, a, b):
        return (b - a) / a * 100

    def _check_entry(self, price: float):
        old = self.prices[0]
        move = self._pct(old, price)
        if move > self.THRESH:
            self._enter('long', price)
        elif move < -self.THRESH:
            self._enter('short', price)

    def _enter(self, side: str, price: float):
        contracts = max(1, int(MAX_POS / price))
        mexc_side = 1 if side == 'long' else 3
        try:
            self.client.place_order(self.symbol, mexc_side, contracts)
            self.in_pos   = True
            self.entry    = price
            self.pos_side = side
            log.info('ENTER %s @ %.4f  contracts=%d', side.upper(), price, contracts)
        except Exception as e:
            log.error('Entry failed: %s', e)

    def _check_exit(self, price: float):
        pnl = self._pct(self.entry, price)
        if self.pos_side == 'short':
            pnl = -pnl
        if pnl >= self.TP:
            self._exit(price, 'TP')
        elif pnl <= -self.SL:
            self._exit(price, 'SL')

    def _exit(self, price: float, reason: str):
        try:
            positions = self.client.get_open_positions(self.symbol)
            for pos in positions:
                self.client.close_position(self.symbol, pos)
            log.info('EXIT  %s @ %.4f  reason=%s', self.pos_side.upper(), price, reason)
        except Exception as e:
            log.error('Exit failed: %s', e)
        finally:
            self.in_pos   = False
            self.pos_side = None
            self.entry    = 0.0


# ── WebSocket feed ───────────────────────────────────────────────────────────

def _ws_thread(strategy: ScalpStrategy, price_cb):
    import websocket
    WS_URL = 'wss://contract.mexc.com/edge'

    def on_open(ws):
        sub = json.dumps({'method': 'sub.ticker', 'param': {'symbol': SYMBOL}})
        ws.send(sub)
        log.info('WebSocket subscribed to %s ticker', SYMBOL)

    def on_message(ws, msg):
        try:
            data = json.loads(msg)
            if data.get('channel') == 'push.ticker':
                price = float(data['data']['lastPrice'])
                price_cb(price)
                strategy.on_tick(price)
        except Exception as e:
            log.debug('WS parse error: %s', e)

    def on_error(ws, err):
        log.error('WS error: %s', err)

    def on_close(ws, *_):
        log.warning('WS closed — reconnecting in 5 s')
        time.sleep(5)
        _ws_thread(strategy, price_cb)   # reconnect

    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever(ping_interval=20, ping_timeout=10)


# ── Headless main ─────────────────────────────────────────────────────────────

def run_headless(client: MexcClient):
    log.info('Starting scalper in HEADLESS mode  symbol=%s  leverage=%d  max_pos=%.0f',
             SYMBOL, LEVERAGE, MAX_POS)
    client.set_leverage(SYMBOL, LEVERAGE)
    strategy = ScalpStrategy(client, SYMBOL)

    def price_cb(p):
        pass  # headless: strategy.on_tick already called in _ws_thread

    t = threading.Thread(target=_ws_thread, args=(strategy, price_cb), daemon=True)
    t.start()
    try:
        while True:
            time.sleep(60)
            log.info('Heartbeat — in_pos=%s', strategy.in_pos)
    except KeyboardInterrupt:
        log.info('Shutting down')


# ── PyQt5 GUI ─────────────────────────────────────────────────────────────────

def run_gui(client: MexcClient):
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox, QSplitter,
    )
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
    from PyQt5.QtGui import QFont, QColor, QPalette
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True)

    class Signals(QObject):
        price_updated = pyqtSignal(float)
        log_message   = pyqtSignal(str)

    signals = Signals()
    strategy = ScalpStrategy(client, SYMBOL)

    # ── price chart data ────────────────────────────────────────────────────
    MAX_CHART = 300
    price_history: deque = deque(maxlen=MAX_CHART)
    time_history:  deque = deque(maxlen=MAX_CHART)
    t0 = time.time()

    def price_cb(p: float):
        price_history.append(p)
        time_history.append(time.time() - t0)
        signals.price_updated.emit(p)

    # Monkey-patch strategy to also emit log messages
    _orig_enter = strategy._enter
    _orig_exit  = strategy._exit

    def patched_enter(side, price):
        _orig_enter(side, price)
        signals.log_message.emit(f'ENTER {side.upper()} @ {price:.4f}')
    def patched_exit(price, reason):
        _orig_exit(price, reason)
        signals.log_message.emit(f'EXIT  {strategy.pos_side or ""} @ {price:.4f}  [{reason}]')

    strategy._enter = patched_enter
    strategy._exit  = patched_exit

    # ── build UI ─────────────────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Dark palette
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(30, 30, 30))
    pal.setColor(QPalette.WindowText,      QColor(220, 220, 220))
    pal.setColor(QPalette.Base,            QColor(20, 20, 20))
    pal.setColor(QPalette.AlternateBase,   QColor(40, 40, 40))
    pal.setColor(QPalette.Text,            QColor(220, 220, 220))
    pal.setColor(QPalette.Button,          QColor(50, 50, 50))
    pal.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
    pal.setColor(QPalette.Highlight,       QColor(0, 120, 215))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(pal)

    win = QMainWindow()
    win.setWindowTitle(f'Ascent Scalper — {SYMBOL}')
    win.resize(1100, 700)

    central = QWidget()
    win.setCentralWidget(central)
    root_layout = QVBoxLayout(central)

    # ── top bar ──────────────────────────────────────────────────────────────
    top = QHBoxLayout()
    price_label = QLabel('Price: --')
    price_label.setFont(QFont('Consolas', 18, QFont.Bold))
    price_label.setStyleSheet('color: #00e5ff;')

    status_label = QLabel('Status: idle')
    status_label.setFont(QFont('Consolas', 12))
    status_label.setStyleSheet('color: #aaa;')

    btn_start = QPushButton('▶  Start')
    btn_stop  = QPushButton('■  Stop')
    btn_stop.setEnabled(False)

    for btn in (btn_start, btn_stop):
        btn.setFixedHeight(34)
        btn.setFont(QFont('Consolas', 11))

    top.addWidget(price_label)
    top.addStretch()
    top.addWidget(status_label)
    top.addSpacing(20)
    top.addWidget(btn_start)
    top.addWidget(btn_stop)
    root_layout.addLayout(top)

    # ── splitter: chart | log ────────────────────────────────────────────────
    splitter = QSplitter(Qt.Horizontal)

    chart_widget = pg.PlotWidget(title='Live Price')
    chart_widget.setBackground('#1a1a1a')
    chart_widget.showGrid(x=True, y=True, alpha=0.2)
    price_curve = chart_widget.plot(pen=pg.mkPen('#00e5ff', width=1.5))
    splitter.addWidget(chart_widget)

    log_box = QTextEdit()
    log_box.setReadOnly(True)
    log_box.setFont(QFont('Consolas', 9))
    log_box.setStyleSheet('background:#111; color:#ccc; border:none;')
    splitter.addWidget(log_box)
    splitter.setSizes([750, 350])

    root_layout.addWidget(splitter, stretch=1)

    # ── bottom: params ───────────────────────────────────────────────────────
    params_box = QGroupBox('Parameters')
    params_layout = QHBoxLayout(params_box)

    def _param(label, value):
        lbl = QLabel(label)
        lbl.setStyleSheet('color:#aaa;')
        edit = QLineEdit(str(value))
        edit.setFixedWidth(80)
        edit.setStyleSheet('background:#2a2a2a; color:#eee; border:1px solid #444;')
        params_layout.addWidget(lbl)
        params_layout.addWidget(edit)
        return edit

    e_window = _param('Window', ScalpStrategy.WINDOW)
    e_thresh = _param('Thresh %', ScalpStrategy.THRESH)
    e_tp     = _param('TP %',     ScalpStrategy.TP)
    e_sl     = _param('SL %',     ScalpStrategy.SL)
    e_maxpos = _param('Max USDT', int(MAX_POS))
    params_layout.addStretch()

    def apply_params():
        try:
            ScalpStrategy.WINDOW = int(e_window.text())
            ScalpStrategy.THRESH = float(e_thresh.text())
            ScalpStrategy.TP     = float(e_tp.text())
            ScalpStrategy.SL     = float(e_sl.text())
            global MAX_POS
            MAX_POS = float(e_maxpos.text())
            log_box.append('↺ Parameters updated')
        except ValueError as ex:
            log_box.append(f'⚠ Invalid param: {ex}')

    btn_apply = QPushButton('Apply')
    btn_apply.clicked.connect(apply_params)
    params_layout.addWidget(btn_apply)
    root_layout.addWidget(params_box)

    # ── wiring ───────────────────────────────────────────────────────────────
    ws_thread_ref = [None]

    def on_price(p: float):
        price_label.setText(f'Price: {p:.4f}')
        if price_history:
            price_curve.setData(list(time_history), list(price_history))
        if strategy.in_pos:
            status_label.setText(f'IN POSITION ({strategy.pos_side})')
            status_label.setStyleSheet('color: #ffa726;')
        else:
            status_label.setText('Status: watching')
            status_label.setStyleSheet('color: #66bb6a;')

    def on_log(msg: str):
        ts = datetime.now().strftime('%H:%M:%S')
        log_box.append(f'[{ts}] {msg}')

    signals.price_updated.connect(on_price)
    signals.log_message.connect(on_log)

    def start_bot():
        try:
            client.set_leverage(SYMBOL, LEVERAGE)
        except Exception as ex:
            log_box.append(f'⚠ set_leverage failed: {ex}')
        t = threading.Thread(target=_ws_thread, args=(strategy, price_cb), daemon=True)
        t.start()
        ws_thread_ref[0] = t
        btn_start.setEnabled(False)
        btn_stop.setEnabled(True)
        status_label.setText('Status: watching')
        status_label.setStyleSheet('color: #66bb6a;')
        log_box.append('▶ Bot started')

    def stop_bot():
        # No clean WS shutdown in this simple version — just flag it
        strategy.in_pos = False
        btn_start.setEnabled(True)
        btn_stop.setEnabled(False)
        status_label.setText('Status: stopped')
        status_label.setStyleSheet('color: #ef5350;')
        log_box.append('■ Bot stopped (positions NOT auto-closed)')

    btn_start.clicked.connect(start_bot)
    btn_stop.clicked.connect(stop_bot)

    win.show()
    sys.exit(app.exec_())


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Load credentials
    api_key    = os.getenv('MEXC_API_KEY', '')
    api_secret = os.getenv('MEXC_API_SECRET', '')

    if not api_key or not api_secret:
        # Try keys.json in project root
        keys_path = os.path.join(os.path.dirname(__file__), '..', 'keys.json')
        if os.path.exists(keys_path):
            with open(keys_path) as f:
                k = json.load(f)
            api_key    = k.get('api_key', '')
            api_secret = k.get('api_secret', '')

    if not api_key:
        if HEADLESS:
            log.error('No API credentials found.  Set MEXC_API_KEY / MEXC_API_SECRET env vars.')
            sys.exit(1)
        else:
            # GUI: prompt
            from PyQt5.QtWidgets import QApplication, QInputDialog
            _app = QApplication.instance() or QApplication(sys.argv)
            api_key,    ok1 = QInputDialog.getText(None, 'MEXC Key',    'API Key:')
            api_secret, ok2 = QInputDialog.getText(None, 'MEXC Secret', 'API Secret:')
            if not (ok1 and ok2 and api_key and api_secret):
                sys.exit(0)

    client = MexcClient(api_key, api_secret)

    if HEADLESS:
        run_headless(client)
    else:
        run_gui(client)


if __name__ == '__main__':
    main()
