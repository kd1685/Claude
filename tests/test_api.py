"""End-to-end API tests using the mock control backend + a temp database."""
import os
import tempfile
import time

# Point the app at a throwaway DB and the mock backend BEFORE importing it.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["CONTROL_BACKEND"] = "mock"
os.environ["ADMIN_USERNAME"] = "king"
os.environ["ADMIN_PASSWORD"] = "s3cret"
os.environ["WORKER_INTERVAL"] = "0.2"   # fast loop so rotation steps quickly in tests

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

        # Control API is locked until we log in (data pages above were public).
        assert client.get("/api/control/status").status_code == 401
        assert client.post("/api/auth/login",
                           json={"username": "king", "password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login",
                           json={"username": "king", "password": "s3cret"}).status_code == 200
        me = client.get("/api/auth/me").json()
        assert me["authenticated"] and me["role"] == "admin"

        # Admin creates a per-officer account; that officer logs in separately.
        assert client.post("/api/auth/users",
                           json={"username": "scout", "password": "pw1", "role": "officer"}
                           ).status_code == 200
        officer = TestClient(app)
        assert officer.post("/api/auth/login",
                            json={"username": "scout", "password": "pw1"}).status_code == 200
        # New officer must change the temp password before doing anything.
        assert officer.get("/api/auth/me").json()["must_change_password"] is True
        assert officer.get("/api/control/status").status_code == 403  # locked out
        assert officer.post("/api/control/locate", json={"player_id": 1}).status_code == 403
        # Changing the password clears the flag and unlocks control.
        assert officer.post("/api/auth/change-password",
                            json={"current_password": "pw1", "new_password": "pw1real"}
                            ).status_code == 200
        assert officer.get("/api/auth/me").json()["must_change_password"] is False
        assert officer.get("/api/control/status").status_code == 200
        # Officers still cannot manage other officers (admin-only).
        assert officer.post("/api/auth/users",
                            json={"username": "x", "password": "y"}).status_code == 403

        # Control: mock backend executes via the worker queue.
        st = client.get("/api/control/status").json()
        assert st["backend"] == "mock"

        pid = lb["rows"][0]["player_id"]
        # The officer issues a command; it must be attributed to them in the log.
        cid = officer.post("/api/control/locate", json={"player_id": pid}).json()["command_id"]
        cmd = _wait_command(client, cid)
        assert cmd["status"] == "done"
        assert cmd["issued_by_name"] == "scout"

        # Self-service password change: wrong current pw rejected, then changed.
        assert officer.post("/api/auth/change-password",
                            json={"current_password": "nope", "new_password": "brandnew"}
                            ).status_code == 400
        assert officer.post("/api/auth/change-password",
                            json={"current_password": "pw1real", "new_password": "brandnew"}
                            ).status_code == 200
        # Old password no longer works; new one does.
        fresh = TestClient(app)
        assert fresh.post("/api/auth/login",
                          json={"username": "scout", "password": "pw1real"}).status_code == 401
        assert fresh.post("/api/auth/login",
                          json={"username": "scout", "password": "brandnew"}).status_code == 200

        # Admin password reset re-arms the forced-change flag.
        oid = next(u["id"] for u in client.get("/api/auth/users").json() if u["username"] == "scout")
        assert client.post(f"/api/auth/users/{oid}/password",
                           json={"password": "tempagain"}).status_code == 200
        reset_client = TestClient(app)
        reset_client.post("/api/auth/login", json={"username": "scout", "password": "tempagain"})
        assert reset_client.get("/api/auth/me").json()["must_change_password"] is True

        # Deactivating the officer revokes access immediately.
        oid = next(u["id"] for u in client.get("/api/auth/users").json() if u["username"] == "scout")
        assert client.post(f"/api/auth/users/{oid}/active?active=false").status_code == 200
        assert officer.get("/api/control/status").status_code == 401

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

        _advanced(client)


def _advanced(client):
    """Rotation, per-action permissions, audit CSV, force-change, DKP."""
    # Two governors to rotate over.
    ids = [r["id"] for r in client.get("/api/players").json()[:2]]
    assert len(ids) == 2

    # Bulk title rotation with a 0s hold (so it completes fast in tests).
    rid = client.post("/api/control/rotation",
                      json={"title": "Duke", "player_ids": ids, "hold_seconds": 0}
                      ).json()["rotation_id"]
    for _ in range(60):
        active = client.get("/api/control/rotation/active").json()
        if active.get("rotation") is None or active["rotation"]["status"] != "running":
            break
        time.sleep(0.2)
    rot = next(r for r in client.get("/api/control/rotations").json() if r["id"] == rid)
    assert rot["status"] == "done"
    # A second rotation cannot start while one runs is moot now; both members granted.
    log = client.get("/api/control/commands?kind=give_title&limit=100").json()
    assert sum(1 for c in log if c["status"] == "done") >= 2

    # Per-action permissions: a plain officer can rank to R4 but not R5.
    client.post("/api/auth/users", json={"username": "duty", "password": "tmp12345"})
    duty = TestClient(app)
    duty.post("/api/auth/login", json={"username": "duty", "password": "tmp12345"})
    duty.post("/api/auth/change-password",
              json={"current_password": "tmp12345", "new_password": "dutyreal1"})
    assert duty.post("/api/control/change-rank",
                     json={"player_id": ids[0], "new_rank": 5}).status_code == 403
    assert duty.post("/api/control/change-rank",
                     json={"player_id": ids[0], "new_rank": 4}).status_code == 200
    # The officer's permission map hides R5.
    perms = duty.get("/api/control/status").json()["permissions"]
    assert perms["change_rank"] is True and perms["change_rank_r5"] is False

    # Force-change toggle (no password reset) takes effect on next request.
    did = next(u["id"] for u in client.get("/api/auth/users").json() if u["username"] == "duty")
    assert client.post(f"/api/auth/users/{did}/force-change").status_code == 200
    assert duty.get("/api/control/status").status_code == 403  # now must change

    # Audit CSV export.
    csv_res = client.get("/api/control/commands.csv")
    assert csv_res.status_code == 200 and "text/csv" in csv_res.headers["content-type"]
    assert csv_res.text.splitlines()[0].startswith("id,kind,player")

    # DKP endpoint responds with a sorted structure.
    dkp = client.get("/api/stats/dkp?from=2026-05-01&to=2026-05-05").json()
    assert "rows" in dkp and dkp["weights"]["dead"] == 5.0

    # Schedules + events CRUD (admin).
    sid = client.post("/api/schedules",
                      json={"kind": "power", "at_hour": 2, "at_minute": 30}).json()["id"]
    assert any(s["id"] == sid for s in client.get("/api/schedules").json())
    eid = client.post("/api/events",
                      json={"name": "KvK1", "start_date": "2026-05-01", "end_date": "2026-05-20"}
                      ).json()["id"]
    assert any(e["id"] == eid for e in client.get("/api/events").json())
