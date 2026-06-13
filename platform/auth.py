"""
auth.py — hardened subscriber-key authentication for Ascent Terminal.

Security model
──────────────
* Keys are NEVER stored in plaintext. keys.json holds SHA-256 hashes only —
  a leaked keys.json reveals nothing usable. The plaintext key is shown to
  the owner exactly once, at generation (key_gen.py).
* Verification is timing-safe: the presented key is hashed and the digest is
  compared with hmac.compare_digest against stored digests. Hashing first
  means an attacker cannot probe stored secrets byte-by-byte via timing.
* Brute force is throttled: failed attempts are counted per client IP in a
  sliding window; over the limit the IP is locked out (HTTP 429) for a
  cool-down. Valid keys have 36^20 ≈ 1.3e31 entropy, so online guessing is
  hopeless even without the limiter — the limiter mainly stops log noise
  and oracle abuse of /api/check.
* keys.json hot-reloads on mtime change (checked at most once/second):
  issuing or revoking a key takes effect immediately — no server restart.
* Expiry is enforced per-request, not at env-generation time.
* ACCESS_KEYS env keys still work as a fallback (hashed at startup, never
  kept in plaintext in memory beyond startup) and map to the architect tier
  — only the machine owner can set env vars. Remove DEMO-KEY in production.

Tiers (hierarchical)
────────────────────
  observer  (1) — live signals, charts, indicator panel, macro, alerts feed
  operator  (2) — + Strategy Lab backtest, execution bridge, alert clearing
  architect (3) — + bots (trend / scalper control)
"""

import hashlib
import hmac
import json
import os
import threading
import time
from collections import deque

KEYS_PATH = os.environ.get(
    "ASCENT_KEYS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "keys.json"),
)


def _migrate_legacy_keyfile(new_path: str):
    """One-time move of keys.json from the app root into data/ (directory
    mounts survive atomic renames; single-file Docker mounts do not — the
    container otherwise freezes on a stale inode after every key write)."""
    legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys.json")
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


_migrate_legacy_keyfile(KEYS_PATH)


TIER_LEVEL = {"observer": 1, "operator": 2, "architect": 3}
DEFAULT_TIER = "observer"

# Brute-force limiter: per-IP failures in a sliding window.
FAIL_LIMIT = 10               # failed auths allowed…
FAIL_WINDOW = 300             # …per 5 minutes…
LOCKOUT = 900                 # …then locked out for 15 minutes
_MAX_TRACKED_IPS = 5000

_lock = threading.Lock()
_keys = {}                    # sha256 hex -> {tier, active, expires, note}
_env_hashes = {}              # sha256 hex -> tier (from ACCESS_KEYS env)
_mtime = None
_last_check = 0.0
_fails = {}                   # ip -> deque[timestamps]
_locked = {}                  # ip -> unlock_ts


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8", "ignore")).hexdigest()


def init_env_keys(raw_csv: str):
    """Hash the ACCESS_KEYS env fallback once at startup (architect tier)."""
    global _env_hashes
    hashes = {}
    for k in (raw_csv or "").split(","):
        k = k.strip()
        if k:
            hashes[_digest(k)] = "architect"
    with _lock:
        _env_hashes = hashes


def _reload_if_changed():
    """Hot-reload keys.json when its mtime changes (checked ≤ 1×/second)."""
    global _keys, _mtime, _last_check
    now = time.time()
    if now - _last_check < 1.0:
        return
    _last_check = now
    try:
        mt = os.path.getmtime(KEYS_PATH)
    except OSError:
        _keys = {}
        _mtime = None
        return
    if mt == _mtime:
        return
    try:
        with open(KEYS_PATH) as f:
            raw = json.load(f)
        entries = raw.get("keys", raw) if isinstance(raw, dict) else {}
        loaded = {}
        for ident, rec in entries.items():
            if not isinstance(rec, dict):
                continue
            # v2 entries are 64-hex sha256 digests; anything else is treated
            # as a legacy PLAINTEXT key and hashed on the fly so old files
            # keep working (key_gen migrates them to hashes on next use).
            h = ident if (len(ident) == 64 and all(c in "0123456789abcdef" for c in ident.lower())) \
                else _digest(ident)
            loaded[h.lower()] = {
                "tier": rec.get("tier", DEFAULT_TIER) if rec.get("tier") in TIER_LEVEL else DEFAULT_TIER,
                "active": bool(rec.get("active", True)),
                "expires": rec.get("expires"),
                "note": str(rec.get("note", ""))[:100],
                "addons": {str(k): int(v) for k, v in (rec.get("addons") or {}).items()
                           if isinstance(v, (int, float))},
            }
        _keys = loaded
        _mtime = mt
    except Exception:
        # A corrupt keys.json must not grant OR strip access mid-flight:
        # keep the last good set in memory.
        pass


def verify(key: str):
    """Timing-safe key check. Returns {"tier": str} or None.
    Never raises; never logs the key."""
    if not key or len(key) > 128:
        return None
    with _lock:
        _reload_if_changed()
        presented = _digest(key)
        # hmac.compare_digest over digests: constant-time in digest length,
        # and the hash step removes any structure an attacker could probe.
        for stored, rec in _keys.items():
            if hmac.compare_digest(presented, stored):
                if not rec.get("active", True):
                    return None
                exp = rec.get("expires")
                if exp and exp < time.strftime("%Y-%m-%d"):
                    return None
                return {"tier": rec["tier"], "hash16": presented[:16],
                        "env": False, "addons": dict(rec.get("addons") or {})}
        for stored, tier in _env_hashes.items():
            if hmac.compare_digest(presented, stored):
                return {"tier": tier, "hash16": presented[:16],
                        "env": True, "addons": {}}
    return None


def tier_ok(rec: dict, min_tier: str) -> bool:
    return TIER_LEVEL.get((rec or {}).get("tier"), 0) >= TIER_LEVEL.get(min_tier, 99)


# ─── Brute-force limiter (used by the app middleware) ─────────────────────────

def is_locked(ip: str) -> float:
    """Seconds remaining on this IP's lockout, or 0."""
    with _lock:
        until = _locked.get(ip, 0)
        now = time.time()
        if until > now:
            return until - now
        _locked.pop(ip, None)
        return 0


def record_failure(ip: str):
    """Count a failed auth; lock the IP out past the threshold."""
    now = time.time()
    with _lock:
        if len(_fails) > _MAX_TRACKED_IPS:        # bound memory
            _fails.clear()
        dq = _fails.setdefault(ip, deque(maxlen=FAIL_LIMIT * 2))
        dq.append(now)
        recent = [t for t in dq if now - t <= FAIL_WINDOW]
        if len(recent) >= FAIL_LIMIT:
            _locked[ip] = now + LOCKOUT


def record_success(ip: str):
    with _lock:
        _fails.pop(ip, None)
