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
    ADB_PATH: str = _get("ADB_PATH", "adb")
    ADB_SERIAL: str = _get("ADB_SERIAL", "")
    ADB_CONNECT: str = _get("ADB_CONNECT", "")
    UI_PROFILE: Path = (ROOT / _get("UI_PROFILE", "app/profiles/rok_720p.json")).resolve()
    TESSERACT_CMD: str = _get("TESSERACT_CMD", "tesseract")

    WORKER_INTERVAL: float = float(_get("WORKER_INTERVAL", "3"))

    # ---- Control-page auth (data pages stay public) ----
    CONTROL_PASSWORD: str = _get("CONTROL_PASSWORD", "changeme1685")
    # Secret for signing session cookies. Set a stable value in prod so sessions
    # survive restarts; otherwise a random per-process key is used.
    CONTROL_SECRET: str = _get("CONTROL_SECRET", "") or os.urandom(32).hex()
    COOKIE_SECURE: bool = _get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    SESSION_TTL: int = int(_get("SESSION_TTL", str(60 * 60 * 24 * 7)))  # 7 days

    CAPTURE_DIR: Path = (ROOT / "captures").resolve()

    @property
    def password_is_default(self) -> bool:
        return self.CONTROL_PASSWORD == "changeme1685"


config = Config()
config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
config.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
