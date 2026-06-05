"""Recurring automatic scan schedules (admin-managed)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin, require_ready
from ..db import get_conn
from ..models import ScheduleIn
from ..utils import rows_to_dicts

# Schedulable jobs: list scans (power/killpoints), the deep deads scan, rallies.
SCHEDULE_KINDS = {"power", "killpoints", "dead", "profiles", "rallies"}

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("")
def list_schedules(user=Depends(require_ready)):
    rows = get_conn().execute(
        "SELECT * FROM scan_schedules ORDER BY at_hour, at_minute").fetchall()
    return rows_to_dicts(rows)


@router.post("")
def create_schedule(body: ScheduleIn, admin=Depends(require_admin)):
    if body.kind not in SCHEDULE_KINDS:
        raise HTTPException(400, f"kind must be one of {sorted(SCHEDULE_KINDS)}")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO scan_schedules (kind, at_hour, at_minute, pages, created_by) "
        "VALUES (?,?,?,?,?)",
        (body.kind, body.at_hour, body.at_minute, body.pages, admin["username"]),
    )
    conn.commit()
    return {"id": int(cur.lastrowid)}


@router.post("/{schedule_id}/active")
def toggle(schedule_id: int, active: bool, admin=Depends(require_admin)):
    conn = get_conn()
    conn.execute("UPDATE scan_schedules SET active=? WHERE id=?",
                 (1 if active else 0, schedule_id))
    conn.commit()
    return {"ok": True}


@router.delete("/{schedule_id}")
def delete(schedule_id: int, admin=Depends(require_admin)):
    conn = get_conn()
    conn.execute("DELETE FROM scan_schedules WHERE id=?", (schedule_id,))
    conn.commit()
    return {"ok": True}
