"""
privacy.py — personal-data protection layer (UK GDPR-aligned by design).

GOAL: the owner never sees, and the server never stores, a readable customer
email. Concretely:

  * ENCRYPTION AT REST — every stored email is encrypted with Fernet
    (AES-128-CBC + HMAC) under DATA_KEY from .env. Generate once:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    Without DATA_KEY the platform still works but stores plaintext and
    prints a loud warning at startup (set it before launch).
  * EMAIL TAGS — lookups (dedupe, unsubscribe, erasure, lost-key reissue)
    use tag(email) = HMAC-SHA256(DATA_KEY, normalized email). Deterministic,
    irreversible: you can MATCH an email someone gives you without ever
    READING the ones you hold.
  * SUPPRESSION LIST — unsubscribed/erased tags are remembered (tags only),
    so a suppressed address can never silently re-enter the mailing list.
  * AUTOMATED ERASURE — a user proves address ownership by clicking a
    signed, expiring link sent to that address; the server then revokes
    their keys, deletes their billing maps and mailing entries, scrubs
    key notes, and suppresses the tag. No human involved.

What is deliberately NOT promised: emails exist transiently in webhook
requests and at the SMTP provider (a disclosed processor), and financial
records remain with Stripe as required by law. That's stated to the user.
"""

import base64
import hashlib
import hmac
import json
import os
import time

import store_db

DATA_KEY = os.environ.get("DATA_KEY", "").strip()
_fernet = None
if DATA_KEY:
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(DATA_KEY.encode())
    except Exception as e:                          # bad key → fail loud at startup
        print(f"[privacy] DATA_KEY invalid ({e}) — emails will be stored PLAINTEXT")
        _fernet = None
else:
    print("[privacy] WARNING: DATA_KEY not set — stored emails are NOT encrypted. "
          "Generate one (see privacy.py docstring) before taking real customers.")


def encrypted() -> bool:
    return _fernet is not None


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def tag(email: str) -> str:
    """Deterministic, irreversible identifier for an email."""
    key = (DATA_KEY or "ascent-fallback-pepper").encode()
    return hmac.new(key, _norm(email).encode(), hashlib.sha256).hexdigest()[:32]


def enc(email: str) -> str:
    e = _norm(email)
    if not e:
        return ""
    if _fernet:
        return "enc:" + _fernet.encrypt(e.encode()).decode()
    return "raw:" + e


def dec(stored: str) -> str:
    """Decrypt only at the moment of sending mail — never for display."""
    if not stored:
        return ""
    if stored.startswith("enc:") and _fernet:
        try:
            return _fernet.decrypt(stored[4:].encode()).decode()
        except Exception:
            return ""
    if stored.startswith("raw:"):
        return stored[4:]
    return stored                                    # legacy plaintext


# ─── suppression list (tags only — no addresses) ─────────────────────────────

def _suppressed() -> set:
    raw = store_db.load_kv("suppress_tags")
    try:
        return set(json.loads(raw)) if raw else set()
    except Exception:
        return set()


def suppress(t: str):
    s = _suppressed()
    if t not in s:
        s.add(t)
        store_db.save_kv("suppress_tags", json.dumps(sorted(s)[-20000:]))


def is_suppressed(t: str) -> bool:
    return t in _suppressed()


# ─── mailing list (encrypted entries, tag-deduped, suppression-aware) ────────

def _load_list() -> list:
    raw = store_db.load_kv("register_list")
    try:
        lst = json.loads(raw) if raw else []
    except Exception:
        lst = []
    # lazy migration of legacy plaintext entries
    changed = False
    for e in lst:
        if "email" in e and "email_enc" not in e:
            e["email_enc"] = enc(e.pop("email"))
            e["tag"] = e.get("tag") or _tag_of_enc(e["email_enc"])
            changed = True
    if changed:
        store_db.save_kv("register_list", json.dumps(lst))
    return lst


def _tag_of_enc(stored: str) -> str:
    return tag(dec(stored))


def list_add(email: str) -> bool:
    t = tag(email)
    if is_suppressed(t):
        return False                                 # objected before — stay out
    lst = _load_list()
    if any(e.get("tag") == t for e in lst):
        return True
    lst.append({"email_enc": enc(email), "tag": t, "ts": int(time.time())})
    store_db.save_kv("register_list", json.dumps(lst[-5000:]))
    return True


def list_remove(t: str) -> int:
    lst = _load_list()
    keep = [e for e in lst if e.get("tag") != t]
    removed = len(lst) - len(keep)
    if removed:
        store_db.save_kv("register_list", json.dumps(keep))
    return removed


def list_addresses() -> list:
    """Decrypted ONLY for actually sending a mailout — never displayed."""
    return [a for a in (dec(e.get("email_enc", "")) for e in _load_list()) if a]


# ─── signed, expiring action tokens (erasure confirmation links) ─────────────

def make_token(t: str, action: str, ttl_s: int = 86400) -> str:
    exp = int(time.time()) + ttl_s
    payload = f"{action}:{t}:{exp}"
    key = (DATA_KEY or "ascent-fallback-pepper").encode()
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def check_token(token: str, action: str) -> str:
    """Return the tag if valid and unexpired, else ''."""
    try:
        payload = base64.urlsafe_b64decode(token.encode()).decode()
        act, t, exp, sig = payload.split(":")
        key = (DATA_KEY or "ascent-fallback-pepper").encode()
        good = hmac.new(key, f"{act}:{t}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        if act == action and hmac.compare_digest(sig, good) and time.time() < int(exp):
            return t
    except Exception:
        pass
    return ""


# ─── full erasure (right to be forgotten) ─────────────────────────────────────

def erase_by_tag(t: str) -> dict:
    """Delete everything tied to one email tag. Returns counts (no data)."""
    import key_gen
    out = {"mailing": 0, "keys_revoked": 0, "billing_maps": 0}
    out["mailing"] = list_remove(t)
    # billing maps: kv keys billing_{provider}_{ext}; match by stored tag
    for k in store_db.kv_keys("billing_"):
        if k.startswith("billing_event_"):
            continue
        raw = store_db.load_kv(k)
        try:
            rec = json.loads(raw) if raw else {}
        except Exception:
            continue
        rec_tag = rec.get("email_tag") or (tag(rec["email"]) if rec.get("email") else "")
        if rec_tag != t:
            continue
        key_hash = rec.get("hash", "")
        if key_hash:
            db = key_gen._load()
            if key_hash in db:
                del db[key_hash]
                key_gen._save(db)
                out["keys_revoked"] += 1
        store_db.delete_kv(k)
        out["billing_maps"] += 1
    # scrub any key notes that carry this tag (no email is ever in notes now,
    # but legacy notes might hold one — remove the whole note defensively)
    db = key_gen._load()
    changed = False
    for h, rec in db.items():
        note = str(rec.get("note", ""))
        if t[:12] in note:
            rec["note"] = "erased"
            changed = True
    if changed:
        key_gen._save(db)
    suppress(t)
    store_db.save_kv(f"gdpr_event_{int(time.time()*1000)}",
                     json.dumps({"action": "erased", "tag": t[:12], **out}))
    return out
