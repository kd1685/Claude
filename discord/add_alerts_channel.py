"""
add_alerts_channel.py — adds a read-only #alerts channel to the SIGNALS category,
gated to Observer role (same as #signals). The bot posts here; members can only read.

HOW TO RUN:
    set DISCORD_BOT_TOKEN=your-bot-token
    set DISCORD_GUILD_ID=715825137785634859
    python add_alerts_channel.py
"""

import os
import unicodedata
import discord

TOKEN    = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0") or 0)

CHANNEL_NAME = "alerts"

intents = discord.Intents.default()
client  = discord.Client(intents=intents)


def find_category(guild, keyword):
    """Find a category whose name contains keyword — case-insensitive, emoji-tolerant."""
    def clean(name):
        return "".join(
            c for c in name
            if unicodedata.category(c) not in ("So", "Mn")
        ).lower().strip()
    kw = keyword.lower()
    for cat in guild.categories:
        if kw in clean(cat.name):
            return cat
    return None


@client.event
async def on_ready():
    print(f"Connected as {client.user}")
    try:
        guild = client.get_guild(GUILD_ID)
        if not guild:
            print(f"❌ Bot not in guild {GUILD_ID}.")
            return

        # Find Observer role
        observer_role = discord.utils.get(guild.roles, name="Observer")
        if not observer_role:
            print("❌ 'Observer' role not found. Run discord_setup.py first.")
            return

        # Find SIGNALS category — tolerant of emoji / capitalisation
        category = find_category(guild, "signals")
        if not category:
            print("❌ No category containing 'signals' found.")
            print("   Available categories:", [c.name for c in guild.categories])
            print("   Run discord_setup.py first, or check the category name above.")
            return
        print(f"= Found category: '{category.name}'")

        # Check if #alerts already exists
        existing = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
        if existing:
            print(f"= #alerts already exists (id={existing.id}) — skipping creation.")
            return

        # Permissions:
        #   @everyone — cannot view
        #   Observer+ — can view and read history, cannot send messages
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
            ),
            observer_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
            ),
        }

        # Runner and Developer inherit Observer access
        for role_name in ("Runner", "Developer"):
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                )

        ch = await guild.create_text_channel(
            CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            topic="🔔 Automated trend-flip alerts — posted by the bot when a coin's daily trend changes.",
            position=0,  # first channel in the SIGNALS category
        )
        print(f"✅ #alerts created (id={ch.id}) in '{category.name}' — read-only for Observer+")
        print()
        print("Next step: create a webhook in #alerts")
        print("  Discord: right-click #alerts → Edit Channel → Integrations → Webhooks → New Webhook")
        print("  Copy the URL, then set it before starting the app:")
        print("  set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...")

    finally:
        await client.close()


if __name__ == "__main__":
    if not TOKEN or not GUILD_ID:
        raise SystemExit("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID first.")
    client.run(TOKEN)
