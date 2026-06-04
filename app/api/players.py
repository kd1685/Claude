"""Player directory + per-player history."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin
from ..db import get_conn, upsert_player
from ..models import PlayerIn

router = APIRouter(prefix="/api/players", tags=["players"])


def _prune_query(cutoff: str) -> str:
    # Players with no snapshot on/after the cutoff date (i.e. not seen lately).
    return ("SELECT p.id, p.name FROM players p WHERE NOT EXISTS ("
            "SELECT 1 FROM snapshots s WHERE s.player_id=p.id AND s.captured_at>=?)")


@router.get("")
def list_players(search: str | None = None, limit: int = 200):
    conn = get_conn()
    where, args = "", []
    if search:
        where = "WHERE p.name LIKE ? OR p.alliance LIKE ?"
        args = [f"%{search}%", f"%{search}%"]
    rows = conn.execute(
        f"""
        SELECT p.id, p.name, p.alliance, p.rank, p.governor_id,
               s.power, s.kill_points, s.deads, s.captured_at AS last_seen
        FROM players p
        LEFT JOIN snapshots s ON s.id = (
            SELECT id FROM snapshots WHERE player_id = p.id
            ORDER BY captured_at DESC LIMIT 1)
        {where}
        ORDER BY s.power DESC NULLS LAST, p.name
        LIMIT ?
        """,
        (*args, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{player_id:int}")
def get_player(player_id: int):
    conn = get_conn()
    p = conn.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    if not p:
        raise HTTPException(404, "player not found")
    history = conn.execute(
        "SELECT * FROM snapshots WHERE player_id=? ORDER BY captured_at",
        (player_id,),
    ).fetchall()
    positions = conn.execute(
        "SELECT kingdom, x, y, captured_at, source FROM map_positions "
        "WHERE player_id=? ORDER BY id DESC LIMIT 20",
        (player_id,),
    ).fetchall()
    return {"player": dict(p), "history": [dict(r) for r in history],
            "positions": [dict(r) for r in positions]}


@router.post("")
def create_player(body: PlayerIn):
    pid = upsert_player(body.name, body.governor_id, body.alliance, body.rank)
    get_conn().commit()
    return {"id": pid}


@router.get("/prune-preview")
def prune_preview(days: int = 7, admin=Depends(require_admin)):
    """List governors that pruning would remove (not seen in `days` days)."""
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = get_conn().execute(_prune_query(cutoff), (cutoff,)).fetchall()
    return {"cutoff": cutoff, "count": len(rows),
            "names": [r["name"] for r in rows][:300]}


@router.post("/prune")
def prune(days: int = 7, admin=Depends(require_admin)):
    """Delete governors not seen in any scan within the last `days` days.
    Run this right after a full scan to drop departed players + old misreads."""
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    conn = get_conn()
    cur = conn.execute(
        f"DELETE FROM players WHERE id IN ({_prune_query(cutoff)})", (cutoff,))
    conn.commit()
    return {"removed": cur.rowcount, "cutoff": cutoff}


@router.delete("/{player_id}")
def delete_player(player_id: int, admin=Depends(require_admin)):
    """Delete one governor and all their history (for junk/misread names)."""
    conn = get_conn()
    conn.execute("DELETE FROM players WHERE id=?", (player_id,))
    conn.commit()
    return {"ok": True}
