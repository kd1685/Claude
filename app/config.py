"""Runtime configuration, loaded from environment (and an optional .env file)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal .env loader so we have no hard dependency on python-dotenv."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _get(key: str, default: str) -> str:
    return os.environ.get(key, default)


class Config:
    HOST: str = _get("HOST", "0.0.0.0")
    PORT: int = int(_get("PORT", "8000"))

    DB_PATH: Path = (ROOT / _get("DB_PATH", "data/rok1685.db")).resolve()

    KINGDOM_ID: str = _get("KINGDOM_ID", "1685")

    CONTROL_BACKEND: str = _get("CONTROL_BACKEND", "mock").lower()
    # mock = simulated | adb = local device | remote = a PC agent drives the game
    ADB_PATH: str = _get("ADB_PATH", "adb")
    ADB_SERIAL: str = _get("ADB_SERIAL", "")
    ADB_CONNECT: str = _get("ADB_CONNECT", "")
    UI_PROFILE: Path = (ROOT / _get("UI_PROFILE", "app/profiles/rok_720p.json")).resolve()
    TESSERACT_CMD: str = _get("TESSERACT_CMD", "tesseract")
    # The controlling account's own in-game name — the deep scan skips this row
    # in the rankings (its own profile has a different layout that breaks the loop).
    OWN_GOVERNOR: str = _get("OWN_GOVERNOR", "")

    WORKER_INTERVAL: float = float(_get("WORKER_INTERVAL", "3"))

    # Shared secret the PC agent uses to authenticate (CONTROL_BACKEND=remote).
    AGENT_TOKEN: str = _get("AGENT_TOKEN", "")
    # How long the server waits for the agent to finish one device action (sec).
    AGENT_TASK_TIMEOUT: float = float(_get("AGENT_TASK_TIMEOUT", "120"))
    AGENT_SCAN_TIMEOUT: float = float(_get("AGENT_SCAN_TIMEOUT", "900"))

    # ---- Control-page auth (data pages stay public) ----
    # First-run bootstrap admin officer. Created only if no users exist yet.
    ADMIN_USERNAME: str = _get("ADMIN_USERNAME", "admin")
    # ADMIN_PASSWORD falls back to the legacy CONTROL_PASSWORD for continuity.
    ADMIN_PASSWORD: str = _get("ADMIN_PASSWORD", "") or _get("CONTROL_PASSWORD", "changeme1685")
    # Secret for signing session cookies. Set a stable value in prod so sessions
    # survive restarts; otherwise a random per-process key is used.
    CONTROL_SECRET: str = _get("CONTROL_SECRET", "") or os.urandom(32).hex()
    COOKIE_SECURE: bool = _get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    # SameSite for the session cookie. Use "none" (with COOKIE_SECURE=true) when
    # the website is on a different origin than the backend (e.g. GitHub Pages).
    COOKIE_SAMESITE: str = _get("COOKIE_SAMESITE", "lax").lower()
    SESSION_TTL: int = int(_get("SESSION_TTL", str(60 * 60 * 24 * 7)))  # 7 days

    # Comma-separated origins allowed to call the API from a browser (CORS).
    # e.g. "https://kd1685.github.io". Empty = same-origin only.
    CORS_ORIGINS: list[str] = [o.strip() for o in _get("CORS_ORIGINS", "").split(",") if o.strip()]

    CAPTURE_DIR: Path = (ROOT / "captures").resolve()

    @property
    def admin_password_is_default(self) -> bool:
        return self.ADMIN_PASSWORD == "changeme1685"


config = Config()
config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
config.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
