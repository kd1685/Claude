"""End-to-end API tests using the mock control backend + a temp database."""
import os
import tempfile
import time

# Point the app at a throwaway DB and the mock backend BEFORE importing it.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["CONTROL_BACKEND"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _wait_command(client, cid, timeout=10):
    for _ in range(int(timeout * 5)):
        rows = client.get("/api/control/commands").json()
        cmd = next((c for c in rows if c["id"] == cid), None)
        if cmd and cmd["status"] in ("done", "failed"):
            return cmd
        time.sleep(0.2)
    raise AssertionError(f"command {cid} did not finish")


def test_full_flow():
    with TestClient(app) as client:  # lifespan starts the worker
        assert client.get("/api/health").json()["ok"] is True

        # Ingest a manual power scan.
        scan = client.post("/api/scans", json={
            "kind": "power", "captured_at": "2026-05-01", "source": "manual",
            "rows": [
                {"name": "Alpha", "power": 50_000_000, "kill_points": 100_000_000, "deads": 10_000},
                {"name": "Bravo", "power": 30_000_000, "kill_points": 60_000_000, "deads": 5_000},
            ],
        })
        assert scan.status_code == 200 and scan.json()["ingested"] == 2

        # Leaderboard reflects it.
        lb = client.get("/api/stats/leaderboard?metric=power&date=2026-05-01").json()
        assert lb["rows"][0]["name"] == "Alpha"
        assert lb["rows"][0]["value"] == 50_000_000

        # Gains between two dates.
        client.post("/api/scans", json={
            "kind": "power", "captured_at": "2026-05-05", "source": "manual",
            "rows": [{"name": "Alpha", "power": 55_000_000}],
        })
        lb2 = client.get("/api/stats/leaderboard?metric=power&date=2026-05-05&from=2026-05-01").json()
        alpha = next(r for r in lb2["rows"] if r["name"] == "Alpha")
        assert alpha["gain"] == 5_000_000

        # Kingdom totals + summary.
        assert client.get("/api/stats/kingdom-totals?metric=power&from=2026-05-01&to=2026-05-05").json()["series"]
        assert client.get("/api/stats/summary?date=2026-05-05").json()["governors"] >= 1

        # Control: mock backend executes via the worker queue.
        st = client.get("/api/control/status").json()
        assert st["backend"] == "mock"

        pid = lb["rows"][0]["player_id"]
        cid = client.post("/api/control/locate", json={"player_id": pid}).json()["command_id"]
        cmd = _wait_command(client, cid)
        assert cmd["status"] == "done"

        # Locate recorded a map position.
        positions = client.get("/api/map/positions").json()["positions"]
        assert any(p["player_id"] == pid for p in positions)

        # Title + rank changes.
        cid = client.post("/api/control/give-title", json={"player_id": pid, "title": "Justice"}).json()["command_id"]
        assert _wait_command(client, cid)["status"] == "done"

        cid = client.post("/api/control/change-rank", json={"player_id": pid, "new_rank": 4}).json()["command_id"]
        assert _wait_command(client, cid)["status"] == "done"
        assert client.get(f"/api/players/{pid}").json()["player"]["rank"] == 4

        # Scan command ingests rows from the mock adapter.
        cid = client.post("/api/control/scan", json={"kind": "killpoints", "pages": 2}).json()["command_id"]
        assert _wait_command(client, cid)["status"] == "done"
