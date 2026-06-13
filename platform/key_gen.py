"""key_gen.py — CLI tool to manage Ascent Terminal API keys.

Usage examples:
    python key_gen.py --tier scout  --label "Trial user"
    python key_gen.py --tier operator --label "Alice"
    python key_gen.py --revoke AT-abcdef1234567890
    python key_gen.py --list
"""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

KEYS_FILE = Path("keys.json")


def _load() -> dict:
    try:
        return json.loads(KEYS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(keys: dict) -> None:
    KEYS_FILE.write_text(json.dumps(keys, indent=2))


def generate(tier: str, label: str) -> str:
    keys = _load()
    key = "AT-" + secrets.token_hex(16)
    keys[key] = {"tier": tier, "label": label, "active": True}
    _save(keys)
    return key


def revoke(key: str) -> bool:
    keys = _load()
    if key not in keys:
        return False
    keys[key]["active"] = False
    _save(keys)
    return True


def list_keys() -> None:
    keys = _load()
    if not keys:
        print("No keys found.")
        return
    print(f"{'Key':<40} {'Tier':<12} {'Label':<20} Active")
    print("-" * 80)
    for k, v in keys.items():
        print(f"{k:<40} {v.get('tier','?'):<12} {v.get('label',''):<20} {v.get('active', True)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ascent Terminal key manager")
    sub = parser.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", aliases=["--tier"])
    gen.add_argument("--tier", required=True, choices=["scout", "operator", "architect"])
    gen.add_argument("--label", default="")

    rev = sub.add_parser("revoke", aliases=["--revoke"])
    rev.add_argument("key")

    sub.add_parser("list", aliases=["--list"])

    # Simple positional-style parsing for the common case
    args, _ = parser.parse_known_args()

    import sys
    argv = sys.argv[1:]
    if "--list" in argv:
        list_keys()
    elif "--revoke" in argv:
        idx = argv.index("--revoke")
        key = argv[idx + 1]
        ok = revoke(key)
        print(f"Revoked {key}" if ok else f"Key not found: {key}")
    elif "--tier" in argv:
        idx = argv.index("--tier")
        tier = argv[idx + 1]
        label = ""
        if "--label" in argv:
            lidx = argv.index("--label")
            label = argv[lidx + 1]
        key = generate(tier, label)
        print(f"Generated key ({tier}): {key}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
