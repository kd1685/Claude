"""Background worker that drains the account-control command queue.

Commands are enqueued by the API (so the HTTP request returns instantly) and
executed here one at a time — important because a single game client can only
do one thing at once.
"""
from __future__ import annotations

import json
import threading
import time

from ..config import config
from ..db import get_conn
from . import actions

_thread: threading.Thread | None = None
_stop = threading.Event()


def enqueue(kind: str, *, player_id: int | None = None, params: dict | None = None,
            issued_by: int | None = None, issued_by_name: str | None = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO commands (kind, player_id, params, issued_by, issued_by_name) "
        "VALUES (?,?,?,?,?)",
        (kind, player_id, json.dumps(params or {}), issued_by, issued_by_name),
    )
    conn.commit()
    return int(cur.lastrowid)


def _dispatch(cmd) -> "actions.ActionResult":
    params = json.loads(cmd["params"] or "{}")
    kind = cmd["kind"]
    if kind == "give_title":
        return actions.give_title(cmd["player_id"], params["title"])
    if kind == "change_rank":
        return actions.change_rank(cmd["player_id"], int(params["new_rank"]))
    if kind == "locate":
        return actions.locate(cmd["player_id"])
    if kind == "scan":
        return actions.scan(params.get("kind", "power"), int(params.get("pages", 4)))
    raise ValueError(f"unknown command kind '{kind}'")


def _process_one() -> bool:
    conn = get_conn()
    cmd = conn.execute(
        "SELECT * FROM commands WHERE status = 'pending' ORDER BY id LIMIT 1"
    ).fetchone()
    if cmd is None:
        return False
    conn.execute(
        "UPDATE commands SET status='running', started_at=datetime('now') WHERE id=?",
        (cmd["id"],),
    )
    conn.commit()
    try:
        res = _dispatch(cmd)
        conn.execute(
            "UPDATE commands SET status=?, result=?, error=?, finished_at=datetime('now')"
            " WHERE id=?",
            ("done" if res.ok else "failed", json.dumps({"detail": res.detail, **res.data}),
             None if res.ok else res.detail, cmd["id"]),
        )
    except Exception as exc:  # noqa: BLE001
        conn.execute(
            "UPDATE commands SET status='failed', error=?, finished_at=datetime('now')"
            " WHERE id=?",
            (str(exc), cmd["id"]),
        )
    conn.commit()
    return True


def _loop() -> None:
    while not _stop.is_set():
        try:
            worked = _process_one()
        except Exception:
            worked = False
        if not worked:
            _stop.wait(config.WORKER_INTERVAL)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="control-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
