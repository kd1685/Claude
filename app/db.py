"""SQLite access layer and schema."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from .config import config

_LOCAL = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    governor_id  TEXT UNIQUE,
    name         TEXT NOT NULL,
    alliance     TEXT,
    rank         INTEGER DEFAULT 1,            -- R1..R5
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,                -- power | killpoints | dead | rss
    captured_at  TEXT NOT NULL,                -- YYYY-MM-DD
    source       TEXT NOT NULL,                -- mock | adb | manual
    device       TEXT,
    rows         INTEGER DEFAULT 0,
    meta         TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

-- One coalesced row per player per day; each scan kind fills its columns.
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id    INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    captured_at  TEXT NOT NULL,                -- YYYY-MM-DD
    power        INTEGER,
    kill_points  INTEGER,
    t1_kills     INTEGER,
    t2_kills     INTEGER,
    t3_kills     INTEGER,
    t4_kills     INTEGER,
    t5_kills     INTEGER,
    deads        INTEGER,
    rss_gathered INTEGER,
    rss_assist   INTEGER,
    helps        INTEGER,
    UNIQUE(player_id, captured_at)
);

CREATE TABLE IF NOT EXISTS rallies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at   TEXT NOT NULL,
    leader_id     INTEGER REFERENCES players(id) ON DELETE SET NULL,
    leader_name   TEXT,
    target_type   TEXT,                        -- barbarian | fortress | flag | player | building
    target_label  TEXT,
    x             INTEGER,
    y             INTEGER,
    troops        INTEGER,
    status        TEXT,                         -- win | loss | pending
    source        TEXT
);

CREATE TABLE IF NOT EXISTS map_positions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id    INTEGER REFERENCES players(id) ON DELETE CASCADE,
    name         TEXT,
    kingdom      INTEGER,
    x            INTEGER,
    y            INTEGER,
    captured_at  TEXT NOT NULL,
    source       TEXT
);

-- Officer accounts that can reach the Control page.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'officer',  -- admin | officer
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now')),
    last_login    TEXT
);

-- Account-control command queue. The worker drains pending rows.
CREATE TABLE IF NOT EXISTS commands (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,                -- give_title | change_rank | locate | scan
    player_id      INTEGER REFERENCES players(id) ON DELETE SET NULL,
    params         TEXT,                          -- json
    status         TEXT DEFAULT 'pending',        -- pending | running | done | failed
    result         TEXT,
    error          TEXT,
    issued_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    issued_by_name TEXT,                          -- denormalised for the audit log
    created_at     TEXT DEFAULT (datetime('now')),
    started_at     TEXT,
    finished_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_player ON snapshots(player_id);
CREATE INDEX IF NOT EXISTS idx_rallies_date ON rallies(captured_at);
CREATE INDEX IF NOT EXISTS idx_map_date ON map_positions(captured_at);
CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_conn() -> sqlite3.Connection:
    """One connection per thread (FastAPI worker threads + the control worker)."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        conn = _connect()
        _LOCAL.conn = conn
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release to pre-existing DBs."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(commands)")}
    if "issued_by" not in cols:
        conn.execute("ALTER TABLE commands ADD COLUMN issued_by INTEGER")
    if "issued_by_name" not in cols:
        conn.execute("ALTER TABLE commands ADD COLUMN issued_by_name TEXT")


def upsert_player(name: str, governor_id: str | None = None,
                  alliance: str | None = None, rank: int | None = None) -> int:
    """Find or create a player by governor_id (preferred) or name; return id."""
    conn = get_conn()
    row = None
    if governor_id:
        row = conn.execute("SELECT id FROM players WHERE governor_id = ?",
                           (governor_id,)).fetchone()
    if row is None:
        row = conn.execute("SELECT id FROM players WHERE name = ?", (name,)).fetchone()
    if row:
        pid = row["id"]
        conn.execute(
            """UPDATE players SET
                 name = COALESCE(?, name),
                 governor_id = COALESCE(?, governor_id),
                 alliance = COALESCE(?, alliance),
                 rank = COALESCE(?, rank)
               WHERE id = ?""",
            (name, governor_id, alliance, rank, pid),
        )
        return pid
    cur = conn.execute(
        "INSERT INTO players (name, governor_id, alliance, rank) VALUES (?,?,?,?)",
        (name, governor_id, alliance, rank or 1),
    )
    return int(cur.lastrowid)


# Numeric snapshot columns that a scan may contribute.
SNAPSHOT_FIELDS = (
    "power", "kill_points", "t1_kills", "t2_kills", "t3_kills", "t4_kills",
    "t5_kills", "deads", "rss_gathered", "rss_assist", "helps",
)


def upsert_snapshot(player_id: int, captured_at: str, values: dict) -> None:
    """Merge `values` into the player's snapshot for that day (non-null wins)."""
    conn = get_conn()
    cols = [c for c in SNAPSHOT_FIELDS if values.get(c) is not None]
    if not cols:
        return
    conn.execute(
        "INSERT OR IGNORE INTO snapshots (player_id, captured_at) VALUES (?,?)",
        (player_id, captured_at),
    )
    assignments = ", ".join(f"{c} = COALESCE(?, {c})" for c in cols)
    args = [values[c] for c in cols] + [player_id, captured_at]
    conn.execute(
        f"UPDATE snapshots SET {assignments} WHERE player_id = ? AND captured_at = ?",
        args,
    )
