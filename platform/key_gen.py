"""
key_gen.py — subscriber access-key manager for Ascent Terminal (v2, hashed).

SECURITY MODEL
  * keys.json stores SHA-256 HASHES, never plaintext. A leaked keys.json
    reveals nothing usable. The plaintext key is printed exactly once at
    generation — if the subscriber loses it, revoke and issue a new one.
  * The server (auth.py) hot-reloads keys.json: new keys work immediately,
    revocations bite immediately, expiry is enforced per request.
    NO RESTART NEEDED — the old ACCESS_KEYS-env workflow is fallback only.
  * Legacy plaintext keys.json files are migrated to hashes automatically
    the first time this tool touches them (existing keys keep working).

TIERS (what each unlocks in the terminal)
  observer   — live signals, charts, indicator panel, positioning, alerts feed
  operator   — + Strategy Lab backtest, execution bridge, alert clearing
  architect  — + bots (trend / scalper)

USAGE
  python key_gen.py new --tier observer --note "patron @alice"
  python key_gen.py new --tier architect --days 31 --note "whop order 123"
  python key_gen.py list
  python key_gen.py revoke --key XXXXX-XXXXX-XXXXX-XXXXX   (or a hash prefix)
"""

import os
import json
import argparse
import hashlib
import secrets
import string
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ASCENT_KEYS", os.path.join(HERE, "data", "keys.json"))


def _migrate_legacy_keyfile(new_path: str):
    """One-time move of keys.json from the app root into data/ (directory
    mounts survive atomic renames; single-file Docker mounts do not — the
    container otherwise freezes on a stale inode after every key write)."""
    legacy = os.path.join(HERE, "keys.json")
    try:
        if os.path.exists(legacy) and not os.path.exists(new_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            try:
                os.replace(legacy, new_path)
            except OSError:                       # cross-device: copy instead
                import shutil
                shutil.copy2(legacy, new_path)
                os.rename(legacy, legacy + ".migrated")
    except Exception:
        pass                                      # never block startup on this

_migrate_legacy_keyfile(DB)

TIERS = ("observer", "operator", "architect")


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8", "ignore")).hexdigest()


def _is_hash(ident: str) -> bool:
    return len(ident) == 64 and all(c in "0123456789abcdef" for c in ident.lower())


def _load():
    """Load keys.json; transparently migrate legacy plaintext files to v2."""
    if not os.path.exists(DB):
        return {}
    with open(DB) as f:
        raw = json.load(f)
    entries = raw.get("keys", raw) if isinstance(raw, dict) else {}
    migrated, out = 0, {}
    for ident, rec in entries.items():
        if not isinstance(rec, dict):
            continue
        if _is_hash(ident):
            out[ident.lower()] = rec
        else:                                     # legacy plaintext key
            out[_digest(ident)] = rec
            migrated += 1
    if migrated:
        _save(out)
        print(f"  [migrated {migrated} legacy plaintext key(s) to hashed storage — "
              f"existing keys keep working]")
    return out


def _save(db):
    tmp = DB + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"version": 2, "keys": db}, f, indent=2)
    os.replace(tmp, DB)                           # atomic — server never sees a half-write


def new_key():
    a = string.ascii_uppercase + string.digits
    raw = "".join(secrets.choice(a) for _ in range(20))
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new")
    p.add_argument("--tier", default="observer", choices=TIERS)
    p.add_argument("--note", default="")
    p.add_argument("--days", type=int, default=0, help="optional expiry in days (0 = none)")

    p = sub.add_parser("revoke")
    p.add_argument("--key", required=True, help="the full key, or a stored-hash prefix from `list`")

    p = sub.add_parser("addon", help="grant/adjust paid add-ons on a key")
    p.add_argument("--key", required=True, help="full key or stored-hash prefix")
    p.add_argument("--bots", type=int, default=0, help="extra bot instances (+/-)")
    p.add_argument("--ai", type=int, default=0, help="extra AI analyses/day (+/-)")

    sub.add_parser("list")

    a = ap.parse_args()
    db = _load()

    if a.cmd == "new":
        k = new_key()
        rec = {"tier": a.tier, "note": a.note, "active": True,
               "created": datetime.utcnow().isoformat()}
        if a.days > 0:
            rec["expires"] = (date.today() + timedelta(days=a.days)).isoformat()
        db[_digest(k)] = rec
        _save(db)
        print(f"\n  NEW KEY (shown ONCE — it is stored only as a hash):\n")
        print(f"      {k}\n")
        print(f"  tier={a.tier}  note='{a.note}'"
              + (f"  expires={rec.get('expires')}" if a.days else ""))
        print(f"  The server picks this up live from keys.json — no restart needed.\n")

    elif a.cmd == "revoke":
        supplied = a.key.strip()
        target = None
        h = _digest(supplied)                     # 1) treat input as a full key
        if h in db:
            target = h
        else:                                     # 2) treat input as a hash prefix
            pref = supplied.lower()
            matches = [k for k in db if k.startswith(pref)]
            if len(matches) == 1:
                target = matches[0]
            elif len(matches) > 1:
                print("Prefix matches multiple keys — use more characters."); return
        if target is None:
            print("Key not found."); return
        db[target]["active"] = False
        _save(db)
        print(f"Revoked {target[:12]}…  [{db[target].get('tier')}] "
              f"{db[target].get('note','')} — effective immediately (hot reload).")

    elif a.cmd == "addon":
        supplied = a.key.strip()
        target = _digest(supplied) if _digest(supplied) in db else None
        if target is None:
            matches = [k for k in db if k.startswith(supplied.lower())]
            if len(matches) == 1:
                target = matches[0]
        if target is None:
            print("Key not found."); return
        addons = db[target].setdefault("addons", {})
        addons["bots"] = max(0, int(addons.get("bots", 0)) + a.bots)
        addons["ai"] = max(0, int(addons.get("ai", 0)) + a.ai)
        _save(db)
        print(f"Add-ons on {target[:12]}…  bots+{addons['bots']}  ai+{addons['ai']}/day "
              f"— live immediately (hot reload).")

    elif a.cmd == "list":
        if not db:
            print("No keys yet."); return
        today = date.today().isoformat()
        for h, r in db.items():
            exp = r.get("expires")
            flag = ("REVOKED" if not r.get("active", True)
                    else "EXPIRED" if exp and exp < today else "active")
            print(f"  {h[:12]}…  [{r.get('tier','observer'):9}] {flag:8} "
                  f"exp={exp or '-':10}  {r.get('note','')}")


if __name__ == "__main__":
    main()
