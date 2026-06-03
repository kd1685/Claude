"""Remote backend: hand each device action to a PC agent and wait for the result.

Used when CONTROL_BACKEND=remote. The server keeps all its logic (command
queue, rotations, scans); whenever it needs to actually touch the game it calls
one of these methods, which creates a row in `device_tasks` and blocks until the
PC agent (running against LDPlayer) claims it, executes it, and posts the result
back via /api/agent/*. The rest of the app is unchanged — RemoteAdapter just
implements the same AccountAdapter interface as the mock/adb backends.
"""
from __future__ import annotations

import json
import time

from ..config import config
from ..db import get_conn
from .adapter import AccountAdapter, ActionResult


def _agent_online() -> bool:
    row = get_conn().execute(
        "SELECT (julianday('now')-julianday(last_seen))*86400 AS age "
        "FROM agent_heartbeat WHERE id=1"
    ).fetchone()
    return bool(row and row["age"] is not None and row["age"] < 30)


class RemoteAdapter(AccountAdapter):
    name = "remote"

    def _run(self, kind: str, params: dict, timeout: float) -> ActionResult:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO device_tasks (kind, params) VALUES (?,?)",
            (kind, json.dumps(params)),
        )
        task_id = int(cur.lastrowid)
        conn.commit()

        deadline = time.time() + timeout
        while time.time() < deadline:
            conn.rollback()  # ensure a fresh read of the agent's commit
            row = conn.execute(
                "SELECT status, ok, result, error FROM device_tasks WHERE id=?",
                (task_id,),
            ).fetchone()
            if row and row["status"] in ("done", "failed"):
                data = {}
                detail = ""
                if row["result"]:
                    try:
                        payload = json.loads(row["result"])
                        detail = payload.get("detail", "")
                        data = payload.get("data", {}) or {}
                    except Exception:
                        detail = row["result"]
                return ActionResult(bool(row["ok"]), detail or (row["error"] or ""), data)
            time.sleep(0.5)

        conn.execute(
            "UPDATE device_tasks SET status='failed', error='agent timeout' WHERE id=?",
            (task_id,),
        )
        conn.commit()
        return ActionResult(False, "PC agent did not respond in time (is it running?)")

    # ---- AccountAdapter interface ----
    def connect(self) -> ActionResult:
        return (ActionResult(True, "PC agent online") if _agent_online()
                else ActionResult(False, "PC agent offline — start the agent on your computer"))

    def status(self) -> dict:
        row = get_conn().execute(
            "SELECT last_seen, info FROM agent_heartbeat WHERE id=1").fetchone()
        return {
            "backend": "remote",
            "connected": _agent_online(),
            "device": "PC agent (LDPlayer)",
            "agent_last_seen": row["last_seen"] if row else None,
            "agent_info": row["info"] if row else None,
        }

    def give_title(self, *, name, governor_id, x, y, title) -> ActionResult:
        return self._run("give_title", {
            "name": name, "governor_id": governor_id, "x": x, "y": y, "title": title,
        }, config.AGENT_TASK_TIMEOUT)

    def change_rank(self, *, name, governor_id, new_rank) -> ActionResult:
        return self._run("change_rank", {
            "name": name, "governor_id": governor_id, "new_rank": new_rank,
        }, config.AGENT_TASK_TIMEOUT)

    def locate(self, *, name, governor_id) -> ActionResult:
        return self._run("locate", {"name": name, "governor_id": governor_id},
                         config.AGENT_TASK_TIMEOUT)

    def scan_rankings(self, *, kind, pages) -> ActionResult:
        return self._run("scan_rankings", {"kind": kind, "pages": pages},
                         config.AGENT_SCAN_TIMEOUT)
