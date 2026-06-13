"""privacy.py — GDPR / data-privacy helpers for Ascent Terminal.

Provides:
  - /privacy/export  : export all data associated with an API key
  - /privacy/delete  : delete (anonymise) all data for an API key

These are intentionally conservative: they operate only on data stored
locally (keys.json + PostgreSQL via store_db).  Exchange data and
third-party service data is outside the platform’s control.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from auth import AuthenticatedUser, get_current_user
from store_db import DatabaseManager

router = APIRouter(prefix="/privacy", tags=["privacy"])

KEYS_FILE = Path("keys.json")
db = DatabaseManager()


def _load_keys() -> dict:
    try:
        return json.loads(KEYS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_keys(keys: dict) -> None:
    KEYS_FILE.write_text(json.dumps(keys, indent=2))


@router.get("/export")
async def export_data(user: AuthenticatedUser = Depends(get_current_user)):
    """Export all locally stored data for the authenticated API key."""
    keys = _load_keys()
    key_entry = keys.get(user.api_key, {})
    db_data = await db.export_user_data(user.api_key)
    return {
        "api_key": user.api_key,
        "tier": user.tier,
        "key_metadata": key_entry,
        "database_records": db_data,
    }


@router.delete("/delete")
async def delete_data(user: AuthenticatedUser = Depends(get_current_user)):
    """Anonymise / delete all locally stored data for the authenticated API key."""
    # Remove from keys.json
    keys = _load_keys()
    if user.api_key in keys:
        del keys[user.api_key]
        _save_keys(keys)

    # Remove from database
    deleted_rows = await db.delete_user_data(user.api_key)

    return {"deleted": True, "db_rows_removed": deleted_rows}
