#!/usr/bin/env python3
"""Kingdom 1685 PC agent.

Runs on your computer next to an Android emulator (LDPlayer) that has Rise of
Kingdoms installed and logged in. It polls your live site for device tasks
(scan / give title / change rank / locate), performs them in the emulator over
ADB — reusing the exact same control code as the server — and posts the results
back. Your website stays on the VPS; only the game-touching happens here.

Setup + run:  see agent/README.md   (or just double-click agent/run-agent.bat)
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(ROOT / "agent" / "agent.env")

SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8000").rstrip("/")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "2"))
AGENT_VERSION = "2026.06.05-rank-target"   # bump on each code change

# Configure the local ADB adapter (via env) before importing the app config.
os.environ.setdefault("CONTROL_BACKEND", "adb")
os.environ.setdefault("ADB_SERIAL", "127.0.0.1:5555")
os.environ.setdefault("ADB_CONNECT", os.environ.get("ADB_SERIAL", "127.0.0.1:5555"))

import requests  # noqa: E402
from app.control.adapter import ActionResult  # noqa: E402
from app.control.adb_adapter import AdbAdapter  # noqa: E402

adapter = AdbAdapter()


def _make_stop_checker(task_id, headers):
    """Returns a throttled callable the scanner uses to ask the server whether
    this scan has been told to stop (checks at most every ~2s)."""
    state = {"t": 0.0, "v": False}

    def check() -> bool:
        now = time.time()
        if state["v"] or now - state["t"] < 2.0:
            return state["v"]
        state["t"] = now
        try:
            r = requests.get(f"{SERVER_URL}/api/agent/task/{task_id}",
                             headers=headers, timeout=10)
            if r.ok:
                state["v"] = bool(r.json().get("cancel_requested"))
        except requests.RequestException:
            pass
        return state["v"]

    return check


def dispatch(kind: str, p: dict) -> ActionResult:
    if kind == "give_title":
        return adapter.give_title(name=p["name"], governor_id=p.get("governor_id"),
                                  x=p.get("x"), y=p.get("y"), title=p["title"])
    if kind == "change_rank":
        return adapter.change_rank(name=p["name"], governor_id=p.get("governor_id"),
                                   new_rank=int(p["new_rank"]))
    if kind == "locate":
        return adapter.locate(name=p["name"], governor_id=p.get("governor_id"))
    if kind == "scan_rankings":
        return adapter.scan_rankings(kind=p.get("kind", "power"),
                                     pages=int(p.get("pages", 4)))
    if kind == "scan_profiles":
        return adapter.scan_profiles(count=int(p.get("count", p.get("pages", 100))))
    if kind == "scan_rallies":
        return adapter.scan_rallies(pages=int(p.get("pages", 5)))
    return ActionResult(False, f"unknown task kind: {kind}")


def main() -> int:
    if not AGENT_TOKEN:
        print("ERROR: set AGENT_TOKEN in agent/agent.env (must match the server).")
        return 1
    print(f"Kingdom 1685 agent {AGENT_VERSION} → {SERVER_URL}")
    conn = adapter.connect()
    print(f"Emulator: {conn.detail}")
    if not conn.ok:
        print("  (the agent will keep trying; make sure LDPlayer is running and "
              "ADB_SERIAL is correct)")

    headers = {"X-Agent-Token": AGENT_TOKEN}
    info = f"{adapter.name}:{os.environ.get('ADB_SERIAL')}"
    print("Waiting for tasks… (leave this window open)")
    while True:
        try:
            r = requests.post(f"{SERVER_URL}/api/agent/poll", headers=headers,
                              params={"info": info}, timeout=30)
            if r.status_code == 401:
                print("Auth failed — AGENT_TOKEN does not match the server."); time.sleep(5); continue
            if r.status_code == 503:
                print("Server says remote agent is not enabled (set AGENT_TOKEN there)."); time.sleep(10); continue
            r.raise_for_status()
            task = r.json().get("task")
            if not task:
                time.sleep(POLL_INTERVAL); continue

            print(f"▶ task #{task['id']} {task['kind']} {task['params']}")
            adapter.should_stop = _make_stop_checker(task["id"], headers)
            try:
                res = dispatch(task["kind"], task["params"])
            finally:
                adapter.should_stop = None
            requests.post(f"{SERVER_URL}/api/agent/complete", headers=headers, json={
                "task_id": task["id"], "ok": res.ok, "detail": res.detail,
                "data": res.data, "error": None if res.ok else res.detail,
            }, timeout=60)
            print(f"  {'✓' if res.ok else '✗'} {res.detail}")
        except requests.RequestException as exc:
            print(f"network error: {exc}"); time.sleep(5)
        except KeyboardInterrupt:
            print("\nstopped."); return 0
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}"); time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
