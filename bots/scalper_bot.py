#!/usr/bin/env python3
"""
MEXC Futures Scalping Bot
Requires: pip install PyQt5 pyqtgraph websocket-client anthropic requests
"""

# ─── STDLIB ─────────────────────────────────────────────────────────────────────────────
import sys, os, json, time, hmac, hashlib, threading, queue, logging
import asyncio, ssl, math, copy, traceback
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import deque
