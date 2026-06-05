"""Unit tests for app/control/worker.py — command dispatch and enqueue."""
import json
import os
import tempfile

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_worker.db")
os.environ["CONTROL_BACKEND"] = "mock"

from app.db import get_conn, init_db, upsert_player  # noqa: E402
from app.control.worker import _dispatch, _process_one, enqueue  # noqa: E402


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    yield


class TestEnqueue:
    def test_basic_enqueue(self):
        pid = upsert_player(name="EnqPlayer1", governor_id="EQ1")
        cid = enqueue("locate", player_id=pid, params={"extra": "val"})
        assert cid > 0
        conn = get_conn()
        cmd = conn.execute("SELECT * FROM commands WHERE id=?", (cid,)).fetchone()
        assert cmd["kind"] == "locate"
        assert cmd["player_id"] == pid
        assert cmd["status"] == "pending"
        assert json.loads(cmd["params"]) == {"extra": "val"}

    def test_enqueue_with_issuer(self):
        cid = enqueue("scan", issued_by=None, issued_by_name="officer1")
        conn = get_conn()
        cmd = conn.execute("SELECT * FROM commands WHERE id=?", (cid,)).fetchone()
        assert cmd["issued_by_name"] == "officer1"

    def test_enqueue_no_params(self):
        pid = upsert_player(name="EnqPlayer2", governor_id="EQ2")
        cid = enqueue("locate", player_id=pid)
        conn = get_conn()
        cmd = conn.execute("SELECT * FROM commands WHERE id=?", (cid,)).fetchone()
        assert json.loads(cmd["params"]) == {}


class TestDispatch:
    def _make_cmd(self, kind, player_id=None, params=None):
        """Create a fake command row dict (simulating what comes from DB)."""
        return {
            "id": 1,
            "kind": kind,
            "player_id": player_id,
            "params": json.dumps(params or {}),
        }

    def test_dispatch_locate(self):
        pid = upsert_player(name="DispatchPlayer", governor_id="D001")
        cmd = self._make_cmd("locate", player_id=pid)
        result = _dispatch(cmd)
        assert result.ok is True
        assert "x" in result.data

    def test_dispatch_give_title(self):
        pid = upsert_player(name="TitlePlayer", governor_id="T001")
        conn = get_conn()
        conn.execute(
            "INSERT INTO map_positions (player_id, name, kingdom, x, y, captured_at, source) "
            "VALUES (?,?,?,?,?,?,?)",
            (pid, "TitlePlayer", 1685, 50, 60, "2026-01-01", "test"),
        )
        conn.commit()
        cmd = self._make_cmd("give_title", player_id=pid, params={"title": "Justice"})
        result = _dispatch(cmd)
        assert result.ok is True

    def test_dispatch_change_rank(self):
        pid = upsert_player(name="RankPlayer", governor_id="R001")
        cmd = self._make_cmd("change_rank", player_id=pid, params={"new_rank": 3})
        result = _dispatch(cmd)
        assert result.ok is True

    def test_dispatch_scan(self):
        cmd = self._make_cmd("scan", params={"kind": "power", "pages": 1})
        result = _dispatch(cmd)
        assert result.ok is True
        assert "rows" in result.data

    def test_dispatch_scan_profiles(self):
        cmd = self._make_cmd("scan_profiles", params={"count": 3})
        result = _dispatch(cmd)
        assert result.ok is True

    def test_dispatch_scan_rallies(self):
        cmd = self._make_cmd("scan_rallies", params={"pages": 1})
        result = _dispatch(cmd)
        assert result.ok is True

    def test_dispatch_unknown_kind_raises(self):
        cmd = self._make_cmd("nonexistent")
        with pytest.raises(ValueError, match="unknown command kind"):
            _dispatch(cmd)


class TestProcessOne:
    def test_no_pending_commands(self):
        # Clear any pending commands from other tests.
        conn = get_conn()
        conn.execute("UPDATE commands SET status='done' WHERE status='pending'")
        conn.commit()
        assert _process_one() is False

    def test_processes_pending_command(self):
        pid = upsert_player(name="ProcessPlayer", governor_id="P001")
        # Clear existing pending commands first.
        conn = get_conn()
        conn.execute("UPDATE commands SET status='done' WHERE status='pending'")
        conn.commit()
        enqueue("locate", player_id=pid)
        assert _process_one() is True
        cmd = conn.execute(
            "SELECT * FROM commands WHERE player_id=? ORDER BY id DESC LIMIT 1",
            (pid,)
        ).fetchone()
        assert cmd["status"] == "done"

    def test_failed_command(self):
        # Clear existing pending commands first.
        conn = get_conn()
        conn.execute("UPDATE commands SET status='done' WHERE status='pending'")
        conn.commit()
        # Enqueue a command for a nonexistent player (player_id=None to avoid FK issue,
        # but locate on None player_id will raise in actions.locate).
        cid = enqueue("locate", player_id=None)
        assert _process_one() is True
        cmd = conn.execute("SELECT * FROM commands WHERE id=?", (cid,)).fetchone()
        assert cmd["status"] == "failed"
        assert cmd["error"] is not None
