"""Unit tests for app/control/rotation.py — title rotation state machine."""
import os
import tempfile
import uuid

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_rotation.db")
os.environ["CONTROL_BACKEND"] = "mock"

from app.db import get_conn, init_db, upsert_player  # noqa: E402
from app.control.rotation import (  # noqa: E402
    active_rotation,
    cancel,
    create_rotation,
    get_running,
    list_rotations,
    skip_current,
    step,
)


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    # Clean state for each test.
    conn = get_conn()
    conn.execute("DELETE FROM rotation_members")
    conn.execute("DELETE FROM rotations")
    conn.execute("DELETE FROM commands")
    conn.commit()
    yield


def _make_user():
    """Create a user with a unique name for rotation creation."""
    conn = get_conn()
    uname = f"rotuser_{uuid.uuid4().hex[:8]}"
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
        (uname, "hash", "admin"),
    )
    conn.commit()
    return {"id": cur.lastrowid, "username": uname}


def _make_players(n=3):
    """Create n test players with unique names, return their IDs."""
    prefix = uuid.uuid4().hex[:6]
    return [upsert_player(name=f"RotP_{prefix}_{i}", governor_id=f"RP_{prefix}_{i}") for i in range(n)]


class TestCreateRotation:
    def test_basic_creation(self):
        user = _make_user()
        pids = _make_players(2)
        rid = create_rotation("Justice", pids, 60, user)
        assert rid > 0
        conn = get_conn()
        rot = conn.execute("SELECT * FROM rotations WHERE id=?", (rid,)).fetchone()
        assert rot["title"] == "Justice"
        assert rot["hold_seconds"] == 60
        assert rot["status"] == "running"

    def test_invalid_title_raises(self):
        user = _make_user()
        pids = _make_players(1)
        with pytest.raises(ValueError, match="title"):
            create_rotation("InvalidTitle", pids, 60, user)

    def test_empty_player_list_raises(self):
        user = _make_user()
        with pytest.raises(ValueError, match="at least one"):
            create_rotation("Duke", [], 60, user)

    def test_nonexistent_player_raises(self):
        user = _make_user()
        with pytest.raises(ValueError, match="not found"):
            create_rotation("Duke", [99999], 60, user)

    def test_duplicate_rotation_raises(self):
        user = _make_user()
        pids = _make_players(2)
        create_rotation("Architect", pids, 60, user)
        with pytest.raises(ValueError, match="already running"):
            create_rotation("Scientist", pids, 60, user)

    def test_hold_seconds_clamped(self):
        user = _make_user()
        pids = _make_players(1)
        rid = create_rotation("Duke", pids, 99999, user)
        conn = get_conn()
        rot = conn.execute("SELECT * FROM rotations WHERE id=?", (rid,)).fetchone()
        assert rot["hold_seconds"] == 3600  # MAX_HOLD

    def test_members_recorded(self):
        user = _make_user()
        pids = _make_players(3)
        rid = create_rotation("Scientist", pids, 0, user)
        conn = get_conn()
        members = conn.execute(
            "SELECT * FROM rotation_members WHERE rotation_id=? ORDER BY position",
            (rid,)
        ).fetchall()
        assert len(members) == 3
        assert all(m["status"] == "waiting" for m in members)


class TestCancel:
    def test_cancel_running_rotation(self):
        user = _make_user()
        pids = _make_players(2)
        rid = create_rotation("Justice", pids, 60, user)
        assert cancel(rid) is True
        conn = get_conn()
        rot = conn.execute("SELECT * FROM rotations WHERE id=?", (rid,)).fetchone()
        assert rot["status"] == "cancelled"

    def test_cancel_nonexistent(self):
        assert cancel(99999) is False


class TestStep:
    def test_no_rotation_returns_false(self):
        assert step() is False

    def test_advances_through_members(self):
        user = _make_user()
        pids = _make_players(2)
        rid = create_rotation("Duke", pids, 0, user)
        # First step: activate first member.
        assert step() is True
        conn = get_conn()
        members = conn.execute(
            "SELECT * FROM rotation_members WHERE rotation_id=? ORDER BY position",
            (rid,)
        ).fetchall()
        # After first step with hold=0: member 0 should be active or done.
        statuses = [m["status"] for m in members]
        assert "active" in statuses or "done" in statuses

    def test_completes_rotation(self):
        user = _make_user()
        pids = _make_players(2)
        rid = create_rotation("Architect", pids, 0, user)
        # Step until rotation completes (max iterations as safety).
        for _ in range(20):
            if not step():
                break
        conn = get_conn()
        rot = conn.execute("SELECT * FROM rotations WHERE id=?", (rid,)).fetchone()
        assert rot["status"] == "done"


class TestSkipCurrent:
    def test_skip_with_active_member(self):
        user = _make_user()
        pids = _make_players(2)
        rid = create_rotation("Justice", pids, 3600, user)
        # Step to activate first member.
        step()
        assert skip_current(rid) is True
        conn = get_conn()
        members = conn.execute(
            "SELECT * FROM rotation_members WHERE rotation_id=? AND status='done'",
            (rid,)
        ).fetchall()
        assert len(members) >= 1

    def test_skip_with_no_active(self):
        # No active rotation — should return False.
        assert skip_current(99999) is False


class TestActiveRotation:
    def test_no_rotation(self):
        assert active_rotation() is None

    def test_with_running_rotation(self):
        user = _make_user()
        pids = _make_players(2)
        create_rotation("Scientist", pids, 180, user)
        info = active_rotation()
        assert info is not None
        assert info["rotation"]["title"] == "Scientist"
        assert info["total"] == 2
        assert len(info["members"]) == 2


class TestGetRunning:
    def test_no_rotation(self):
        assert get_running() is None

    def test_with_rotation(self):
        user = _make_user()
        pids = _make_players(1)
        create_rotation("Duke", pids, 60, user)
        rot = get_running()
        assert rot is not None
        assert rot["title"] == "Duke"


class TestListRotations:
    def test_empty(self):
        assert list_rotations() == []

    def test_returns_rotations(self):
        user = _make_user()
        pids = _make_players(1)
        create_rotation("Justice", pids, 0, user)
        rotations = list_rotations()
        assert len(rotations) >= 1
        assert rotations[0]["title"] == "Justice"
