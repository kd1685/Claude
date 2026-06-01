"""Populate the database with realistic demo data for kingdom 1685.

Run:  python -m scripts.seed
Generates ~24 governors with 30 days of power/KP/dead history, rallies and
map positions so the website has something to show before a real scan runs.
"""
from __future__ import annotations

import datetime as dt
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_conn, init_db, upsert_player, upsert_snapshot  # noqa: E402
from app.services import today  # noqa: E402

R = random.Random(1685)

GOVERNORS = [
    ("DragonLord", "KOXV", 5), ("NightFury", "KOXV", 4), ("KingSlayer", "KOXV", 4),
    ("IronWolf", "KOXV", 3), ("ShadowReign", "KOXV", 3), ("ValkyrieX", "KOXV", 3),
    ("StormBlade", "KOXV", 2), ("Ragnarok", "KOXV", 2), ("PhoenixAsh", "KOXV", 2),
    ("TitanFall", "KOXV", 1), ("CrimsonAce", "KOXV", 1), ("FrostByte", "KOXV", 1),
    ("WarHymn", "DARK", 5), ("ObsidianK", "DARK", 4), ("Leviathan", "DARK", 3),
    ("GhostRecon", "DARK", 3), ("ThunderGod", "DARK", 2), ("VortexY", "DARK", 2),
    ("BloodMoon", "DARK", 1), ("Spartacus", "DARK", 1), ("NovaStrike", "VKNG", 4),
    ("EmberQueen", "VKNG", 3), ("Direwolf", "VKNG", 2), ("Onyxia", "VKNG", 1),
]

TARGETS = [("barbarian", "Lvl 30 Barbarian"), ("fortress", "Barbarian Fort"),
           ("flag", "Alliance Flag"), ("player", "Enemy City")]


def seed(days: int = 30) -> None:
    init_db()
    conn = get_conn()
    end = dt.date.fromisoformat(today())
    start = end - dt.timedelta(days=days - 1)

    player_ids = {}
    base_stats = {}
    for name, alliance, rank in GOVERNORS:
        pid = upsert_player(name=name, alliance=alliance, rank=rank,
                            governor_id=str(1685_000 + len(player_ids)))
        player_ids[name] = pid
        base_stats[name] = {
            "power": R.randint(15_000_000, 95_000_000),
            "kp": R.randint(20_000_000, 600_000_000),
            "deads": R.randint(0, 200_000),
        }

    d = start
    while d <= end:
        ds = d.isoformat()
        for name, _, _ in GOVERNORS:
            b = base_stats[name]
            # daily growth
            b["power"] += R.randint(-200_000, 900_000)
            b["kp"] += R.randint(0, 12_000_000)
            b["deads"] += R.randint(0, 40_000)
            kp = b["kp"]
            upsert_snapshot(player_ids[name], ds, {
                "power": b["power"],
                "kill_points": kp,
                "t4_kills": int(kp * 0.4 / 20),
                "t5_kills": int(kp * 0.5 / 30),
                "deads": b["deads"],
                "rss_gathered": R.randint(0, 5_000_000),
                "rss_assist": R.randint(0, 200_000),
                "helps": R.randint(0, 400),
            })
        # a few rallies per day
        for _ in range(R.randint(2, 6)):
            name = R.choice(GOVERNORS)[0]
            tt, tl = R.choice(TARGETS)
            conn.execute(
                "INSERT INTO rallies (captured_at, leader_id, leader_name, target_type,"
                " target_label, x, y, troops, status, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ds, player_ids[name], name, tt, tl, R.randint(0, 1023),
                 R.randint(0, 1023), R.randint(50_000, 600_000),
                 R.choice(["win", "win", "win", "loss"]), "seed"),
            )
        d += dt.timedelta(days=1)

    # one set of current map positions
    for name, _, _ in GOVERNORS:
        conn.execute(
            "INSERT INTO map_positions (player_id, name, kingdom, x, y, captured_at, source)"
            " VALUES (?,?,?,?,?,?,?)",
            (player_ids[name], name, 1685, R.randint(0, 1023), R.randint(0, 1023),
             end.isoformat(), "seed"),
        )
    conn.commit()
    print(f"Seeded {len(GOVERNORS)} governors x {days} days "
          f"({start} .. {end}) into the database.")


if __name__ == "__main__":
    seed()
