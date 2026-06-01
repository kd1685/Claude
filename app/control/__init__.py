"""Account-control subsystem: adapters, OCR scanner, high-level actions."""
from __future__ import annotations

from ..config import config
from .adapter import AccountAdapter
from .mock_adapter import MockAdapter

_adapter: AccountAdapter | None = None


def get_adapter() -> AccountAdapter:
    """Return the configured singleton adapter (mock or adb)."""
    global _adapter
    if _adapter is not None:
        return _adapter
    if config.CONTROL_BACKEND == "adb":
        from .adb_adapter import AdbAdapter  # lazy: avoids importing heavy deps
        _adapter = AdbAdapter()
    else:
        _adapter = MockAdapter()
    return _adapter
