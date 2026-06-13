"""
Ascent Terminal — pre-deploy test suite.

Run before EVERY deploy, from the platform/ folder:

    pip install pytest httpx
    python -m pytest tests -q

Uses throwaway DB/key files (never touches data/ascent.db or keys.json)
and mocks all exchange network calls — safe to run anywhere, ~5 seconds.
"""

import json
import math
import os
import random
import sys
import time
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PLATFORM = os.path.dirname(HERE)
sys.path.insert(0, PLATFORM)

# isolated state + disarmed-by-default env, BEFORE importing the app
os.environ["ASCENT_DB"] = "/tmp/ascent_test.db"
os.environ["ASCENT_KEYS"] = "/tmp/ascent_test_keys.json"
os.environ["ACCESS_KEYS"] = "TEST-OWNER-KEY"
os.environ["EXECUTE_KEY"] = "TEST-XKEY"
os.environ["LIQ_FEED"] = "false"
os.environ["DATA_KEY"] = "19dD5MQYI_qvgDjebc-GTCgVh7EPIRq8xLmewsmoTeY="
for f in ("/tmp/ascent_test.db", "/tmp/ascent_test_keys.json"):
    if os.path.exists(f):
        os.remove(f)

# mock ccxt before anything imports it
_prices = {"BTC/USDT": 65000.0}


class _FakeEx:
    def __init__(self, *a, **k):
        pass

    def fetch_ticker(self, m):
        return {"last": _prices.get(m, 100.0)}

    def fetch_trades(self, m, limit=500):
        rng = random.Random(1)
        out, px = [], 100.0
        for i in range(300):
            px *= 1 + rng.gauss(0, 0.0005)
            big = rng.random() < 0.05
            out.append({"price": px, "amount": rng.uniform(50, 200) if big else rng.uniform(0.1, 3),
                        "side": "buy" if rng.random() < 0.55 else "sell",
                        "timestamp": 1_700_000_000_000 + i * 1500})
        return out

    def fetch_order_book(self, m, limit=100):
        mid = 100.0
        return {"bids": [[mid * (1 - 0.0002 * (i + 1)), 10] for i in range(100)],
                "asks": [[mid * (1 + 0.0002 * (i + 1)), 10] for i in range(100)]}


_fake_ccxt = types.ModuleType("ccxt")
_fake_ccxt.binance = _FakeEx
sys.modules.setdefault("ccxt", _fake_ccxt)

from fastapi.testclient import TestClient  # noqa: E402
import app as appmod                        # noqa: E402
import auth, billing, exits, key_gen        # noqa: E402

client = TestClient(appmod.app)
OWNER = {"X-Access-Key": "TEST-OWNER-KEY"}
OWNER_X = {"X-Access-Key": "TEST-OWNER-KEY", "X-Execute-Key": "TEST-XKEY"}


def _force_auth_reload():
    with auth._lock:
        auth._mtime = 0
        auth._last_check = 0


def _make_key(tier):
    db = key_gen._load()
    k = key_gen.new_key()
    db[key_gen._digest(k)] = {"tier": tier, "note": "test", "active": True,
                              "created": "2026-01-01"}
    key_gen._save(db)
    _force_auth_reload()
    return k


# ─── routes + security headers ────────────────────────────────────────────────

def test_pages_and_redirects():
    assert client.get("/").status_code == 200
    assert client.get("/app").status_code == 200
    assert client.get("/download").status_code == 200
    assert client.get("/terminal", follow_redirects=False).status_code == 308
    for p in ("terms", "privacy", "disclaimer"):
        r = client.get(f"/legal/{p}")
        assert r.status_code == 200 and "Ascent Terminal" in r.text
    assert client.get("/legal/nonsense").status_code == 404
    assert "Sitemap" in client.get("/robots.txt").text
    assert "<urlset" in client.get("/sitemap.xml").text


def test_security_headers():
    h = client.get("/api/health").headers
    assert "content-security-policy" in h
    assert "strict-transport-security" in h
    assert h["x-content-type-options"] == "nosniff"


def test_social_meta_present():
    s = client.get("/").text
    assert 'og:image' in s and 'twitter:card' in s


# ─── auth + tiers + entitlements ─────────────────────────────────────────────

def test_tier_gates():
    obs = _make_key("observer")
    assert client.get("/api/bots").status_code in (401, 403)
    assert client.get("/api/bots", headers={"X-Access-Key": obs}).status_code == 403
    assert client.get("/api/bots", headers=OWNER).status_code == 200


def test_bot_ownership_and_allowance():
    arch = _make_key("architect")
    H = {"X-Access-Key": arch}
    assert client.get("/api/bots", headers=H).json()["allowance"] == 3
    ids = []
    for _ in range(3):
        r = client.post("/api/bots/create", headers=H, json={"kind": "scalper"})
        assert r.status_code == 200
        ids.append(r.json()["bot"]["id"])
    r = client.post("/api/bots/create", headers=H, json={"kind": "trend"})
    assert r.status_code == 422 and "allowance" in r.json()["detail"]
    # cross-key control blocked; owner sees all
    assert client.delete("/api/bots/trend", headers=H).status_code == 403
    assert len(client.get("/api/bots", headers=OWNER).json()["bots"]) >= 5
    # add-on raises the cap
    assert billing._addon_apply(key_gen._digest(arch), "bots", +1)
    _force_auth_reload()
    assert client.get("/api/bots", headers=H).json()["allowance"] == 5
    for i in ids:
        client.delete(f"/api/bots/{i}", headers=H)


def test_billing_key_schema_roundtrip():
    plain = billing._issue("operator", "pytest")
    _force_auth_reload()
    rec = auth.verify(plain)
    assert rec and rec["tier"] == "operator"
    billing._revoke_hash(key_gen._digest(plain))
    _force_auth_reload()
    assert auth.verify(plain) is None


def test_ai_quota_math():
    arch = _make_key("architect")
    billing._addon_apply(key_gen._digest(arch), "ai", +1)
    _force_auth_reload()
    rec = auth.verify(arch)
    _, limit, _ = appmod._ai_quota_check(arch, rec)
    assert limit == appmod.AI_QUOTA["architect"] + 50


# ─── webhooks refuse safely when unconfigured ────────────────────────────────

def test_billing_webhooks_unconfigured():
    assert client.post("/api/whop-webhook", json={}).status_code == 503
    assert client.post("/api/stripe-webhook", json={}).status_code == 503


def test_register_validation():
    assert client.post("/api/register", json={"email": "x@example.com"}).status_code == 200
    assert client.post("/api/register", json={"email": "junk"}).status_code == 422


# ─── alerts, levels, exits ───────────────────────────────────────────────────

def test_levels_and_exit_watch():
    client.post("/api/tv-webhook", json={"symbol": "BTC_USDT", "action": "BUY",
                                         "price": 65000, "tp": 68000, "sl": 63000})
    # drag commit
    r = client.post("/api/levels/BTC_USDT", headers=OWNER, json={"tp": 69000, "sl": 63000})
    assert r.status_code == 200
    d = client.get("/api/tv-alerts/BTC_USDT", headers=OWNER).json()
    assert d["levels"]["tp"] == 69000
    assert d["alerts"][0]["action"] == "ADJUST"
    # validation + gating
    assert client.post("/api/levels/BTC_USDT", headers=OWNER, json={}).status_code == 422
    assert client.post("/api/levels/BTC_USDT", json={"tp": 1}).status_code == 401
    # exit watcher: arm → drag-sync → TP cross fires through the bridge
    r = client.post("/api/exits", headers=OWNER_X,
                    json={"symbol": "BTC_USDT", "qty": 0.001, "tp": 68000,
                          "sl": 63000, "live": False})
    assert r.status_code == 200
    client.post("/api/levels/BTC_USDT", headers=OWNER, json={"tp": 69500, "sl": 63500})
    plan = client.get("/api/exits", headers=OWNER).json()["plans"][0]
    assert plan["tp"] == 69500
    _prices["BTC/USDT"] = 69600.0
    exits._cycle()
    plan = client.get("/api/exits", headers=OWNER).json()["plans"][0]
    assert plan["status"] == "done" and "TP hit" in plan["note"]
    log = client.get("/api/exec-log", headers=OWNER).json()["orders"][0]
    assert log["source"] == "exitwatch" and log["side"] == "SELL"
    assert client.post("/api/exits", headers=OWNER,
                       json={"symbol": "X_USDT", "qty": 1, "tp": 2}).status_code == 403


# ─── live tape ────────────────────────────────────────────────────────────────

def test_orderflow_and_liquidations():
    r = client.get("/api/orderflow/BTC_USDT", headers=OWNER)
    assert r.status_code == 200 and "whale" in r.json()["trades"]
    assert client.get("/api/orderflow/BTC_USDT").status_code == 401
    import liquidations as L
    now = time.time()
    L._inject(now - 5, "BTCUSDT", True, 1_000_000)
    L._sum_cache.clear()
    s = client.get("/api/liquidations/BTC_USDT", headers=OWNER).json()
    assert s["asset"]["m5"]["long_usd"] >= 1_000_000
    assert client.get("/api/liquidations").status_code == 401


# ─── scoring engine consistency (edge_lab fast path == live panel) ───────────

def test_vote_matrix_matches_compute_panel():
    import indicators
    rng = random.Random(2)
    px, candles = 100.0, []
    for i in range(260):
        px *= 1 + 0.0005 * math.sin(i / 40) + rng.gauss(0, 0.015)
        candles.append({"time": 1_700_000_000 + i * 86400, "open": px,
                        "high": px * 1.01, "low": px * 0.99, "close": px,
                        "volume": 1000})
    keys = list(indicators.REGISTRY.keys())
    p = indicators.compute_panel(candles, volumes=None, enabled=keys, weights=None)
    votes = {k: {"BULL": 1.0, "NEUTRAL": 0.5, "BEAR": 0.0}.get(
        (p["signals"].get(k) or {}).get("vote"), 0.5) for k in keys}
    manual = sum(votes.values()) / len(keys) * 10
    assert abs(manual - p["score"]) < 0.011


# ─── GDPR / privacy layer ─────────────────────────────────────────────────────

def test_emails_encrypted_at_rest_and_unsubscribe():
    import privacy, store_db
    assert privacy.encrypted(), "DATA_KEY must be set in tests"
    addr = "alice@example.com"
    client.post("/api/register", json={"email": addr})
    raw = store_db.load_kv("register_list") or ""
    assert addr not in raw and "alice" not in raw          # nothing readable on disk
    assert addr in privacy.list_addresses()                # but sendable when needed
    # owner endpoint shows count only — never addresses
    r = client.get("/api/register-list", params={"key": "TEST-OWNER-KEY"})
    assert r.status_code == 200 and "emails" not in r.json() and r.json()["count"] >= 1
    # unsubscribe removes + permanently suppresses
    r = client.post("/api/gdpr/unsubscribe", json={"email": addr})
    assert r.status_code == 200
    assert addr not in privacy.list_addresses()
    client.post("/api/register", json={"email": addr})     # tries to come back
    assert addr not in privacy.list_addresses()            # suppression holds


def test_billing_stores_no_plaintext_email(monkeypatch):
    import billing, privacy, store_db
    sent = {}
    monkeypatch.setattr(billing, "_send_mail",
                        lambda to, subj, body: sent.update({"to": to, "body": body}))
    monkeypatch.setattr(billing, "_email_ready", lambda: True)
    addr = "buyer@example.com"
    billing._fulfil("stripe", "sub_priv1", addr, "operator")
    assert sent["to"] == addr and "/privacy-tools" in sent["body"]
    raw_map = store_db.load_kv("billing_stripe_sub_priv1") or ""
    assert addr not in raw_map and "buyer" not in raw_map
    # key note carries a tag, not the email
    db = key_gen._load()
    rec = [r for r in db.values() if "stripe:sub_priv1" in str(r.get("note",""))][0]
    assert addr not in rec["note"]


def test_full_erasure_flow(monkeypatch):
    import billing, privacy
    sent = {}
    monkeypatch.setattr(billing, "_send_mail",
                        lambda to, subj, body: sent.update({"to": to, "body": body}))
    monkeypatch.setattr(billing, "_email_ready", lambda: True)
    addr = "leaver@example.com"
    billing._fulfil("stripe", "sub_gone1", addr, "observer")
    client.post("/api/register", json={"email": addr})
    # step 1: request → confirmation email with a signed link
    r = client.post("/api/gdpr/erase", json={"email": addr})
    assert r.status_code == 200 and "erase-confirm?t=" in sent["body"]
    token = sent["body"].split("erase-confirm?t=")[1].split()[0]
    # tampered/expired tokens fail
    assert client.get("/api/gdpr/erase-confirm", params={"t": token[:-4] + "AAAA"}).status_code == 400
    # step 2: confirm → keys revoked, maps gone, mailing gone, suppressed
    r = client.get("/api/gdpr/erase-confirm", params={"t": token})
    assert r.status_code == 200 and "erased" in r.text
    _force_auth_reload()
    assert addr not in privacy.list_addresses()
    import store_db
    assert store_db.load_kv("billing_stripe_sub_gone1") is None
    assert privacy.is_suppressed(privacy.tag(addr))


# ─── Terms acceptance + finalized legal pages ────────────────────────────────

def test_terms_acceptance_flow():
    import store_db, app as A
    # /api/check advertises the current terms version
    r = client.get("/api/check", params={"key": "TEST-OWNER-KEY"})
    assert r.json()["terms_version"] == A.TERMS_VERSION
    # acceptance needs a valid key
    assert client.post("/api/accept-terms", json={}).status_code in (401, 403)
    r = client.post("/api/accept-terms", headers=OWNER,
                    json={"version": A.TERMS_VERSION})
    assert r.status_code == 200
    # recorded server-side against the hashed key id, with version + timestamp
    import auth as _a, json as _j
    h16 = _a.verify("TEST-OWNER-KEY")["hash16"]
    rec = _j.loads(store_db.load_kv(f"tos_{h16}"))
    assert rec["version"] == A.TERMS_VERSION and rec["ts"] > 0


def test_legal_pages_finalized():
    # consent control present on the lock screen
    app_html = client.get("/app").text
    assert 'id="tosChk"' in app_html and "/legal/terms" in app_html
    # finalized content: carve-outs in, draft stamps out
    terms = client.get("/legal/terms").text
    assert "fraudulent misrepresentation" in terms          # liability carve-out
    assert "Version 2026-06-12" in terms
    for page in ("terms", "privacy", "disclaimer"):
        t = client.get(f"/legal/{page}").text
        assert "solicitor" not in t.lower() and "DRAFT" not in t
        assert "mrpacstar" not in t and "support@ascentterminal.com" in t


# ─── per-user order caps ─────────────────────────────────────────────────────

def test_per_user_order_caps():
    import app as A
    op = _make_key("operator")
    H = {"X-Access-Key": op, "X-Execute-Key": "TEST-XKEY"}
    # default: inherits server ceiling (env unset in tests → 1000 default)
    r = client.get("/api/user-cap", headers={"X-Access-Key": op})
    assert r.status_code == 200 and r.json()["server_ceiling"] == A.EXEC_MAX_USD
    # user sets a personal $100 cap
    r = client.post("/api/user-cap", headers={"X-Access-Key": op}, json={"max_usd": 100})
    assert r.status_code == 200 and r.json()["effective"] == 100
    # a $150 paper order from THIS key is refused by THEIR cap
    r = client.post("/api/tv-execute", headers=H,
                    json={"symbol": "BTC_USDT", "side": "BUY", "quote_amount": 150,
                          "price": 100.0, "dry_run": True, "execute_key": "TEST-XKEY"})
    assert r.status_code == 200
    d = r.json()["result"]
    assert d["status"] == "error" and "cap" in d["detail"].lower(), d
    # $50 passes
    r = client.post("/api/tv-execute", headers=H,
                    json={"symbol": "BTC_USDT", "side": "BUY", "quote_amount": 50,
                          "price": 100.0, "dry_run": True, "execute_key": "TEST-XKEY"})
    assert r.json()["result"]["status"] == "ok"
    # user cap above the server ceiling is clamped by the ceiling
    client.post("/api/user-cap", headers={"X-Access-Key": op},
                json={"max_usd": A.EXEC_MAX_USD + 5000})
    assert client.get("/api/user-cap", headers={"X-Access-Key": op}).json()["effective"] == A.EXEC_MAX_USD
    # validation
    assert client.post("/api/user-cap", headers={"X-Access-Key": op}, json={"max_usd": "x"}).status_code == 422


# ─── Whop V1 event names ─────────────────────────────────────────────────────

def test_whop_v1_events(monkeypatch):
    import billing, hmac as _h, hashlib as _hl, json as _j
    monkeypatch.setattr(billing, "WHOP_SECRET", "whoptest")
    sent = {}
    monkeypatch.setattr(billing, "_send_mail",
                        lambda to, subj, body: sent.update({"to": to}))
    monkeypatch.setattr(billing, "_email_ready", lambda: True)

    def signed(payload):
        raw = _j.dumps(payload).encode()
        sig = _h.new(b"whoptest", raw, _hl.sha256).hexdigest()
        return client.post("/api/whop-webhook", content=raw,
                           headers={"X-Whop-Signature": sig,
                                    "Content-Type": "application/json"})

    # V1 activation issues a key at the tier found in the plan title
    r = signed({"action": "membership_activated",
                "data": {"id": "mem_v1_1", "user": {"email": "w@example.com"},
                         "plan": {"title": "Ascent Operator Monthly"}}})
    assert r.status_code == 200 and sent["to"] == "w@example.com"
    # V1 invoice_paid renews without error
    assert signed({"action": "invoice_paid",
                   "data": {"membership_id": "mem_v1_1"}}).status_code == 200
    # V1 deactivation revokes (and is not mistaken for activation)
    r = signed({"action": "membership_deactivated", "data": {"id": "mem_v1_1"}})
    assert r.status_code == 200
    import store_db
    assert store_db.load_kv("billing_whop_mem_v1_1") is None
    # bad signature refused
    raw = b"{}"
    r = client.post("/api/whop-webhook", content=raw,
                    headers={"X-Whop-Signature": "deadbeef",
                             "Content-Type": "application/json"})
    assert r.status_code == 401


# ─── payment-failed courtesy email ───────────────────────────────────────────

def test_payment_trouble_notice(monkeypatch):
    import billing, hmac as _h, hashlib as _hl, json as _j
    monkeypatch.setattr(billing, "WHOP_SECRET", "whoptest")
    sent = []
    monkeypatch.setattr(billing, "_send_mail",
                        lambda to, subj, body: sent.append((to, subj, body)))
    monkeypatch.setattr(billing, "_email_ready", lambda: True)

    def signed(payload):
        raw = _j.dumps(payload).encode()
        sig = _h.new(b"whoptest", raw, _hl.sha256).hexdigest()
        return client.post("/api/whop-webhook", content=raw,
                           headers={"X-Whop-Signature": sig,
                                    "Content-Type": "application/json"})

    signed({"action": "membership_activated",
            "data": {"id": "mem_pd1", "user": {"email": "pd@example.com"},
                     "plan": {"title": "Observer"}}})
    sent.clear()
    # past-due → one courtesy email to the right customer, key NOT revoked
    r = signed({"action": "invoice_past_due", "data": {"membership_id": "mem_pd1"}})
    assert r.status_code == 200 and r.json().get("notified") is True
    assert sent and sent[0][0] == "pd@example.com" and "payment" in sent[0][1].lower()
    import store_db
    assert store_db.load_kv("billing_whop_mem_pd1") is not None   # still subscribed
    # dunning retry within 3 days → throttled, no second email
    r = signed({"action": "invoice_past_due", "data": {"membership_id": "mem_pd1"}})
    assert r.json().get("throttled") is True and len(sent) == 1


# ─── vanity redirects ────────────────────────────────────────────────────────

def test_vanity_redirects():
    r = client.get("/patreon", follow_redirects=False)
    assert r.status_code == 302 and "patreon.com" in r.headers["location"]
    r = client.get("/whop", follow_redirects=False)
    assert r.status_code == 302 and "whop.com" in r.headers["location"]
    r = client.get("/twitter", follow_redirects=False)
    assert r.status_code == 302 and "x.com" in r.headers["location"]
    # discord 404s until SOCIAL_DISCORD is configured
    assert client.get("/discord", follow_redirects=False).status_code == 404
    # regression: literal routes must not shadow real pages
    assert client.get("/privacy-tools").status_code == 200
    assert client.get("/legal/terms").status_code == 200
