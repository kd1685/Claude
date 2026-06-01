"""Mock adapter: simulates a RoK client so the whole app runs with no device.

It produces stable, plausible data (seeded from the governor name) so the
website, queue worker and APIs can be exercised end-to-end before you point the
ADB backend at a live client.
"""
from __future__ import annotations

import hashlib
import random

from .adapter import AccountAdapter, ActionResult

_KIND_FIELD = {"power": "power", "killpoints": "kill_points", "dead": "deads"}

_NAMES = [
    "DragonLord", "NightFury", "KingSlayer", "IronWolf", "ShadowReign",
    "ValkyrieX", "StormBlade", "Ragnarok", "PhoenixAsh", "TitanFall",
    "CrimsonAce", "FrostByte", "WarHymn", "ObsidianK", "Leviathan",
    "GhostRecon", "ThunderGod", "VortexY", "BloodMoon", "Spartacus",
]


def _rng(seed: str) -> random.Random:
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return random.Random(h)


class MockAdapter(AccountAdapter):
    name = "mock"

    def connect(self) -> ActionResult:
        return ActionResult(True, "mock backend ready (no device)")

    def status(self) -> dict:
        return {"backend": "mock", "connected": True, "device": None}

    def give_title(self, *, name, governor_id, x, y, title) -> ActionResult:
        return ActionResult(
            True,
            f"[mock] granted title '{title}' to {name}"
            + (f" at ({x},{y})" if x is not None else ""),
            {"title": title},
        )

    def change_rank(self, *, name, governor_id, new_rank) -> ActionResult:
        return ActionResult(True, f"[mock] set {name} to R{new_rank}",
                            {"new_rank": new_rank})

    def locate(self, *, name, governor_id) -> ActionResult:
        r = _rng(name + (governor_id or ""))
        x, y = r.randint(0, 1023), r.randint(0, 1023)
        return ActionResult(True, f"[mock] found {name}",
                            {"kingdom": 1685, "x": x, "y": y})

    def scan_rankings(self, *, kind, pages) -> ActionResult:
        field = _KIND_FIELD.get(kind, "power")
        rows = []
        for i, name in enumerate(_NAMES[: min(len(_NAMES), pages * 5)]):
            r = _rng(name + kind)
            base = {
                "power": r.randint(8_000_000, 120_000_000),
                "kill_points": r.randint(5_000_000, 900_000_000),
                "deads": r.randint(0, 3_000_000),
            }
            rows.append({
                "name": name,
                "governor_id": str(100000 + i),
                field: base.get(field, base["power"]),
            })
        rows.sort(key=lambda d: d.get(field, 0), reverse=True)
        return ActionResult(True, f"[mock] scanned {len(rows)} rows ({kind})",
                            {"rows": rows})
