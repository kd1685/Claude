"""Abstract account adapter.

An adapter knows how to drive *one* Rise of Kingdoms client (the "control
account") so the app can grant titles, change alliance ranks, locate governors
on the map and scan the rankings. Concrete backends:

  * MockAdapter  - no device; deterministic synthetic data (default).
  * AdbAdapter   - a real client on an Android device/emulator over ADB.

The high-level :mod:`app.control.actions` module only ever talks to this
interface, so the rest of the app is identical whether you are testing locally
or running headless on a VPS against a live game.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class ActionResult:
    ok: bool
    detail: str = ""
    data: dict = field(default_factory=dict)


class AccountAdapter(abc.ABC):
    """Capabilities a control backend must provide."""

    name: str = "base"

    @abc.abstractmethod
    def connect(self) -> ActionResult:
        """Establish/verify the connection to the client. Idempotent."""

    @abc.abstractmethod
    def status(self) -> dict:
        """Return a small dict describing backend health for the UI."""

    @abc.abstractmethod
    def give_title(self, *, name: str, governor_id: str | None,
                   x: int | None, y: int | None, title: str) -> ActionResult:
        """Grant an in-game title to a governor (located by coords or name)."""

    @abc.abstractmethod
    def change_rank(self, *, name: str, governor_id: str | None,
                    new_rank: int) -> ActionResult:
        """Change an alliance member's rank (R1..R5)."""

    @abc.abstractmethod
    def locate(self, *, name: str, governor_id: str | None) -> ActionResult:
        """Find a governor on the map. data -> {kingdom, x, y}."""

    @abc.abstractmethod
    def scan_rankings(self, *, kind: str, pages: int) -> ActionResult:
        """Read the rankings list. data -> {'rows': [ {name, value, ...} ]}."""

    @abc.abstractmethod
    def scan_rallies(self, *, pages: int) -> ActionResult:
        """Read the alliance war/rally reports. data -> {'rows': [ {leader_name,
        target_label, status, ...} ]}."""

    @abc.abstractmethod
    def scan_profiles(self, *, count: int) -> ActionResult:
        """Deep scan the top `count` governors: open each one's profile + More
        Info to read the full stat block including DEAD troops. data ->
        {'rows': [ {name, power, kill_points, deads, rss_assist, ...} ]}."""
