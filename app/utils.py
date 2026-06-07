"""Shared helpers used across API routes and services."""
from __future__ import annotations

import datetime as dt
import sqlite3


def today() -> str:
    """Today's date as an ISO string (YYYY-MM-DD)."""
    return dt.date.today().isoformat()


def date_range(frm: str | None, to: str | None, default_days: int = 30) -> tuple[str, str]:
    """Normalise an optional from/to date pair into concrete ISO strings.

    *to* defaults to today; *frm* defaults to ``default_days`` before *to*.
    """
    to = to or today()
    frm = frm or (dt.date.fromisoformat(to) - dt.timedelta(days=default_days)).isoformat()
    return frm, to


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    """Convert a list of ``sqlite3.Row`` objects to plain dicts."""
    return [dict(r) for r in rows]


def add_positions(items: list[dict], start: int = 1) -> list[dict]:
    """Number each item with a ``position`` key (in-place, for convenience)."""
    for i, item in enumerate(items, start):
        item["position"] = i
    return items
