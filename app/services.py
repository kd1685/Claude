"""Shared business logic used by both the HTTP API and the control worker."""
from __future__ import annotations

import datetime as dt
import json

from .db import get_conn, upsert_player, upsert_snapshot

VALID_KINDS = {"power", "killpoints", "dead", "rss"}


def today() -> str:
    return dt.date.today().isoformat()


def ingest_scan(kind: str, rows: list[dict], *, captured_at: str | None = None,
                source: str = "manual", device: str | None = None) -> dict:
    """Persist a rankings scan: create the scan record, upsert players and
    coalesce each row into that day's snapshot. Returns a summary dict."""
    captured_at = captured_at or today()
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO scans (kind, captured_at, source, device, rows, meta) "
        "VALUES (?,?,?,?,?,?)",
        (kind, captured_at, source, device, len(rows),
         json.dumps({"ingested": True})),
    )
    scan_id = int(cur.lastrowid)

    ingested = 0
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        pid = upsert_player(
            name=name,
            governor_id=row.get("governor_id"),
            alliance=row.get("alliance"),
        )
        upsert_snapshot(pid, captured_at, row)
        ingested += 1

    conn.commit()
    return {"scan_id": scan_id, "kind": kind, "captured_at": captured_at,
            "ingested": ingested}


def ingest_rallies(rows: list[dict], *, captured_at: str | None = None,
                   source: str = "scan") -> dict:
    """Log rallies read from the alliance war reports. Skips ones already logged
    today for the same leader+target so repeated scans don't double-count."""
    captured_at = captured_at or today()
    conn = get_conn()
    added = 0
    for row in rows:
        leader = (row.get("leader_name") or "").strip()
        if not leader:
            continue
        target = (row.get("target_label") or "").strip()
        dup = conn.execute(
            "SELECT 1 FROM rallies WHERE captured_at=? AND leader_name=? "
            "AND COALESCE(target_label,'')=? LIMIT 1",
            (captured_at, leader, target),
        ).fetchone()
        if dup:
            continue
        pid = None
        p = conn.execute("SELECT id FROM players WHERE name=?", (leader,)).fetchone()
        if p:
            pid = p["id"]
        conn.execute(
            "INSERT INTO rallies (captured_at, leader_id, leader_name, target_type, "
            "target_label, troops, status, source) VALUES (?,?,?,?,?,?,?,?)",
            (captured_at, pid, leader, row.get("target_type"), target or None,
             row.get("troops"), row.get("status"), source),
        )
        added += 1
    conn.commit()
    return {"captured_at": captured_at, "logged": added, "seen": len(rows)}


def record_map_position(player_id: int, name: str, kingdom: int | None,
                        x: int | None, y: int | None, source: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO map_positions (player_id, name, kingdom, x, y, captured_at, source)"
        " VALUES (?,?,?,?,?,?,?)",
        (player_id, name, kingdom, x, y, today(), source),
    )
    conn.commit()
