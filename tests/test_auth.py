"""Unit tests for app/auth.py — HMAC-signed session tokens."""
import os
import tempfile
import time

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_auth.db")
os.environ["CONTROL_BACKEND"] = "mock"
os.environ["CONTROL_SECRET"] = "test-secret-key-for-tests"

from app.auth import _b64, _unb64, make_token, verify_token  # noqa: E402
from app.db import init_db  # noqa: E402
from app.users import create_user, get_user  # noqa: E402


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    yield


class TestBase64Helpers:
    def test_roundtrip(self):
        data = b"hello world"
        encoded = _b64(data)
        assert _unb64(encoded) == data

    def test_empty(self):
        assert _unb64(_b64(b"")) == b""

    def test_padding_stripped(self):
        encoded = _b64(b"a")
        assert "=" not in encoded
        assert _unb64(encoded) == b"a"


class TestMakeToken:
    def test_returns_payload_dot_signature(self):
        uid = create_user("tokenuser", "pass")
        user = get_user(uid)
        token = make_token(user)
        assert "." in token
        parts = token.split(".")
        assert len(parts) == 2

    def test_custom_ttl(self):
        uid = create_user("ttluser", "pass")
        user = get_user(uid)
        token = make_token(user, ttl=60)
        body = verify_token(token)
        assert body is not None
        assert body["exp"] <= int(time.time()) + 61


class TestVerifyToken:
    def test_valid_token(self):
        uid = create_user("validuser", "pass")
        user = get_user(uid)
        token = make_token(user)
        body = verify_token(token)
        assert body is not None
        assert body["uid"] == uid

    def test_expired_token(self):
        uid = create_user("expuser", "pass")
        user = get_user(uid)
        token = make_token(user, ttl=-10)  # already expired
        assert verify_token(token) is None

    def test_tampered_payload(self):
        uid = create_user("tamperuser", "pass")
        user = get_user(uid)
        token = make_token(user)
        payload, sig = token.split(".")
        # Flip a character in the payload.
        tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
        assert verify_token(f"{tampered}.{sig}") is None

    def test_tampered_signature(self):
        uid = create_user("tamperuser2", "pass")
        user = get_user(uid)
        token = make_token(user)
        payload, sig = token.split(".")
        bad_sig = sig[:-1] + ("X" if sig[-1] != "X" else "Y")
        assert verify_token(f"{payload}.{bad_sig}") is None

    def test_garbage_input(self):
        assert verify_token("not.a.valid.token") is None
        assert verify_token("") is None
        assert verify_token("nodot") is None
