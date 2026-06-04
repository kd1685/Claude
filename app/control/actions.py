"""High-level account-control actions: adapter call + database side effects.

Each function is what the queue worker actually runs for a command.
"""
from __future__ import annotations

from ..db import get_conn
from ..models import TITLES
from ..services import ingest_rallies, ingest_scan, record_map_position
from . import get_adapter
from .adapter import ActionResult


def _player(player_id: int):
    row = get_conn().execute(
        "SELECT id, name, governor_id, rank FROM players WHERE id = ?",
        (player_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"player {player_id} not found")
    return row


def _latest_position(player_id: int):
    return get_conn().execute(
        "SELECT x, y FROM map_positions WHERE player_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (player_id,),
    ).fetchone()


def give_title(player_id: int, title: str) -> ActionResult:
    if title not in TITLES:
        return ActionResult(False, f"unknown title '{title}'; valid: {TITLES}")
    p = _player(player_id)
    pos = _latest_position(player_id)
    adapter = get_adapter()
    res = adapter.give_title(
        name=p["name"], governor_id=p["governor_id"],
        x=pos["x"] if pos else None, y=pos["y"] if pos else None, title=title,
    )
    return res


def change_rank(player_id: int, new_rank: int) -> ActionResult:
    if not 1 <= new_rank <= 5:
        return ActionResult(False, "rank must be 1..5")
    p = _player(player_id)
    adapter = get_adapter()
    res = adapter.change_rank(name=p["name"], governor_id=p["governor_id"],
                              new_rank=new_rank)
    if res.ok:
        conn = get_conn()
        conn.execute("UPDATE players SET rank = ? WHERE id = ?", (new_rank, player_id))
        conn.commit()
    return res


def locate(player_id: int) -> ActionResult:
    p = _player(player_id)
    adapter = get_adapter()
    res = adapter.locate(name=p["name"], governor_id=p["governor_id"])
    if res.ok:
        record_map_position(player_id, p["name"], res.data.get("kingdom"),
                            res.data.get("x"), res.data.get("y"), adapter.name)
    return res


def scan(kind: str, pages: int) -> ActionResult:
    adapter = get_adapter()
    res = adapter.scan_rankings(kind=kind, pages=pages)
    if res.ok:
        summary = ingest_scan(kind, res.data.get("rows", []), source=adapter.name,
                              device=adapter.status().get("device"))
        res.data["summary"] = summary
        res.detail += f" -> ingested {summary['ingested']} rows (scan #{summary['scan_id']})"
    return res


def scan_profiles(count: int) -> ActionResult:
    """Deep scan the top `count` governors incl. dead troops (opens each profile)."""
    adapter = get_adapter()
    res = adapter.scan_profiles(count=count)
    if res.ok:
        summary = ingest_scan("profile", res.data.get("rows", []), source=adapter.name)
        res.data["summary"] = summary
        res.detail += f" -> ingested {summary['ingested']} governors (incl. deads)"
    return res


def scan_rallies(pages: int) -> ActionResult:
    adapter = get_adapter()
    res = adapter.scan_rallies(pages=pages)
    if res.ok:
        summary = ingest_rallies(res.data.get("rows", []), source=adapter.name)
        res.data["summary"] = summary
        res.detail += f" -> logged {summary['logged']} new rallies"
    return res
