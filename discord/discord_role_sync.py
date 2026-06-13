"""
discord_role_sync.py — Whop webhook receiver for automatic Discord role assignment.

When a subscriber joins, upgrades, or cancels on Whop, Whop fires a webhook to
this script. It assigns or removes the matching Discord role automatically.

TIER → ROLE MAPPING:
  Observer tier  → Observer role  (signals access)
  Runner tier    → Runner role    (bot access)
  Developer tier → Developer role (source access)

HOW TO DEPLOY:
  1. Run this alongside your web app on your VPS (it listens on port 8001).
  2. In Whop dashboard → Settings → Webhooks → add:
         https://yourdomain.com/whop-webhook
  3. Set WHOP_WEBHOOK_SECRET from Whop dashboard.
  4. Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID.

HOW TO RUN LOCALLY FOR TESTING:
    pip install fastapi uvicorn discord.py requests
    set DISCORD_BOT_TOKEN=your-token
    set DISCORD_GUILD_ID=715825137785634859
    set WHOP_WEBHOOK_SECRET=your-whop-secret
    uvicorn discord_role_sync:app --port 8001

NOTE ON PATREON:
  Patreon's native Discord integration (Patreon dashboard → Integrations →
  Discord) handles role sync automatically without code — connect it there.
  This script is for Whop only.
"""

import os
import hmac
import hashlib
import discord
import asyncio
from fastapi import FastAPI, Request, HTTPException

# --------------------------------------------------------------------------- #
# Config                                                                       #
# --------------------------------------------------------------------------- #

DISCORD_TOKEN   = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID        = int(os.environ.get("DISCORD_GUILD_ID", "0") or 0)
WHOP_SECRET     = os.environ.get("WHOP_WEBHOOK_SECRET", "").strip()

# Map Whop plan/product IDs → Discord role names
# TODO: replace the keys with your actual Whop plan IDs from your dashboard
#       Whop dashboard → Your product → Plans → copy the plan ID (e.g. plan_xxxx)
PLAN_TO_ROLE = {
    "plan_observer_id_here":  "Observer",
    "plan_runner_id_here":    "Runner",
    "plan_developer_id_here": "Developer",
}

app = FastAPI()

# --------------------------------------------------------------------------- #
# Discord helper                                                               #
# --------------------------------------------------------------------------- #

async def set_discord_role(discord_id: str, role_name: str, add: bool):
    """Add or remove a Discord role for a user by their Discord user ID."""
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            guild  = client.get_guild(GUILD_ID)
            if not guild:
                print(f"❌ Guild {GUILD_ID} not found")
                return

            member = guild.get_member(int(discord_id))
            if not member:
                # Try fetching if not in cache
                try:
                    member = await guild.fetch_member(int(discord_id))
                except discord.NotFound:
                    print(f"❌ Member {discord_id} not in guild")
                    return

            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                print(f"❌ Role '{role_name}' not found")
                return

            if add:
                await member.add_roles(role)
                print(f"✅ Added '{role_name}' to {member.name}")
            else:
                await member.remove_roles(role)
                print(f"🗑  Removed '{role_name}' from {member.name}")
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)


# --------------------------------------------------------------------------- #
# Whop webhook endpoint                                                        #
# --------------------------------------------------------------------------- #

def verify_whop_signature(body: bytes, signature: str) -> bool:
    """Verify the Whop webhook HMAC-SHA256 signature."""
    if not WHOP_SECRET:
        return True  # skip verification if secret not set (dev only)
    expected = hmac.new(
        WHOP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@app.post("/whop-webhook")
async def whop_webhook(request: Request):
    body      = await request.body()
    signature = request.headers.get("x-whop-signature", "")

    if not verify_whop_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event   = payload.get("event", "")
    data    = payload.get("data", {})

    discord_id = data.get("discord_account_id") or data.get("discord_id")
    plan_id    = data.get("plan_id") or data.get("product_id")
    role_name  = PLAN_TO_ROLE.get(plan_id)

    if not discord_id or not role_name:
        # Not a mapped plan or no Discord ID — ignore silently
        return {"status": "ignored"}

    # membership.went_valid  → user paid / joined   → ADD role
    # membership.went_invalid → cancelled / expired → REMOVE role
    if event == "membership.went_valid":
        asyncio.create_task(set_discord_role(discord_id, role_name, add=True))
        return {"status": "role_add_queued"}

    elif event == "membership.went_invalid":
        asyncio.create_task(set_discord_role(discord_id, role_name, add=False))
        return {"status": "role_remove_queued"}

    return {"status": "unhandled_event"}


# --------------------------------------------------------------------------- #
# Health check                                                                 #
# --------------------------------------------------------------------------- #

@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("discord_role_sync:app", host="0.0.0.0", port=8001, reload=False)
