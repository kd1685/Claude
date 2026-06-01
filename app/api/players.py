"""Player directory + per-player history."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn, upsert_player
from ..models import PlayerIn

router = APIRouter(prefix="/api/players", tags=["players"])


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


@router.get("/{player_id}")
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
