"""Unit tests for app/db.py — upsert helpers and schema init."""
import os
import tempfile

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_db.db")
os.environ["CONTROL_BACKEND"] = "mock"

from app.db import get_conn, init_db, upsert_player, upsert_snapshot  # noqa: E402


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    yield


class TestInitDb:
    def test_tables_created(self):
        conn = get_conn()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "players" in tables
        assert "scans" in tables
        assert "snapshots" in tables
        assert "commands" in tables
        assert "users" in tables
        assert "rotations" in tables
        assert "rotation_members" in tables
        assert "scan_schedules" in tables
        assert "events" in tables
        assert "rallies" in tables
        assert "map_positions" in tables

    def test_idempotent(self):
        # Calling init_db again should not raise.
        init_db()


class TestUpsertPlayer:
    def test_create_new_player(self):
        pid = upsert_player(name="NewPlayer")
        assert pid > 0
        conn = get_conn()
        row = conn.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
        assert row["name"] == "NewPlayer"
        assert row["rank"] == 1  # default

    def test_find_by_governor_id(self):
        pid1 = upsert_player(name="GovPlayer", governor_id="GOV123")
        pid2 = upsert_player(name="GovPlayerRenamed", governor_id="GOV123")
        assert pid1 == pid2
        conn = get_conn()
        row = conn.execute("SELECT * FROM players WHERE id=?", (pid1,)).fetchone()
        assert row["name"] == "GovPlayerRenamed"

    def test_find_by_name_fallback(self):
        pid1 = upsert_player(name="NameMatch")
        pid2 = upsert_player(name="NameMatch", alliance="ABC")
        assert pid1 == pid2
        conn = get_conn()
        row = conn.execute("SELECT * FROM players WHERE id=?", (pid1,)).fetchone()
        assert row["alliance"] == "ABC"

    def test_updates_coalesce_nulls(self):
        pid = upsert_player(name="CoalesceTest", governor_id="C001", alliance="OLD")
        # Updating with None alliance should not overwrite.
        upsert_player(name="CoalesceTest", governor_id="C001", alliance=None)
        conn = get_conn()
        row = conn.execute("SELECT * FROM players WHERE id=?", (pid,)).fetchone()
        assert row["alliance"] == "OLD"

    def test_different_names_create_different_players(self):
        pid1 = upsert_player(name="Player1")
        pid2 = upsert_player(name="Player2")
        assert pid1 != pid2


class TestUpsertSnapshot:
    def test_creates_snapshot(self):
        pid = upsert_player(name="SnapPlayer")
        upsert_snapshot(pid, "2026-06-01", {"power": 42_000_000})
        conn = get_conn()
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE player_id=? AND captured_at='2026-06-01'",
            (pid,)
        ).fetchone()
        assert snap["power"] == 42_000_000

    def test_merges_values_same_day(self):
        pid = upsert_player(name="MergePlayer")
        upsert_snapshot(pid, "2026-06-02", {"power": 10})
        upsert_snapshot(pid, "2026-06-02", {"kill_points": 20})
        conn = get_conn()
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE player_id=? AND captured_at='2026-06-02'",
            (pid,)
        ).fetchone()
        assert snap["power"] == 10
        assert snap["kill_points"] == 20

    def test_no_update_with_empty_values(self):
        pid = upsert_player(name="EmptySnap")
        upsert_snapshot(pid, "2026-06-03", {})
        conn = get_conn()
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE player_id=? AND captured_at='2026-06-03'",
            (pid,)
        ).fetchone()
        # No snapshot row should be created when no valid columns.
        assert snap is None

    def test_all_snapshot_fields(self):
        pid = upsert_player(name="AllFields")
        values = {
            "power": 1, "kill_points": 2, "t1_kills": 3, "t2_kills": 4,
            "t3_kills": 5, "t4_kills": 6, "t5_kills": 7, "deads": 8,
            "rss_gathered": 9, "rss_assist": 10, "helps": 11,
        }
        upsert_snapshot(pid, "2026-06-04", values)
        conn = get_conn()
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE player_id=? AND captured_at='2026-06-04'",
            (pid,)
        ).fetchone()
        for field, val in values.items():
            assert snap[field] == val
