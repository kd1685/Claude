"""Date-filtered statistics endpoints (leaderboards, gains, kingdom totals)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn

router = APIRouter(prefix="/api/stats", tags=["stats"])

# Whitelist of metric -> snapshot column (prevents SQL injection via metric).
METRICS = {
    "power": "power",
    "kill_points": "kill_points",
    "kp": "kill_points",
    "deads": "deads",
    "dead": "deads",
    "t4_kills": "t4_kills",
    "t5_kills": "t5_kills",
    "rss_gathered": "rss_gathered",
    "rss_assist": "rss_assist",
    "helps": "helps",
}


def _col(metric: str) -> str:
    col = METRICS.get(metric)
    if not col:
        raise HTTPException(400, f"unknown metric '{metric}'. valid: {sorted(set(METRICS))}")
    return col


def _value_at(conn, player_id: int, col: str, date: str):
    row = conn.execute(
        f"SELECT {col} AS v FROM snapshots WHERE player_id=? AND captured_at<=? "
        f"AND {col} IS NOT NULL ORDER BY captured_at DESC LIMIT 1",
        (player_id, date),
    ).fetchone()
    return row["v"] if row else None


@router.get("/dates")
def available_dates():
    rows = get_conn().execute(
        "SELECT DISTINCT captured_at FROM snapshots ORDER BY captured_at DESC"
    ).fetchall()
    return [r["captured_at"] for r in rows]


@router.get("/leaderboard")
def leaderboard(
    metric: str = "power",
    date: str | None = None,
    frm: str | None = Query(default=None, alias="from"),
    limit: int = 100,
):
    """Ranked players for `metric` as of `date`. If `from` is given, also
    returns the gain (delta) accumulated between `from` and `date`."""
    col = _col(metric)
    date = date or dt.date.today().isoformat()
    conn = get_conn()
    rows = conn.execute(
        f"""
        SELECT p.id, p.name, p.alliance, p.rank, s.captured_at, s.{col} AS value
        FROM players p
        JOIN snapshots s ON s.player_id = p.id
        WHERE s.captured_at <= ? AND s.{col} IS NOT NULL
          AND s.captured_at = (
              SELECT MAX(s2.captured_at) FROM snapshots s2
              WHERE s2.player_id = p.id AND s2.captured_at <= ? AND s2.{col} IS NOT NULL
          )
        ORDER BY value DESC
        LIMIT ?
        """,
        (date, date, limit),
    ).fetchall()

    out = []
    for i, r in enumerate(rows, 1):
        item = {"position": i, "player_id": r["id"], "name": r["name"],
                "alliance": r["alliance"], "rank": r["rank"],
                "as_of": r["captured_at"], "value": r["value"]}
        if frm:
            base = _value_at(conn, r["id"], col, frm)
            item["base"] = base
            item["gain"] = (r["value"] - base) if base is not None else None
        out.append(item)
    if frm:
        out.sort(key=lambda d: (d["gain"] is None, -(d["gain"] or 0)))
        for i, item in enumerate(out, 1):
            item["position"] = i
    return {"metric": col, "date": date, "from": frm, "count": len(out), "rows": out}


@router.get("/kingdom-totals")
def kingdom_totals(
    metric: str = "power",
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = None,
):
    """Per-day kingdom-wide totals for charting a metric over a date range."""
    col = _col(metric)
    to = to or dt.date.today().isoformat()
    frm = frm or (dt.date.fromisoformat(to) - dt.timedelta(days=30)).isoformat()
    rows = get_conn().execute(
        f"""SELECT captured_at, SUM({col}) AS total, COUNT({col}) AS players
            FROM snapshots
            WHERE captured_at BETWEEN ? AND ? AND {col} IS NOT NULL
            GROUP BY captured_at ORDER BY captured_at""",
        (frm, to),
    ).fetchall()
    return {"metric": col, "from": frm, "to": to,
            "series": [dict(r) for r in rows]}


@router.get("/summary")
def summary(date: str | None = None):
    """Headline numbers for the dashboard at a given date."""
    date = date or dt.date.today().isoformat()
    conn = get_conn()

    def total(col: str):
        r = conn.execute(
            f"""SELECT SUM({col}) t, COUNT({col}) n FROM snapshots s
                WHERE captured_at = (
                  SELECT MAX(captured_at) FROM snapshots s2
                  WHERE s2.player_id=s.player_id AND s2.captured_at<=? AND s2.{col} IS NOT NULL)
                AND {col} IS NOT NULL""",
            (date,),
        ).fetchone()
        return r["t"], r["n"]

    power, governors = total("power")
    kp, _ = total("kill_points")
    deads, _ = total("deads")
    return {
        "date": date,
        "governors": governors or 0,
        "total_power": power or 0,
        "total_kill_points": kp or 0,
        "total_deads": deads or 0,
    }
