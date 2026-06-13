"""
billing.py — automated access-key delivery, so the owner never runs
key_gen.py for a subscriber again.

Flow (both stores):
  payment succeeds  -> store calls our webhook -> verify signature
                    -> issue a key at the right tier -> email it to the buyer
  subscription ends -> store calls our webhook -> revoke that key instantly

Keys remain hashed-at-rest: the plaintext exists only inside the webhook
request that emails it. If the email cannot be sent, the freshly issued key
is revoked again and the webhook returns 500 so the store retries — a buyer
either receives their key or no key exists. Nothing is left in limbo.

Supported stores
  WHOP    POST /api/whop-webhook    (set WHOP_WEBHOOK_SECRET)
          Events: membership.went_valid -> issue, membership.went_invalid -> revoke.
          Tier from the plan/product title or metadata containing
          observer/operator/architect (name your Whop products accordingly).
  STRIPE  POST /api/stripe-webhook   (set STRIPE_WEBHOOK_SECRET, whsec_...)
          Events: checkout.session.completed -> issue,
                  customer.subscription.deleted -> revoke.
          Tier from the Payment Link's metadata: add  tier=observer|operator|architect
          when creating each Payment Link in the Stripe dashboard.

Email (any SMTP provider — Resend/Mailgun/Gmail app password/etc.):
  SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM
  Until SMTP is configured the webhooks refuse to issue (and say why),
  so a buyer can never pay without receiving a key silently.

Landing page:
  POST /api/register {email}  -> appends to a kv mailing list (deduped,
  capped, lightly rate-limited). GET /api/register-list?key=<architect key>
  to read it.
"""

import hashlib
import hmac
import json
import os
import smtplib
import threading
import time
from email.mime.text import MIMEText

from fastapi import APIRouter, Header, HTTPException, Request

import auth
import key_gen
import privacy
import store_db

router = APIRouter()

WHOP_SECRET = os.environ.get("WHOP_WEBHOOK_SECRET", "")
STRIPE_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
KEY_DAYS = int(os.environ.get("BILLING_KEY_DAYS", "33"))    # 31 + grace
SITE = os.environ.get("DOMAIN", "ascentterminal.com")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or f"support@{SITE}")

TIERS = ("observer", "operator", "architect")

_lock = threading.Lock()
_reg_hits: dict = {}                       # ip -> [timestamps] for /api/register


# ─── key issue / revoke (reuses key_gen's hashed store + hot reload) ─────────

def _issue(tier: str, note: str) -> str:
    """Create a key at `tier`, persist its hash, return the plaintext once."""
    with _lock:
        db = key_gen._load()
        plain = key_gen.new_key()
        from datetime import date, datetime, timedelta, timezone
        db[key_gen._digest(plain)] = {
            "tier": tier,
            "note": note[:120],
            "active": True,
            "created": datetime.now(timezone.utc).isoformat(),
            "expires": (date.today() + timedelta(days=KEY_DAYS)).isoformat(),
        }
        key_gen._save(db)
    return plain


def _revoke_hash(key_hash: str) -> bool:
    with _lock:
        db = key_gen._load()
        if key_hash in db:
            del db[key_hash]
            key_gen._save(db)
            return True
    return False


def _renew_hash(key_hash: str) -> bool:
    """Push an existing key's expiry forward (recurring payment on Stripe)."""
    with _lock:
        db = key_gen._load()
        rec = db.get(key_hash)
        if not rec:
            return False
        from datetime import date, timedelta
        rec["expires"] = (date.today() + timedelta(days=KEY_DAYS)).isoformat()
        rec["active"] = True
        key_gen._save(db)
    return True


# ── Add-ons: paid boosts on an existing key ──────────────────────────────────
# addon kinds and what ONE purchase unit grants:
ADDON_UNITS = {"bots": 2, "ai": 50}      # +2 bot instances · +50 AI analyses/day


def _addon_apply(key_hash: str, kind: str, units: int) -> bool:
    """units may be negative (subscription to the add-on cancelled)."""
    if kind not in ADDON_UNITS:
        return False
    with _lock:
        db = key_gen._load()
        rec = db.get(key_hash)
        if not rec:
            return False
        addons = rec.setdefault("addons", {})
        addons[kind] = max(0, int(addons.get(kind, 0)) + ADDON_UNITS[kind] * units)
        key_gen._save(db)
    return True


# membership/subscription id -> key hash, so cancellations can revoke
def _map_save(provider: str, ext_id: str, key_hash: str, email: str, tier: str):
    store_db.save_kv(f"billing_{provider}_{ext_id}", json.dumps(
        {"hash": key_hash, "email_enc": privacy.enc(email),
         "email_tag": privacy.tag(email) if email else "",
         "tier": tier, "ts": int(time.time())}))


def _map_load(provider: str, ext_id: str):
    raw = store_db.load_kv(f"billing_{provider}_{ext_id}")
    try:
        return json.loads(raw) if raw else None
    except Exception:
        return None


# ─── email ────────────────────────────────────────────────────────────────────

def _email_ready() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def _send_mail(to_addr: str, subject: str, body: str):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_addr
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as srv:
        srv.ehlo()
        try:
            srv.starttls()
            srv.ehlo()
        except smtplib.SMTPNotSupportedError:
            pass
        if SMTP_USER:
            srv.login(SMTP_USER, SMTP_PASS)
        srv.sendmail(SMTP_FROM, [to_addr], msg.as_string())


def _send_key_email(to_addr: str, tier: str, key: str):
    body = f"""Welcome to Ascent Terminal!

Your {tier.upper()} access key:

    {key}

How to use it:
  1. Open https://{SITE}/app  (or the desktop app from https://{SITE}/download)
  2. Paste the key into the box at the top right and press Unlock.

Keep this key private — it is your subscription. We store only a hashed
fingerprint of it, so this email is the only copy: save it somewhere safe.
If you lose it, reply to this email and we'll issue a replacement.

Your key renews with your subscription and stops working if you cancel.

Questions? Just reply.
Manage or delete your data anytime: https://{SITE}/privacy-tools
— Ascent Terminal
""".replace("{SITE}", SITE)
    _send_mail(to_addr, f"Your Ascent Terminal access key ({tier})", body)


def _fulfil(provider: str, ext_id: str, email: str, tier: str) -> dict:
    """Issue + email + record the mapping. All-or-nothing."""
    if tier not in TIERS:
        raise HTTPException(422, f"Unknown tier {tier!r} — name your product/metadata "
                                 f"with one of: {', '.join(TIERS)}.")
    if not email or "@" not in email:
        raise HTTPException(422, "No buyer email in the webhook payload.")
    if not _email_ready():
        raise HTTPException(503, "SMTP is not configured on the server — refusing to "
                                 "issue a key that could not be delivered. Set SMTP_HOST/"
                                 "SMTP_FROM (+ SMTP_USER/SMTP_PASS) and let the store retry.")
    existing = _map_load(provider, ext_id)
    if existing:                                  # duplicate webhook delivery
        return {"ok": True, "duplicate": True}
    plain = _issue(tier, f"{provider}:{ext_id} {privacy.tag(email)[:12]}")
    key_hash = key_gen._digest(plain)
    try:
        _send_key_email(email, tier, plain)
    except Exception as e:
        _revoke_hash(key_hash)                    # never leave an undelivered key live
        raise HTTPException(500, f"Email send failed ({type(e).__name__}) — key rolled "
                                 f"back, store will retry.")
    _map_save(provider, ext_id, key_hash, email, tier)
    store_db.save_kv(f"billing_event_{int(time.time()*1000)}",
                     json.dumps({"action": "issued", "provider": provider,
                                 "tier": tier, "who": privacy.tag(email)[:12]}))
    return {"ok": True, "tier": tier}


def _cancel(provider: str, ext_id: str) -> dict:
    rec = _map_load(provider, ext_id)
    if not rec:
        return {"ok": True, "note": "no key on record for this membership"}
    tier = str(rec.get("tier") or "")
    if tier.startswith("addon:"):                  # add-on cancelled, key survives
        _addon_apply(rec["hash"], tier.split(":", 1)[1], -1)
        store_db.delete_kv(f"billing_{provider}_{ext_id}")
        return {"ok": True, "addon_removed": tier}
    _revoke_hash(rec["hash"])
    store_db.delete_kv(f"billing_{provider}_{ext_id}")
    store_db.save_kv(f"billing_event_{int(time.time()*1000)}",
                     json.dumps({"action": "revoked", "provider": provider,
                                 "who": (rec.get("email_tag") or "")[:12]}))
    return {"ok": True, "revoked": True}


def _tier_from_text(*texts) -> str:
    blob = " ".join(str(t or "") for t in texts).lower()
    for t in ("architect", "operator", "observer"):
        if t in blob:
            return t
    return ""


# ─── WHOP ─────────────────────────────────────────────────────────────────────

@router.post("/api/whop-webhook")
async def whop_webhook(request: Request,
                       x_whop_signature: str = Header(default="")):
    if not WHOP_SECRET:
        raise HTTPException(503, "WHOP_WEBHOOK_SECRET is not set on the server.")
    raw = await request.body()
    # Whop signs the raw body with HMAC-SHA256 of your webhook secret.
    digest = hmac.new(WHOP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    supplied = (x_whop_signature or "").removeprefix("sha256=").strip()
    if not supplied or not hmac.compare_digest(digest, supplied):
        raise HTTPException(401, "Bad Whop signature.")
    try:
        evt = json.loads(raw)
    except Exception:
        raise HTTPException(422, "Webhook body is not JSON.")

    action = str(evt.get("action") or evt.get("event") or evt.get("type") or "")
    data = evt.get("data") or {}
    ext_id = str(data.get("id") or data.get("membership_id") or "")
    email = (data.get("user") or {}).get("email") or data.get("email") or ""
    tier = _tier_from_text(
        (data.get("plan") or {}).get("title") if isinstance(data.get("plan"), dict) else data.get("plan"),
        (data.get("product") or {}).get("title") if isinstance(data.get("product"), dict) else data.get("product"),
        json.dumps(data.get("metadata") or {}),
    )

    act = action.lower()
    mem_id = str(data.get("membership_id") or data.get("membership") or ext_id)
    # invalid checks FIRST ("deactivated" contains "activated")
    if any(k in act for k in ("went_invalid", "deactivated", "membership.deleted",
                              "membership_deleted", "cancel", "expired")):
        return _cancel("whop", mem_id)
    if any(k in act for k in ("went_valid", "membership_activated",
                              "membership.created", "membership_created")):
        return _fulfil("whop", mem_id, email, tier)
    if "invoice_paid" in act or "payment_succeeded" in act or "invoice.paid" in act:
        _renew_hash_by_map("whop", mem_id)
        return {"ok": True, "renewed": bool(mem_id)}
    if "past_due" in act or "payment_failed" in act:
        return _payment_trouble("whop", mem_id)
    return {"ok": True, "ignored": action}


def _payment_trouble(provider: str, ext_id: str):
    """Courtesy 'payment failed' email. Transactional (contract-related), so it
    sends regardless of marketing unsubscribe; impossible after erasure because
    the billing map is gone. Throttled to one notice per membership per 3 days
    (dunning systems retry repeatedly). Never blocks the webhook."""
    try:
        rec = _map_load(provider, ext_id)
        if not rec or not rec.get("email_enc") or not _email_ready():
            return {"ok": True, "notified": False}
        throttle_key = f"pastdue_{provider}_{ext_id}"
        last = store_db.load_kv(throttle_key)
        if last and time.time() - float(last) < 3 * 86400:
            return {"ok": True, "notified": False, "throttled": True}
        addr = privacy.dec(rec["email_enc"])           # decrypted only to send
        if not addr:
            return {"ok": True, "notified": False}
        store = "Whop (whop.com → your orders)" if provider == "whop" else                 "the Stripe billing portal (link in your payment receipt email)"
        _send_mail(addr, "Ascent Terminal — payment issue on your subscription",
                   "Hi,\n\n"
                   "A renewal payment for your Ascent Terminal subscription didn't go "
                   "through — usually an expired or replaced card.\n\n"
                   f"To keep your access key active, update your payment method via {store}. "
                   "Your access continues while the payment is retried; if it can't be "
                   "collected, the subscription will lapse and your key will deactivate "
                   "automatically.\n\n"
                   "Need help? Just reply to this email.\n"
                   "Manage or delete your data anytime: https://" + SITE + "/privacy-tools\n"
                   "— Ascent Terminal")
        store_db.save_kv(throttle_key, str(time.time()))
        store_db.save_kv(f"billing_event_{int(time.time()*1000)}",
                         json.dumps({"action": "pastdue_notice", "provider": provider,
                                     "who": (rec.get("email_tag") or "")[:12]}))
        return {"ok": True, "notified": True}
    except Exception:
        return {"ok": True, "notified": False}


def _renew_hash_by_map(provider: str, ext_id: str):
    rec = _map_load(provider, ext_id)
    if rec and rec.get("hash") and not str(rec.get("tier", "")).startswith("addon:"):
        _renew_hash(rec["hash"])


# ─── STRIPE ───────────────────────────────────────────────────────────────────

def _stripe_verify(raw: bytes, sig_header: str):
    """Verify Stripe-Signature (t=...,v1=...) without the stripe SDK."""
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    if not t or not v1:
        raise HTTPException(401, "Malformed Stripe-Signature header.")
    if abs(time.time() - int(t)) > 600:
        raise HTTPException(401, "Stale Stripe webhook (replay protection).")
    expect = hmac.new(STRIPE_SECRET.encode(),
                      f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, v1):
        raise HTTPException(401, "Bad Stripe signature.")


@router.post("/api/stripe-webhook")
async def stripe_webhook(request: Request,
                         stripe_signature: str = Header(default="")):
    if not STRIPE_SECRET:
        raise HTTPException(503, "STRIPE_WEBHOOK_SECRET is not set on the server.")
    raw = await request.body()
    _stripe_verify(raw, stripe_signature)
    try:
        evt = json.loads(raw)
    except Exception:
        raise HTTPException(422, "Webhook body is not JSON.")

    etype = evt.get("type", "")
    obj = (evt.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        ext_id = str(obj.get("subscription") or obj.get("id") or "")
        addon = str(meta.get("addon") or "").strip().lower()
        if addon:                                  # add-on purchase, not a tier
            # buyer pastes their access key into the Payment Link's custom
            # field (set its key to "accesskey" in the Stripe dashboard)
            supplied = ""
            for f in obj.get("custom_fields") or []:
                if f.get("key") in ("accesskey", "access_key"):
                    supplied = ((f.get("text") or {}).get("value") or "").strip()
            key_hash = key_gen._digest(supplied) if supplied else ""
            if not key_hash or not _addon_apply(key_hash, addon, +1):
                raise HTTPException(422, "Add-on purchase: access key missing or "
                                         "not recognised — buyer should contact support.")
            _map_save("stripe", ext_id, key_hash, "", f"addon:{addon}")
            store_db.save_kv(f"billing_event_{int(time.time()*1000)}",
                             json.dumps({"action": "addon", "kind": addon,
                                         "hash": key_hash[:12]}))
            return {"ok": True, "addon": addon}
        email = ((obj.get("customer_details") or {}).get("email")
                 or obj.get("customer_email") or "")
        tier = _tier_from_text(meta.get("tier"), json.dumps(meta))
        return _fulfil("stripe", ext_id, email, tier)

    if etype == "invoice.payment_failed":
        sub = str(obj.get("subscription") or "")
        return _payment_trouble("stripe", sub) if sub else {"ok": True}

    if etype == "invoice.paid":                    # recurring renewal
        ext_id = str(obj.get("subscription") or "")
        rec = _map_load("stripe", ext_id)
        if rec and _renew_hash(rec["hash"]):
            return {"ok": True, "renewed": True}
        return {"ok": True, "note": "nothing to renew"}

    if etype in ("customer.subscription.deleted", "charge.refunded"):
        ext_id = str(obj.get("id") if etype.startswith("customer") else
                     obj.get("subscription") or obj.get("payment_intent") or "")
        return _cancel("stripe", ext_id)

    return {"ok": True, "ignored": etype}


# ─── Landing-page mailing list ────────────────────────────────────────────────

@router.post("/api/register")
async def register(request: Request):
    ip = request.client.host if request.client else "?"
    now = time.time()
    hits = [t for t in _reg_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= 5:
        raise HTTPException(429, "Too many sign-ups from this address — try later.")
    hits.append(now)
    _reg_hits[ip] = hits
    if len(_reg_hits) > 2000:                      # drop stale IPs
        for k in [k for k, v in _reg_hits.items() if not v or now - v[-1] > 3600]:
            _reg_hits.pop(k, None)
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = str(body.get("email", "")).strip().lower()[:200]
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(422, "Enter a valid email address.")
    privacy.list_add(email)        # encrypted at rest, deduped by tag,
    return {"ok": True}            # silently respected if previously unsubscribed


# ─── GDPR self-service (fully automated — the owner never sees data) ─────────

def _gdpr_rate(ip: str):
    now = time.time()
    hits = [t for t in _reg_hits.get("g:" + ip, []) if now - t < 3600]
    if len(hits) >= 6:
        raise HTTPException(429, "Too many requests — try again later.")
    hits.append(now)
    _reg_hits["g:" + ip] = hits


@router.post("/api/gdpr/unsubscribe")
async def gdpr_unsubscribe(request: Request):
    """Instant marketing opt-out: removes the address from the mailing list
    and suppresses it permanently. Always returns ok (no enumeration)."""
    import privacy
    _gdpr_rate(request.client.host if request.client else "?")
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = str(body.get("email", "")).strip()
    if "@" not in email:
        raise HTTPException(422, "Enter a valid email address.")
    t = privacy.tag(email)
    privacy.list_remove(t)
    privacy.suppress(t)
    return {"ok": True, "message": "If that address was on our list, it has been "
                                   "removed and permanently suppressed."}


@router.post("/api/gdpr/erase")
async def gdpr_erase_request(request: Request):
    """Right-to-erasure step 1: send a signed confirmation link to the address.
    Ownership of the inbox = identity verification. Always returns ok."""
    import privacy
    _gdpr_rate(request.client.host if request.client else "?")
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = str(body.get("email", "")).strip()
    if "@" not in email:
        raise HTTPException(422, "Enter a valid email address.")
    if not _email_ready():
        raise HTTPException(503, "Email is not configured on this server yet — "
                                 "contact support to exercise your rights.")
    t = privacy.tag(email)
    token = privacy.make_token(t, "erase", ttl_s=86400)
    link = f"https://{SITE}/api/gdpr/erase-confirm?t={token}"
    try:
        _send_mail(email, "Confirm deletion of your Ascent Terminal data",
                   "You (or someone) asked us to delete all data associated with "
                   "this email address at Ascent Terminal.\n\n"
                   "If that was you, confirm by opening this link (valid 24h):\n\n"
                   f"    {link}\n\n"
                   "This will: revoke any access keys bought with this address, "
                   "delete our billing references and mailing-list entry, and "
                   "permanently suppress the address. Payment records remain with "
                   "our payment processor as required by law.\n\n"
                   "If this wasn't you, ignore this email — nothing will change.\n"
                   "— Ascent Terminal")
    except Exception:
        raise HTTPException(500, "Could not send the confirmation email — try later.")
    return {"ok": True, "message": "Check that inbox for a confirmation link "
                                   "(valid 24 hours)."}


@router.get("/api/gdpr/erase-confirm")
def gdpr_erase_confirm(t: str = ""):
    """Right-to-erasure step 2: the signed link was clicked — execute."""
    import privacy
    from fastapi.responses import HTMLResponse
    tag_v = privacy.check_token(t, "erase")
    if not tag_v:
        return HTMLResponse("<h3>Link invalid or expired.</h3><p>Request a fresh "
                            "one at /privacy-tools.</p>", status_code=400)
    res = privacy.erase_by_tag(tag_v)
    return HTMLResponse(
        "<h3>Done — your data has been erased.</h3>"
        f"<p>Mailing entries removed: {res['mailing']} · access keys revoked: "
        f"{res['keys_revoked']} · billing references deleted: {res['billing_maps']}. "
        "The address is permanently suppressed from future mailings. Payment "
        "records remain with our payment processor as required by law.</p>")


@router.get("/api/register-list")
def register_list(key: str = ""):
    """Owner view: COUNT only — addresses stay encrypted. To actually send a
    mailout, use a server-side script with privacy.list_addresses()."""
    rec = auth.verify(key)
    if not rec or not auth.tier_ok(rec, "architect"):
        raise HTTPException(401, "Architect key required.")
    n = len(privacy._load_list())
    return {"count": n, "encrypted": privacy.encrypted(),
            "note": "addresses are stored encrypted and never displayed"}
