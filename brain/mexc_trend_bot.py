#!/usr/bin/env python3
"""
MEXC Futures Daily Trend Bot
Strategy: EMA30 on Day1 candles — long above EMA, short below EMA.
Designed to run on the owner's Windows machine (PyQt5 GUI).
NOT deployed to the VPS.

Requires: pip install PyQt5 pyqtgraph pandas numpy requests
"""

import sys, os, json, time, hmac, hashlib, threading, logging
from datetime import datetime, timezone, timedelta
from collections import deque

import requests
import pandas as pd
import numpy as np

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('trend_bot')

# ── MEXC REST ────────────────────────────────────────────────────────────────
BASE = 'https://contract.mexc.com'

class MexcClient:
    def __init__(self, key: str, secret: str):
        self.key    = key
        self.secret = secret
        self.s      = requests.Session()
        self.s.headers.update({'Content-Type': 'application/json'})

    # ── auth ────────────────────────────────────────────────────────────────
    def _sign(self, params: dict) -> dict:
        params = dict(params)
        params['timestamp'] = str(int(time.time() * 1000))
        params['api_key']   = self.key
        q = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
        params['sign'] = hmac.new(self.secret.encode(), q.encode(),
                                   hashlib.sha256).hexdigest()
        return params

    # ── market data ─────────────────────────────────────────────────────────
    def klines(self, symbol: str, interval: str = 'Day1',
               limit: int = 100) -> pd.DataFrame:
        end   = int(time.time())
        start = end - limit * 86400
        r = self.s.get(
            f'{BASE}/api/v1/contract/kline',
            params={'symbol': symbol, 'interval': interval,
                    'start': start, 'end': end},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json().get('data', {})
        df = pd.DataFrame({
            'ts':    raw['time'],
            'open':  raw['realOpen'],
            'high':  raw['high'],
            'low':   raw['low'],
            'close': raw['realClose'],
            'vol':   raw['vol'],
        }).astype({'ts': int, 'open': float, 'high': float,
                   'low': float, 'close': float, 'vol': float})
        df['dt'] = pd.to_datetime(df['ts'], unit='s', utc=True)
        return df.sort_values('ts').reset_index(drop=True)

    def ticker(self, symbol: str) -> float:
        r = self.s.get(f'{BASE}/api/v1/contract/ticker',
                       params={'symbol': symbol}, timeout=10)
        r.raise_for_status()
        return float(r.json()['data']['lastPrice'])

    # ── account ──────────────────────────────────────────────────────────────
    def account(self) -> dict:
        r = self.s.get(f'{BASE}/api/v1/private/account/assets',
                       params=self._sign({}), timeout=10)
        r.raise_for_status()
        return r.json().get('data', {})

    def open_positions(self, symbol: str) -> list:
        r = self.s.get(f'{BASE}/api/v1/private/position/open_positions',
                       params=self._sign({'symbol': symbol}), timeout=10)
        r.raise_for_status()
        return r.json().get('data', [])

    # ── trading ──────────────────────────────────────────────────────────────
    def set_leverage(self, symbol: str, lev: int):
        data = self._sign({'symbol': symbol, 'leverage': lev,
                           'openType': 1, 'positionType': 3})
        self.s.post(f'{BASE}/api/v1/private/position/change_leverage',
                    json=data, timeout=10)

    def market_order(self, symbol: str, side: int, vol: float):
        """
        side: 1=open_long 2=close_short 3=open_short 4=close_long
        vol:  number of contracts
        """
        data = self._sign({'symbol': symbol, 'side': side, 'openType': 1,
                           'type': 5, 'vol': vol, 'leverage': 3})
        r = self.s.post(f'{BASE}/api/v1/private/order/submit',
                        json=data, timeout=10)
        r.raise_for_status()
        return r.json()

    def close_all(self, symbol: str):
        for pos in self.open_positions(symbol):
            side = 4 if pos['positionType'] == 1 else 2
            self.market_order(symbol, side, pos['holdVol'])


# ── Strategy ─────────────────────────────────────────────────────────────────

class TrendStrategy:
    EMA_PERIOD  = 30
    LEVERAGE    = 3
    MAX_USDT    = float(os.getenv('MAX_POSITION_USDT', 200))

    def __init__(self, client: MexcClient, symbol: str):
        self.client = client
        self.symbol = symbol
        self.last_signal: str | None = None  # 'long' | 'short' | None

    def ema(self, series: pd.Series) -> pd.Series:
        return series.ewm(span=self.EMA_PERIOD, adjust=False).mean()

    def evaluate(self) -> str | None:
        """Returns 'long', 'short', or None (no change)."""
        df  = self.client.klines(self.symbol, 'Day1', self.EMA_PERIOD + 10)
        e   = self.ema(df['close'])
        last_close = df['close'].iloc[-2]   # confirmed closed candle
        last_ema   = e.iloc[-2]

        new_signal = 'long' if last_close > last_ema else 'short'
        if new_signal != self.last_signal:
            return new_signal
        return None

    def execute(self, signal: str):
        price = self.client.ticker(self.symbol)
        vol   = max(1, int(self.MAX_USDT / price))
        self.client.set_leverage(self.symbol, self.LEVERAGE)
        self.client.close_all(self.symbol)
        if signal == 'long':
            self.client.market_order(self.symbol, 1, vol)   # open long
        else:
            self.client.market_order(self.symbol, 3, vol)   # open short
        self.last_signal = signal
        log.info('Signal → %s | price=%.4f | vol=%d', signal.upper(), price, vol)

    # ── CSV export ───────────────────────────────────────────────────────────
    def export_signals_csv(self, path: str = 'brain/daily_signals.csv'):
        df   = self.client.klines(self.symbol, 'Day1', 100)
        df['ema'] = self.ema(df['close'])
        df['signal'] = np.where(df['close'] > df['ema'], 'long', 'short')
        df[['dt', 'close', 'ema', 'signal']].to_csv(path, index=False)
        log.info('Signals exported → %s', path)
        return path


# ── Scheduler ────────────────────────────────────────────────────────────────

def _scheduler_thread(strategy: TrendStrategy,
                      log_cb, status_cb,
                      interval_hours: float = 24.0):
    """Runs evaluate → execute every interval_hours."""
    log_cb('Scheduler started')
    while True:
        try:
            sig = strategy.evaluate()
            if sig:
                status_cb(f'Signal: {sig.upper()}')
                log_cb(f'New signal: {sig.upper()} — executing')
                strategy.execute(sig)
                log_cb('Order sent')
            else:
                log_cb('No signal change')
                status_cb(f'Holding {strategy.last_signal or "flat"}')
        except Exception as e:
            log_cb(f'ERROR: {e}')
            log.exception('Scheduler error')
        time.sleep(interval_hours * 3600)


# ── GUI ───────────────────────────────────────────────────────────────────────

def run_gui(client: MexcClient):
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox, QComboBox,
        QSplitter, QFileDialog,
    )
    from PyQt5.QtCore import Qt, pyqtSignal, QObject
    from PyQt5.QtGui import QFont, QColor, QPalette
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True)

    class Signals(QObject):
        log_msg    = pyqtSignal(str)
        status_msg = pyqtSignal(str)
        chart_data = pyqtSignal(object, object, object)   # times, closes, emas

    sigs = Signals()

    # ── fetch symbol list ────────────────────────────────────────────────────
    DEFAULT_SYM = 'BTC_USDT'
    try:
        r   = requests.get(f'{BASE}/api/v1/contract/detail', timeout=10)
        all_syms = [d['symbol'] for d in r.json().get('data', [])
                    if d.get('quoteCoin') == 'USDT' and d.get('state') == 0]
    except Exception:
        all_syms = [DEFAULT_SYM]

    strategy_ref: list[TrendStrategy | None] = [None]

    # ── app / palette ────────────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    pal = QPalette()
    pal.setColor(QPalette.Window,        QColor(28, 28, 28))
    pal.setColor(QPalette.WindowText,    QColor(220, 220, 220))
    pal.setColor(QPalette.Base,          QColor(18, 18, 18))
    pal.setColor(QPalette.Text,          QColor(220, 220, 220))
    pal.setColor(QPalette.Button,        QColor(50, 50, 50))
    pal.setColor(QPalette.ButtonText,    QColor(220, 220, 220))
    pal.setColor(QPalette.Highlight,     QColor(0, 120, 215))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(pal)

    win = QMainWindow()
    win.setWindowTitle('Ascent Trend Bot')
    win.resize(1200, 750)
    central = QWidget()
    win.setCentralWidget(central)
    root = QVBoxLayout(central)

    # ── toolbar ──────────────────────────────────────────────────────────────
    tb = QHBoxLayout()
    sym_combo = QComboBox()
    sym_combo.addItems(sorted(all_syms))
    sym_combo.setCurrentText(DEFAULT_SYM)
    sym_combo.setFixedWidth(160)
    sym_combo.setStyleSheet('background:#2a2a2a; color:#eee;')

    status_lbl = QLabel('Idle')
    status_lbl.setFont(QFont('Consolas', 13, QFont.Bold))
    status_lbl.setStyleSheet('color: #aaa;')

    btn_run    = QPushButton('▶  Run')
    btn_stop   = QPushButton('■  Stop')
    btn_export = QPushButton('📥  Export CSV')
    btn_stop.setEnabled(False)
    for btn in (btn_run, btn_stop, btn_export):
        btn.setFixedHeight(32)
        btn.setFont(QFont('Consolas', 10))

    tb.addWidget(QLabel('Symbol:'))
    tb.addWidget(sym_combo)
    tb.addStretch()
    tb.addWidget(status_lbl)
    tb.addSpacing(20)
    tb.addWidget(btn_run)
    tb.addWidget(btn_stop)
    tb.addWidget(btn_export)
    root.addLayout(tb)

    # ── splitter: chart | log ────────────────────────────────────────────────
    splitter = QSplitter(Qt.Horizontal)

    pw = pg.PlotWidget(title='Daily Close + EMA30')
    pw.setBackground('#1a1a1a')
    pw.showGrid(x=True, y=True, alpha=0.2)
    close_curve = pw.plot(pen=pg.mkPen('#00e5ff', width=1.5), name='Close')
    ema_curve   = pw.plot(pen=pg.mkPen('#ff9800', width=1.5), name='EMA30')
    splitter.addWidget(pw)

    log_box = QTextEdit()
    log_box.setReadOnly(True)
    log_box.setFont(QFont('Consolas', 9))
    log_box.setStyleSheet('background:#111; color:#ccc;')
    splitter.addWidget(log_box)
    splitter.setSizes([800, 400])
    root.addWidget(splitter, stretch=1)

    # ── params ───────────────────────────────────────────────────────────────
    p_box    = QGroupBox('Strategy Parameters')
    p_layout = QHBoxLayout(p_box)

    def _p(label, val):
        l = QLabel(label); l.setStyleSheet('color:#aaa;')
        e = QLineEdit(str(val))
        e.setFixedWidth(70)
        e.setStyleSheet('background:#2a2a2a; color:#eee; border:1px solid #444;')
        p_layout.addWidget(l); p_layout.addWidget(e)
        return e

    e_ema     = _p('EMA period', TrendStrategy.EMA_PERIOD)
    e_lev     = _p('Leverage',   TrendStrategy.LEVERAGE)
    e_maxusdt = _p('Max USDT',   int(TrendStrategy.MAX_USDT))
    e_interval= _p('Interval h', 24)
    p_layout.addStretch()

    def apply_params():
        try:
            TrendStrategy.EMA_PERIOD = int(e_ema.text())
            TrendStrategy.LEVERAGE   = int(e_lev.text())
            TrendStrategy.MAX_USDT   = float(e_maxusdt.text())
            log_box.append('↺ Parameters updated')
        except ValueError as ex:
            log_box.append(f'⚠ Bad param: {ex}')

    btn_ap = QPushButton('Apply')
    btn_ap.clicked.connect(apply_params)
    p_layout.addWidget(btn_ap)
    root.addWidget(p_box)

    # ── chart refresh ─────────────────────────────────────────────────────────
    def refresh_chart(sym: str):
        try:
            df = client.klines(sym, 'Day1', 100)
            df['ema'] = df['close'].ewm(span=TrendStrategy.EMA_PERIOD,
                                        adjust=False).mean()
            ts = df['ts'].values.astype(float)
            sigs.chart_data.emit(ts, df['close'].values, df['ema'].values)
        except Exception as e:
            sigs.log_msg.emit(f'Chart error: {e}')

    def on_chart_data(ts, closes, emas):
        close_curve.setData(ts, closes)
        ema_curve.setData(ts, emas)

    sigs.chart_data.connect(on_chart_data)
    sigs.log_msg.connect(lambda m: log_box.append(
        f'[{datetime.now():%H:%M:%S}] {m}'))
    sigs.status_msg.connect(lambda m: (
        status_lbl.setText(m),
        status_lbl.setStyleSheet('color: #ffa726;' if 'long' in m.lower()
                                 else 'color: #ef5350;' if 'short' in m.lower()
                                 else 'color: #aaa;'),
    ))

    # ── button handlers ───────────────────────────────────────────────────────
    _sched_stop = threading.Event()

    def start():
        sym = sym_combo.currentText()
        strat = TrendStrategy(client, sym)
        strategy_ref[0] = strat
        _sched_stop.clear()

        # Load chart immediately
        threading.Thread(target=refresh_chart, args=(sym,), daemon=True).start()

        def log_cb(m):    sigs.log_msg.emit(m)
        def status_cb(m): sigs.status_msg.emit(m)

        def _loop():
            try:
                interval = float(e_interval.text())
            except ValueError:
                interval = 24.0
            _scheduler_thread(strat, log_cb, status_cb, interval)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        btn_run.setEnabled(False)
        btn_stop.setEnabled(True)
        status_lbl.setText('Running')
        status_lbl.setStyleSheet('color: #66bb6a;')

    def stop():
        _sched_stop.set()
        btn_run.setEnabled(True)
        btn_stop.setEnabled(False)
        status_lbl.setText('Stopped')
        status_lbl.setStyleSheet('color: #ef5350;')
        log_box.append('■ Bot stopped (open positions NOT closed)')

    def export_csv():
        strat = strategy_ref[0]
        if strat is None:
            strat = TrendStrategy(client, sym_combo.currentText())
        path, _ = QFileDialog.getSaveFileName(
            win, 'Save CSV', 'daily_signals.csv', 'CSV files (*.csv)')
        if path:
            def _do():
                try:
                    out = strat.export_signals_csv(path)
                    sigs.log_msg.emit(f'Exported → {out}')
                except Exception as e:
                    sigs.log_msg.emit(f'Export error: {e}')
            threading.Thread(target=_do, daemon=True).start()

    btn_run.clicked.connect(start)
    btn_stop.clicked.connect(stop)
    btn_export.clicked.connect(export_csv)
    sym_combo.currentTextChanged.connect(
        lambda sym: threading.Thread(target=refresh_chart,
                                     args=(sym,), daemon=True).start())

    win.show()
    sys.exit(app.exec_())


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    api_key    = os.getenv('MEXC_API_KEY', '')
    api_secret = os.getenv('MEXC_API_SECRET', '')

    if not api_key:
        keys_path = os.path.join(os.path.dirname(__file__), '..', 'keys.json')
        if os.path.exists(keys_path):
            with open(keys_path) as f:
                k = json.load(f)
            api_key    = k.get('api_key', '')
            api_secret = k.get('api_secret', '')

    if not api_key:
        from PyQt5.QtWidgets import QApplication, QInputDialog
        _app = QApplication.instance() or QApplication(sys.argv)
        api_key,    ok1 = QInputDialog.getText(None, 'MEXC Key',    'API Key:')
        api_secret, ok2 = QInputDialog.getText(None, 'MEXC Secret', 'API Secret:')
        if not (ok1 and ok2):
            sys.exit(0)

    client = MexcClient(api_key, api_secret)
    run_gui(client)


if __name__ == '__main__':
    main()
