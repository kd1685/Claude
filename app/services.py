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


def record_map_position(player_id: int, name: str, kingdom: int | None,
                        x: int | None, y: int | None, source: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO map_positions (player_id, name, kingdom, x, y, captured_at, source)"
        " VALUES (?,?,?,?,?,?,?)",
        (player_id, name, kingdom, x, y, today(), source),
    )
    conn.commit()
