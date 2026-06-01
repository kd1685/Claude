"""Login / logout / session info, and admin-only officer management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import users
from ..auth import COOKIE, current_user, make_token, require_admin, require_auth
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


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
def login(body: LoginIn, response: Response):
    user = users.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(401, "invalid username or password")
    users.touch_login(user["id"])
    response.set_cookie(
        COOKIE, make_token(user), max_age=config.SESSION_TTL,
        httponly=True, samesite=config.COOKIE_SAMESITE, secure=config.COOKIE_SECURE, path="/",
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
        "must_change_password": bool(user["must_change_password"]),
        # Warn the admin while the seeded admin password is still the default.
        "default_password": user["role"] == "admin" and config.admin_password_is_default,
    }


# ---- self-service (any logged-in officer) ----

@router.post("/change-password")
def change_password(body: ChangePasswordIn, response: Response, user=Depends(require_auth)):
    if not users.verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(400, "current password is incorrect")
    if len(body.new_password) < 6:
        raise HTTPException(400, "new password must be at least 6 characters")
    if body.new_password == body.current_password:
        raise HTTPException(400, "new password must differ from the current one")
    users.set_password(user["id"], body.new_password, must_change=False)
    # Re-issue the session so the cookie stays valid after the change.
    response.set_cookie(
        COOKIE, make_token(user), max_age=config.SESSION_TTL,
        httponly=True, samesite=config.COOKIE_SAMESITE, secure=config.COOKIE_SECURE, path="/",
    )
    return {"ok": True}


# ---- admin-only officer management ----

@router.get("/users")
def get_users(admin=Depends(require_admin)):
    return users.list_users()


@router.post("/users")
def add_user(body: UserIn, admin=Depends(require_admin)):
    # New officers get a temp password and must change it on first login.
    try:
        uid = users.create_user(body.username, body.password, body.role,
                                must_change=True)
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
    # An admin reset is a temp password — force the officer to change it.
    try:
        users.set_password(user_id, body.password, must_change=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.post("/users/{user_id}/force-change")
def force_change(user_id: int, value: bool = True, admin=Depends(require_admin)):
    """Flag (or clear) an existing account to change its password next login,
    without resetting the password."""
    users.set_must_change(user_id, value)
    return {"ok": True}
