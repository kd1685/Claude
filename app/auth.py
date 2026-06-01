"""Per-officer session auth for the Control page.

Data pages and their APIs are public. Everything under /api/control requires a
valid session cookie, obtained by POSTing officer credentials to
/api/auth/login. Tokens are HMAC-signed (stdlib only) with an expiry and carry
the user id — the user is re-checked against the DB (and `active` flag) on every
request, so deactivating an officer takes effect immediately. No server-side
session store.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException, Request

from . import users
from .config import config

COOKIE = "rok_session"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: str) -> str:
    sig = hmac.new(config.CONTROL_SECRET.encode(), payload.encode(),
                   hashlib.sha256).digest()
    return _b64(sig)


def make_token(user, ttl: int | None = None) -> str:
    body = {"uid": user["id"], "exp": int(time.time()) + (ttl or config.SESSION_TTL)}
    payload = _b64(json.dumps(body).encode())
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str) -> dict | None:
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        body = json.loads(_unb64(payload))
        if float(body.get("exp", 0)) <= time.time():
            return None
        return body
    except Exception:
        return None


def current_user(request: Request):
    """Return the authenticated, still-active user row, or None."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    body = verify_token(token)
    if not body:
        return None
    user = users.get_user(body.get("uid"))
    if not user or not user["active"]:
        return None
    return user


def require_auth(request: Request):
    """Dependency: any logged-in officer. Returns the user row."""
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def require_admin(request: Request):
    """Dependency: admin officers only."""
    user = require_auth(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin privileges required")
    return user
