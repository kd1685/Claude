"""Named event windows (KvK, Ark, …). Listing is public so the DKP page can
populate its selector; creating/deleting is admin-only."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import require_admin
from ..db import get_conn
from ..models import EventIn

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events():
    rows = get_conn().execute(
        "SELECT * FROM events ORDER BY start_date DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("")
def create_event(body: EventIn, admin=Depends(require_admin)):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO events (name, start_date, end_date, created_by) VALUES (?,?,?,?)",
        (body.name, body.start_date, body.end_date, admin["username"]),
    )
    conn.commit()
    return {"id": int(cur.lastrowid)}


@router.delete("/{event_id}")
def delete_event(event_id: int, admin=Depends(require_admin)):
    get_conn().execute("DELETE FROM events WHERE id=?", (event_id,))
    get_conn().commit()
    return {"ok": True}
