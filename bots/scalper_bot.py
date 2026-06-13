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