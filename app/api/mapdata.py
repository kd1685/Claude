"""Map positions for the kingdom map view."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from ..db import get_conn

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/positions")
def positions(date: str | None = None):
    """Latest known position per player as of `date`."""
    date = date or dt.date.today().isoformat()
    rows = get_conn().execute(
        """
        SELECT m.player_id, m.name, m.kingdom, m.x, m.y, m.captured_at, p.alliance
        FROM map_positions m
        LEFT JOIN players p ON p.id = m.player_id
        WHERE m.id = (
            SELECT id FROM map_positions m2
            WHERE m2.player_id = m.player_id AND m2.captured_at <= ?
            ORDER BY id DESC LIMIT 1)
        ORDER BY m.name
        """,
        (date,),
    ).fetchall()
    return {"date": date, "positions": [dict(r) for r in rows]}
