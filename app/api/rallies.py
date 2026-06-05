"""Rally log endpoints."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_ready
from ..db import get_conn

router = APIRouter(prefix="/api/rallies", tags=["rallies"])


class RallyIn(BaseModel):
    captured_at: str | None = None
    leader_name: str | None = None
    leader_id: int | None = None
    target_type: str | None = None
    target_label: str | None = None
    x: int | None = None
    y: int | None = None
    troops: int | None = None
    status: str | None = None
    source: str = "manual"


@router.get("")
def list_rallies(frm: str | None = None, to: str | None = None, limit: int = 500):
    to = to or dt.date.today().isoformat()
    frm = frm or (dt.date.fromisoformat(to) - dt.timedelta(days=30)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM rallies WHERE captured_at BETWEEN ? AND ? "
        "ORDER BY captured_at DESC, id DESC LIMIT ?",
        (frm, to, limit),
    ).fetchall()
    agg = conn.execute(
        """SELECT captured_at,
                  COUNT(*) AS rallies,
                  SUM(COALESCE(troops,0)) AS troops,
                  SUM(status='win') AS wins
           FROM rallies WHERE captured_at BETWEEN ? AND ?
           GROUP BY captured_at ORDER BY captured_at""",
        (frm, to),
    ).fetchall()
    return {"from": frm, "to": to, "rows": [dict(r) for r in rows],
            "by_day": [dict(r) for r in agg]}


@router.get("/leaderboard")
def rally_leaderboard(frm: str | None = None, to: str | None = None, limit: int = 100):
    """Rank alliance members by rallies led over a date range."""
    to = to or dt.date.today().isoformat()
    frm = frm or (dt.date.fromisoformat(to) - dt.timedelta(days=30)).isoformat()
    rows = get_conn().execute(
        """SELECT leader_name,
                  COUNT(*) AS rallies,
                  SUM(COALESCE(troops,0)) AS troops,
                  SUM(status='win') AS wins
           FROM rallies
           WHERE captured_at BETWEEN ? AND ? AND leader_name IS NOT NULL AND leader_name<>''
           GROUP BY leader_name
           ORDER BY rallies DESC, troops DESC
           LIMIT ?""",
        (frm, to, limit),
    ).fetchall()
    out = []
    for i, r in enumerate(rows, 1):
        d = dict(r)
        d["position"] = i
        d["win_rate"] = round(100 * (d["wins"] or 0) / d["rallies"]) if d["rallies"] else 0
        out.append(d)
    return {"from": frm, "to": to, "rows": out}


@router.post("")
def create_rally(body: RallyIn, user=Depends(require_ready)):
    data = body.model_dump()
    data["captured_at"] = data["captured_at"] or dt.date.today().isoformat()
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO rallies
           (captured_at, leader_id, leader_name, target_type, target_label,
            x, y, troops, status, source)
           VALUES (:captured_at,:leader_id,:leader_name,:target_type,:target_label,
                   :x,:y,:troops,:status,:source)""",
        data,
    )
    conn.commit()
    return {"id": int(cur.lastrowid)}
