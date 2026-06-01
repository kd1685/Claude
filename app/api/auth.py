"""Login / logout / session info, and admin-only officer management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import users
from ..auth import COOKIE, current_user, make_token, require_admin
from ..config import config

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "officer"


class PasswordIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, response: Response):
    user = users.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(401, "invalid username or password")
    users.touch_login(user["id"])
    response.set_cookie(
        COOKIE, make_token(user), max_age=config.SESSION_TTL,
        httponly=True, samesite="lax", secure=config.COOKIE_SECURE, path="/",
    )
    return {"ok": True, "username": user["username"], "role": user["role"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = current_user(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": user["username"],
        "role": user["role"],
        # Warn the admin while the seeded admin password is still the default.
        "default_password": user["role"] == "admin" and config.admin_password_is_default,
    }


# ---- admin-only officer management ----

@router.get("/users")
def get_users(admin=Depends(require_admin)):
    return users.list_users()


@router.post("/users")
def add_user(body: UserIn, admin=Depends(require_admin)):
    try:
        uid = users.create_user(body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": uid}


@router.post("/users/{user_id}/active")
def set_active(user_id: int, active: bool, admin=Depends(require_admin)):
    if user_id == admin["id"] and not active:
        raise HTTPException(400, "you cannot deactivate your own account")
    users.set_active(user_id, active)
    return {"ok": True}


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordIn, admin=Depends(require_admin)):
    try:
        users.set_password(user_id, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}
