"""Officer accounts: password hashing (stdlib pbkdf2) and CRUD."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import sqlite3

from .config import config
from .db import get_conn

_log = logging.getLogger(__name__)

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        _log.warning("password verification failed (possibly corrupt hash)", exc_info=True)
        return False


def count_users() -> int:
    return get_conn().execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def get_user(user_id: int):
    return get_conn().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def get_user_by_username(username: str):
    return get_conn().execute(
        "SELECT * FROM users WHERE username=?", (username,)).fetchone()


def list_users() -> list[dict]:
    rows = get_conn().execute(
        "SELECT id, username, role, active, must_change_password, created_at, last_login "
        "FROM users ORDER BY role='admin' DESC, username"
    ).fetchall()
    return [dict(r) for r in rows]


def create_user(username: str, password: str, role: str = "officer",
                must_change: bool = False) -> int:
    username = username.strip()
    if not username or not password:
        raise ValueError("username and password are required")
    if role not in ("admin", "officer"):
        raise ValueError("role must be 'admin' or 'officer'")
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password) "
            "VALUES (?,?,?,?)",
            (username, hash_password(password), role, 1 if must_change else 0),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"username '{username}' already exists")
    return int(cur.lastrowid)


def set_active(user_id: int, active: bool) -> None:
    conn = get_conn()
    conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
    conn.commit()


def set_password(user_id: int, password: str, must_change: bool = False) -> None:
    if not password:
        raise ValueError("password is required")
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=?, must_change_password=? WHERE id=?",
                 (hash_password(password), 1 if must_change else 0, user_id))
    conn.commit()


def set_must_change(user_id: int, must_change: bool) -> None:
    conn = get_conn()
    conn.execute("UPDATE users SET must_change_password=? WHERE id=?",
                 (1 if must_change else 0, user_id))
    conn.commit()


def touch_login(user_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user_id,))
    conn.commit()


def authenticate(username: str, password: str):
    """Return the user row on success, else None."""
    u = get_user_by_username(username)
    if u and u["active"] and verify_password(password, u["password_hash"]):
        return u
    return None


def ensure_bootstrap_admin() -> None:
    """Create the first admin from config if the users table is empty."""
    if count_users() == 0:
        create_user(config.ADMIN_USERNAME, config.ADMIN_PASSWORD, "admin")
