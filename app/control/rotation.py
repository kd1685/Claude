"""Title-rotation engine ("title duty").

An officer queues a list of governors for a title. The worker hands the title to
each member in turn and holds it for `hold_seconds` (default 180 = 3 minutes)
before advancing to the next. Rotations are exclusive: while one runs, one-off
commands wait. Each grant is also written to the command/audit log.
"""
from __future__ import annotations

import json

from ..db import get_conn
from ..models import TITLES
from ..utils import rows_to_dicts
from . import actions
from .adapter import ActionResult

DEFAULT_HOLD = 180
MIN_HOLD = 0
MAX_HOLD = 3600


def get_running():
    return get_conn().execute(
        "SELECT * FROM rotations WHERE status='running' ORDER BY id LIMIT 1").fetchone()


def create_rotation(title: str, player_ids: list[int], hold_seconds: int,
                    user) -> int:
    if title not in TITLES:
        raise ValueError(f"title must be one of {TITLES}")
    if not player_ids:
        raise ValueError("at least one governor is required")
    if get_running():
        raise ValueError("a rotation is already running — cancel it first")
    hold_seconds = max(MIN_HOLD, min(MAX_HOLD, int(hold_seconds)))

    conn = get_conn()
    # Resolve names and validate the governors exist.
    members = []
    for pid in player_ids:
        row = conn.execute("SELECT id, name FROM players WHERE id=?", (pid,)).fetchone()
        if not row:
            raise ValueError(f"player {pid} not found")
        members.append((row["id"], row["name"]))

    cur = conn.execute(
        "INSERT INTO rotations (title, hold_seconds, issued_by, issued_by_name) "
        "VALUES (?,?,?,?)",
        (title, hold_seconds, user["id"], user["username"]),
    )
    rid = int(cur.lastrowid)
    for pos, (pid, name) in enumerate(members):
        conn.execute(
            "INSERT INTO rotation_members (rotation_id, player_id, player_name, position)"
            " VALUES (?,?,?,?)",
            (rid, pid, name, pos),
        )
    conn.commit()
    return rid


def cancel(rotation_id: int) -> bool:
    conn = get_conn()
    rot = conn.execute("SELECT * FROM rotations WHERE id=?", (rotation_id,)).fetchone()
    if not rot or rot["status"] != "running":
        return False
    conn.execute(
        "UPDATE rotation_members SET status='skipped', finished_at=datetime('now') "
        "WHERE rotation_id=? AND status IN ('waiting','active')",
        (rotation_id,),
    )
    conn.execute(
        "UPDATE rotations SET status='cancelled', finished_at=datetime('now') WHERE id=?",
        (rotation_id,),
    )
    conn.commit()
    return True


def skip_current(rotation_id: int) -> bool:
    """Advance past the active member immediately (ends their hold early)."""
    conn = get_conn()
    active = conn.execute(
        "SELECT id FROM rotation_members WHERE rotation_id=? AND status='active'",
        (rotation_id,),
    ).fetchone()
    if not active:
        return False
    conn.execute(
        "UPDATE rotation_members SET status='done', finished_at=datetime('now') WHERE id=?",
        (active["id"],),
    )
    conn.commit()
    return True


def _elapsed(member_id: int) -> float:
    row = get_conn().execute(
        "SELECT (julianday('now')-julianday(started_at))*86400 AS e "
        "FROM rotation_members WHERE id=?",
        (member_id,),
    ).fetchone()
    return row["e"] or 0.0


def active_rotation() -> dict | None:
    rot = get_running()
    if not rot:
        return None
    conn = get_conn()
    members = conn.execute(
        "SELECT * FROM rotation_members WHERE rotation_id=? ORDER BY position",
        (rot["id"],),
    ).fetchall()
    active = next((m for m in members if m["status"] == "active"), None)
    remaining = None
    if active:
        remaining = max(0, int(rot["hold_seconds"] - _elapsed(active["id"])))
    return {
        "rotation": dict(rot),
        "members": rows_to_dicts(members),
        "active_member_id": active["id"] if active else None,
        "remaining_seconds": remaining,
        "done": sum(1 for m in members if m["status"] in ("done", "skipped", "failed")),
        "total": len(members),
    }


def _log(rot, member, res: ActionResult) -> None:
    """Mirror each grant into the command/audit log."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO commands (kind, player_id, params, status, result, error, "
        "issued_by, issued_by_name, started_at, finished_at) "
        "VALUES ('give_title',?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        (member["player_id"],
         json.dumps({"title": rot["title"], "rotation_id": rot["id"]}),
         "done" if res.ok else "failed",
         json.dumps({"detail": res.detail}) if res.ok else None,
         None if res.ok else res.detail,
         rot["issued_by"], rot["issued_by_name"]),
    )
    conn.commit()


def step() -> bool:
    """Advance the running rotation by at most one transition.

    Returns True while a rotation is running (so the worker keeps the client
    reserved for it), False when none is running.
    """
    conn = get_conn()
    rot = get_running()
    if not rot:
        return False

    active = conn.execute(
        "SELECT * FROM rotation_members WHERE rotation_id=? AND status='active' LIMIT 1",
        (rot["id"],),
    ).fetchone()
    if active:
        if _elapsed(active["id"]) < rot["hold_seconds"]:
            return True  # still holding this member's title
        conn.execute(
            "UPDATE rotation_members SET status='done', finished_at=datetime('now') WHERE id=?",
            (active["id"],),
        )
        conn.commit()

    nxt = conn.execute(
        "SELECT * FROM rotation_members WHERE rotation_id=? AND status='waiting' "
        "ORDER BY position LIMIT 1",
        (rot["id"],),
    ).fetchone()
    if not nxt:
        conn.execute(
            "UPDATE rotations SET status='done', finished_at=datetime('now') WHERE id=?",
            (rot["id"],),
        )
        conn.commit()
        return False

    if nxt["player_id"]:
        res = actions.give_title(nxt["player_id"], rot["title"])
    else:
        res = ActionResult(False, "player no longer exists")

    if res.ok:
        conn.execute(
            "UPDATE rotation_members SET status='active', started_at=datetime('now'), "
            "error=NULL WHERE id=?",
            (nxt["id"],),
        )
    else:
        conn.execute(
            "UPDATE rotation_members SET status='failed', error=?, "
            "finished_at=datetime('now') WHERE id=?",
            (res.detail, nxt["id"]),
        )
    conn.commit()
    _log(rot, nxt, res)
    return True


def list_rotations(limit: int = 20) -> list[dict]:
    rows = get_conn().execute(
        "SELECT r.*, "
        "(SELECT COUNT(*) FROM rotation_members m WHERE m.rotation_id=r.id) AS total "
        "FROM rotations r ORDER BY r.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
