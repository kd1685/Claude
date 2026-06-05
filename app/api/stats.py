"""Date-filtered statistics endpoints (leaderboards, gains, kingdom totals)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db import get_conn
from ..utils import add_positions, date_range, rows_to_dicts, today

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
    date = date or today()
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
        add_positions(out)
    return {"metric": col, "date": date, "from": frm, "count": len(out), "rows": out}


@router.get("/kingdom-totals")
def kingdom_totals(
    metric: str = "power",
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = None,
):
    """Per-day kingdom-wide totals for charting a metric over a date range."""
    col = _col(metric)
    frm, to = date_range(frm, to, default_days=30)
    rows = get_conn().execute(
        f"""SELECT captured_at, SUM({col}) AS total, COUNT({col}) AS players
            FROM snapshots
            WHERE captured_at BETWEEN ? AND ? AND {col} IS NOT NULL
            GROUP BY captured_at ORDER BY captured_at""",
        (frm, to),
    ).fetchall()
    return {"metric": col, "from": frm, "to": to,
            "series": rows_to_dicts(rows)}


@router.get("/dkp")
def dkp(
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    w_t4: float = 1.0,
    w_t5: float = 2.0,
    w_dead: float = 5.0,
    limit: int = 200,
):
    """KvK-style DKP leaderboard: points from T4/T5 kills + deads *gained*
    between two dates, each weighted. Defaults: T4×1, T5×2, deads×5."""
    frm, to = date_range(frm, to, default_days=14)
    conn = get_conn()
    players = conn.execute("SELECT id, name, alliance FROM players").fetchall()
    out = []
    for p in players:
        parts = {}
        for col, w in (("t4_kills", w_t4), ("t5_kills", w_t5), ("deads", w_dead)):
            end = _value_at(conn, p["id"], col, to)
            start = _value_at(conn, p["id"], col, frm)
            parts[col] = (end - start) if (end is not None and start is not None) else 0
        score = parts["t4_kills"] * w_t4 + parts["t5_kills"] * w_t5 + parts["deads"] * w_dead
        if score <= 0:
            continue
        out.append({"player_id": p["id"], "name": p["name"], "alliance": p["alliance"],
                    "dkp": round(score), "t4_gain": parts["t4_kills"],
                    "t5_gain": parts["t5_kills"], "dead_gain": parts["deads"]})
    out.sort(key=lambda d: d["dkp"], reverse=True)
    out = out[:limit]
    add_positions(out)
    return {"from": frm, "to": to,
            "weights": {"t4": w_t4, "t5": w_t5, "dead": w_dead}, "rows": out}


@router.get("/alerts")
def alerts(
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = None,
    power_drop: int = 1_000_000,
    dead_spike: int = 500_000,
):
    """Governors whose power dropped (possible quit/migration) or whose deads
    spiked, between two dates."""
    frm, to = date_range(frm, to, default_days=7)
    conn = get_conn()
    drops, spikes = [], []
    for p in conn.execute("SELECT id, name, alliance FROM players").fetchall():
        p_end, p_start = _value_at(conn, p["id"], "power", to), _value_at(conn, p["id"], "power", frm)
        if p_end is not None and p_start is not None and (p_start - p_end) >= power_drop:
            drops.append({"player_id": p["id"], "name": p["name"], "alliance": p["alliance"],
                          "lost": p_start - p_end})
        d_end, d_start = _value_at(conn, p["id"], "deads", to), _value_at(conn, p["id"], "deads", frm)
        if d_end is not None and d_start is not None and (d_end - d_start) >= dead_spike:
            spikes.append({"player_id": p["id"], "name": p["name"], "alliance": p["alliance"],
                           "gained": d_end - d_start})
    drops.sort(key=lambda d: d["lost"], reverse=True)
    spikes.sort(key=lambda d: d["gained"], reverse=True)
    return {"from": frm, "to": to, "power_drops": drops[:50], "dead_spikes": spikes[:50]}


@router.get("/summary")
def summary(date: str | None = None):
    """Headline numbers for the dashboard at a given date."""
    date = date or today()
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
