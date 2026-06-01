"""Lightweight session auth for the Control page.

Data pages and their APIs are public. Everything under /api/control requires a
valid session cookie, obtained by POSTing the control password to
/api/auth/login. Tokens are HMAC-signed (stdlib only) with an expiry — no
external dependency, no server-side session store.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException, Request

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


def make_token(ttl: int | None = None) -> str:
    body = {"exp": int(time.time()) + (ttl or config.SESSION_TTL)}
    payload = _b64(json.dumps(body).encode())
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str) -> bool:
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return False
        body = json.loads(_unb64(payload))
        return float(body.get("exp", 0)) > time.time()
    except Exception:
        return False


def check_password(password: str) -> bool:
    return hmac.compare_digest(password or "", config.CONTROL_PASSWORD)


def is_authed(request: Request) -> bool:
    token = request.cookies.get(COOKIE)
    return bool(token and verify_token(token))


def require_auth(request: Request) -> None:
    """FastAPI dependency: 401 unless the request carries a valid session."""
    if not is_authed(request):
        raise HTTPException(status_code=401, detail="authentication required")
