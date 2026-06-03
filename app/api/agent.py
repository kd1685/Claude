"""Endpoints for the PC agent (CONTROL_BACKEND=remote).

The agent authenticates with the shared AGENT_TOKEN, polls for the next device
task, runs it in LDPlayer, and posts the result back. It also heartbeats so the
Control page can show whether the agent is online.
"""
from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ..config import config
from ..db import get_conn

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _auth(token: str | None) -> None:
    if not config.AGENT_TOKEN:
        raise HTTPException(503, "remote agent not enabled (set AGENT_TOKEN)")
    if not token or not hmac.compare_digest(token, config.AGENT_TOKEN):
        raise HTTPException(401, "invalid agent token")


def _beat(info: str | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO agent_heartbeat (id, last_seen, info) VALUES (1, datetime('now'), ?) "
        "ON CONFLICT(id) DO UPDATE SET last_seen=datetime('now'), info=COALESCE(?, info)",
        (info, info),
    )
    conn.commit()


class CompleteIn(BaseModel):
    task_id: int
    ok: bool
    detail: str = ""
    data: dict = {}
    error: str | None = None


@router.post("/poll")
def poll(x_agent_token: str | None = Header(default=None), info: str | None = None):
    """Heartbeat + claim the oldest pending device task (or return none)."""
    _auth(x_agent_token)
    _beat(info)
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM device_tasks WHERE status='pending' ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        return {"task": None}
    conn.execute(
        "UPDATE device_tasks SET status='running', claimed_at=datetime('now') WHERE id=?",
        (row["id"],),
    )
    conn.commit()
    return {"task": {"id": row["id"], "kind": row["kind"],
                     "params": json.loads(row["params"] or "{}")}}


@router.post("/complete")
def complete(body: CompleteIn, x_agent_token: str | None = Header(default=None)):
    _auth(x_agent_token)
    _beat()
    conn = get_conn()
    conn.execute(
        "UPDATE device_tasks SET status=?, ok=?, result=?, error=?, "
        "finished_at=datetime('now') WHERE id=?",
        ("done" if body.ok else "failed", 1 if body.ok else 0,
         json.dumps({"detail": body.detail, "data": body.data}),
         body.error, body.task_id),
    )
    conn.commit()
    return {"ok": True}


@router.get("/health")
def health(x_agent_token: str | None = Header(default=None)):
    _auth(x_agent_token)
    _beat()
    return {"ok": True}
