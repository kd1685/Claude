"""
store_db.py — tiny SQLite persistence layer for Ascent Terminal.

Backs the in-memory stores (webhook_store alerts, execution log) so they
survive server restarts. Write-through design: the deques stay the source
of truth for reads (fast), every write is mirrored to disk, and on startup
the deques are rebuilt from the last rows on disk.

Graceful by design: if the DB can't be opened (read-only disk, locked file),
everything silently degrades to memory-only — persistence must never be the
reason the terminal won't start.

DB file: platform/data/ascent.db (override with ASCENT_DB env var).
Growth is capped: old rows are pruned periodically (ALERTS_KEEP / EXEC_KEEP).
"""

import os
import sqlite3
import threading

DB_PATH = os.environ.get(
    "ASCENT_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ascent.db"),
)

ALERTS_KEEP = 5000
EXEC_KEEP = 2000
_PRUNE_EVERY = 100            # prune after this many inserts per table

_lock = threading.Lock()
_conn = None
_disabled = False
_insert_counts = {"alerts": 0, "exec_log": 0}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
  rowid_pk INTEGER PRIMARY KEY AUTOINCREMENT,
  id INTEGER, ts REAL, symbol TEXT, action TEXT,
  price REAL, tp REAL, sl REAL, message TEXT, timeframe TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
CREATE TABLE IF NOT EXISTS exec_log (
  rowid_pk INTEGER PRIMARY KEY AUTOINCREMENT,
  id INTEGER, ts REAL, source TEXT, symbol TEXT, side TEXT,
  exchange TEXT, order_type TEXT, mode TEXT, status TEXT, detail TEXT,
  price REAL, amount REAL, notional REAL, tp REAL, sl REAL
);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def _get():
    """Lazy thread-safe connection. Returns None when persistence is disabled."""
    global _conn, _disabled
    if _disabled:
        return None
    if _conn is not None:
        return _conn
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        _conn = conn
        return _conn
    except Exception:
        _disabled = True          # memory-only from here on — never crash the app
        return None


def available() -> bool:
    with _lock:
        return _get() is not None


def save_alert(a: dict):
    with _lock:
        conn = _get()
        if not conn:
            return
        try:
            conn.execute(
                "INSERT INTO alerts (id,ts,symbol,action,price,tp,sl,message,timeframe) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (a.get("id"), a.get("ts"), a.get("symbol"), a.get("action"),
                 a.get("price"), a.get("tp"), a.get("sl"),
                 a.get("message"), a.get("timeframe")))
            conn.commit()
            _maybe_prune(conn, "alerts", ALERTS_KEEP)
        except Exception:
            pass


def load_alerts(limit: int = 500) -> list:
    with _lock:
        conn = _get()
        if not conn:
            return []
        try:
            rows = conn.execute(
                "SELECT id,ts,symbol,action,price,tp,sl,message,timeframe "
                "FROM alerts ORDER BY rowid_pk DESC LIMIT ?", (limit,)).fetchall()
        except Exception:
            return []
    keys = ("id", "ts", "symbol", "action", "price", "tp", "sl", "message", "timeframe")
    return [dict(zip(keys, r)) for r in rows]


def delete_alerts(symbol: str):
    with _lock:
        conn = _get()
        if not conn:
            return
        try:
            conn.execute("DELETE FROM alerts WHERE symbol = ?", (symbol,))
            conn.commit()
        except Exception:
            pass


_EXEC_KEYS = ("id", "ts", "source", "symbol", "side", "exchange", "order_type",
              "mode", "status", "detail", "price", "amount", "notional", "tp", "sl")


def save_exec(e: dict):
    with _lock:
        conn = _get()
        if not conn:
            return
        try:
            conn.execute(
                f"INSERT INTO exec_log ({','.join(_EXEC_KEYS)}) "
                f"VALUES ({','.join('?' * len(_EXEC_KEYS))})",
                tuple(e.get(k) for k in _EXEC_KEYS))
            conn.commit()
            _maybe_prune(conn, "exec_log", EXEC_KEEP)
        except Exception:
            pass


def load_exec(limit: int = 200) -> list:
    with _lock:
        conn = _get()
        if not conn:
            return []
        try:
            rows = conn.execute(
                f"SELECT {','.join(_EXEC_KEYS)} FROM exec_log "
                "ORDER BY rowid_pk DESC LIMIT ?", (limit,)).fetchall()
        except Exception:
            return []
    return [dict(zip(_EXEC_KEYS, r)) for r in rows]


def save_kv(key: str, value: str):
    with _lock:
        conn = _get()
        if not conn:
            return
        try:
            conn.execute("INSERT INTO kv (key,value) VALUES (?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, value))
            conn.commit()
        except Exception:
            pass


def load_kv(key: str):
    with _lock:
        conn = _get()
        if not conn:
            return None
        try:
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return row[0] if row else None
        except Exception:
            return None


def delete_kv(key: str):
    with _lock:
        conn = _get()
        if not conn:
            return
        try:
            conn.execute("DELETE FROM kv WHERE key=?", (key,))
            conn.commit()
        except Exception:
            pass


def kv_keys(prefix: str):
    with _lock:
        conn = _get()
        if not conn:
            return []
        try:
            rows = conn.execute("SELECT key FROM kv WHERE key LIKE ?",
                                (prefix + "%",)).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []


def _maybe_prune(conn, table: str, keep: int):
    _insert_counts[table] += 1
    if _insert_counts[table] % _PRUNE_EVERY:
        return
    try:
        conn.execute(
            f"DELETE FROM {table} WHERE rowid_pk <= "
            f"(SELECT COALESCE(MAX(rowid_pk),0) - ? FROM {table})", (keep,))
        conn.commit()
    except Exception:
        pass
