"""Unit tests for app/services.py — scan/rally ingestion logic."""
import os
import tempfile

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_services.db")
os.environ["CONTROL_BACKEND"] = "mock"

from app.db import get_conn, init_db  # noqa: E402
from app.services import ingest_rallies, ingest_scan, record_map_position  # noqa: E402


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    yield


class TestIngestScan:
    def test_basic_power_scan(self):
        result = ingest_scan("power", [
            {"name": "Alpha", "power": 50_000_000},
            {"name": "Bravo", "power": 30_000_000},
        ], captured_at="2026-01-01")
        assert result["ingested"] == 2
        assert result["kind"] == "power"
        assert result["captured_at"] == "2026-01-01"
        assert result["scan_id"] > 0

    def test_skips_empty_names(self):
        result = ingest_scan("power", [
            {"name": "", "power": 100},
            {"name": "   ", "power": 200},
            {"name": "Valid", "power": 300},
        ], captured_at="2026-01-01")
        assert result["ingested"] == 1

    def test_upserts_player_and_snapshot(self):
        ingest_scan("power", [
            {"name": "Charlie", "governor_id": "G001", "power": 10_000_000},
        ], captured_at="2026-02-01")
        conn = get_conn()
        player = conn.execute("SELECT * FROM players WHERE name='Charlie'").fetchone()
        assert player is not None
        assert player["governor_id"] == "G001"

        snap = conn.execute(
            "SELECT * FROM snapshots WHERE player_id=? AND captured_at='2026-02-01'",
            (player["id"],)
        ).fetchone()
        assert snap["power"] == 10_000_000

    def test_coalesces_multiple_scans_same_day(self):
        ingest_scan("power", [
            {"name": "Delta", "power": 5_000_000},
        ], captured_at="2026-03-01")
        ingest_scan("killpoints", [
            {"name": "Delta", "kill_points": 1_000_000},
        ], captured_at="2026-03-01")

        conn = get_conn()
        pid = conn.execute("SELECT id FROM players WHERE name='Delta'").fetchone()["id"]
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE player_id=? AND captured_at='2026-03-01'",
            (pid,)
        ).fetchone()
        assert snap["power"] == 5_000_000
        assert snap["kill_points"] == 1_000_000

    def test_scan_record_created(self):
        result = ingest_scan("dead", [
            {"name": "Echo", "deads": 500},
        ], captured_at="2026-04-01", source="adb")
        conn = get_conn()
        scan = conn.execute("SELECT * FROM scans WHERE id=?", (result["scan_id"],)).fetchone()
        assert scan["kind"] == "dead"
        assert scan["source"] == "adb"
        assert scan["captured_at"] == "2026-04-01"

    def test_empty_rows_list(self):
        result = ingest_scan("power", [], captured_at="2026-05-01")
        assert result["ingested"] == 0


class TestIngestRallies:
    def test_basic_rally_ingestion(self):
        result = ingest_rallies([
            {"leader_name": "Foxtrot", "target_label": "Lvl 5 Fort",
             "troops": 100_000, "status": "win"},
        ], captured_at="2026-01-01")
        assert result["logged"] == 1
        assert result["seen"] == 1

    def test_skips_empty_leader_names(self):
        result = ingest_rallies([
            {"leader_name": "", "target_label": "Fort"},
            {"leader_name": "   ", "target_label": "Fort"},
            {"leader_name": "Golf", "target_label": "Fort"},
        ], captured_at="2026-01-02")
        assert result["logged"] == 1

    def test_deduplication_same_day(self):
        rows = [{"leader_name": "Hotel", "target_label": "Flag", "status": "win"}]
        r1 = ingest_rallies(rows, captured_at="2026-01-03")
        r2 = ingest_rallies(rows, captured_at="2026-01-03")
        assert r1["logged"] == 1
        assert r2["logged"] == 0  # duplicate skipped

    def test_different_days_not_deduplicated(self):
        rows = [{"leader_name": "India", "target_label": "Barb"}]
        r1 = ingest_rallies(rows, captured_at="2026-01-04")
        r2 = ingest_rallies(rows, captured_at="2026-01-05")
        assert r1["logged"] == 1
        assert r2["logged"] == 1

    def test_links_to_existing_player(self):
        # Create the player first via a scan.
        ingest_scan("power", [{"name": "Juliet", "power": 1_000_000}],
                    captured_at="2026-01-06")
        ingest_rallies([
            {"leader_name": "Juliet", "target_label": "Fort"},
        ], captured_at="2026-01-06")
        conn = get_conn()
        rally = conn.execute(
            "SELECT * FROM rallies WHERE leader_name='Juliet'"
        ).fetchone()
        assert rally["leader_id"] is not None


class TestRecordMapPosition:
    def test_records_position(self):
        # Create a player first.
        ingest_scan("power", [{"name": "Kilo", "power": 1}], captured_at="2026-01-07")
        conn = get_conn()
        pid = conn.execute("SELECT id FROM players WHERE name='Kilo'").fetchone()["id"]

        record_map_position(pid, "Kilo", 1685, 100, 200, "mock")
        pos = conn.execute(
            "SELECT * FROM map_positions WHERE player_id=?", (pid,)
        ).fetchone()
        assert pos["x"] == 100
        assert pos["y"] == 200
        assert pos["kingdom"] == 1685
        assert pos["source"] == "mock"
