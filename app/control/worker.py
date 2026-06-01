"""Background worker that drains the account-control command queue.

Commands are enqueued by the API (so the HTTP request returns instantly) and
executed here one at a time — important because a single game client can only
do one thing at once.
"""
from __future__ import annotations

import datetime as dt
import json
import threading

from ..config import config
from ..db import get_conn
from . import actions, rotation

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


def _check_schedules() -> None:
    """Enqueue automatic scans for any schedule that is due today."""
    now = dt.datetime.now()
    today = now.date().isoformat()
    conn = get_conn()
    for s in conn.execute("SELECT * FROM scan_schedules WHERE active=1").fetchall():
        if s["last_run_date"] == today:
            continue
        due = (now.hour, now.minute) >= (s["at_hour"], s["at_minute"])
        if due:
            enqueue("scan", params={"kind": s["kind"], "pages": s["pages"]},
                    issued_by_name=f"schedule #{s['id']}")
            conn.execute("UPDATE scan_schedules SET last_run_date=? WHERE id=?",
                         (today, s["id"]))
            conn.commit()


def _tick() -> bool:
    # Rotations are exclusive and take priority over everything else.
    if rotation.step():
        return False  # a rotation is running (possibly holding) — wait the interval
    _check_schedules()
    return _process_one()


def _loop() -> None:
    while not _stop.is_set():
        try:
            worked = _tick()
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
