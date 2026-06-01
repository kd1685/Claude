"""Login / logout / session-check for the Control page."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..auth import COOKIE, check_password, is_authed, make_token
from ..config import config

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, response: Response):
    if not check_password(body.password):
        raise HTTPException(401, "invalid password")
    response.set_cookie(
        COOKIE, make_token(), max_age=config.SESSION_TTL,
        httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/",
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return {
        "authenticated": is_authed(request),
        "default_password": config.password_is_default,
    }
