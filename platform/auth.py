"""auth.py — API-key authentication + tier enforcement for Ascent Terminal.

Imported by other modules for require_tier / get_current_user.
The main FastAPI app is in app.py.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ACCESS_KEYS_RAW = os.getenv("ACCESS_KEYS", "")
ACCESS_KEYS: set[str] = set(filter(None, ACCESS_KEYS_RAW.split(",")))

KEYS_FILE = Path("keys.json")


# ---------------------------------------------------------------------------
# Key store helpers
# ---------------------------------------------------------------------------

def _load_keys() -> dict[str, dict]:
    try:
        return json.loads(KEYS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_keys(keys: dict[str, dict]) -> None:
    KEYS_FILE.write_text(json.dumps(keys, indent=2))


def _key_tier(api_key: str) -> str | None:
    """Return the tier for *api_key* or None if unknown / revoked."""
    if api_key in ACCESS_KEYS:
        return "architect"
    if api_key == "DEMO-KEY" and not ACCESS_KEYS:
        return "observer"
    store = _load_keys()
    entry = store.get(api_key)
    if entry and entry.get("active", True):
        return entry.get("tier", "observer")
    return None


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

TIER_RANK = {"observer": 1, "operator": 2, "architect": 3}


class AuthenticatedUser(BaseModel):
    api_key: str
    tier: str


async def get_current_user(x_api_key: str = Header(...)) -> AuthenticatedUser:
    tier = _key_tier(x_api_key)
    if tier is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    return AuthenticatedUser(api_key=x_api_key, tier=tier)


def require_tier(minimum: str):
    """Dependency factory — raises 403 if user tier is below *minimum*."""
    async def _check(user: AuthenticatedUser = Depends(get_current_user)):
        if TIER_RANK.get(user.tier, 0) < TIER_RANK.get(minimum, 99):
            raise HTTPException(
                status_code=403,
                detail=f"Requires '{minimum}' tier or above (you have '{user.tier}').",
            )
        return user
    return _check
