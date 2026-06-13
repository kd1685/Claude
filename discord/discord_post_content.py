"""
discord_post_content.py — posts the standard Ascent Terminal server content into an
existing Discord server. Safe to re-run — deletes any previous bot messages in
each channel before reposting, so you never get duplicates.

Channels populated (under "📢 INFORMATION" category):
  #welcome  #rules  #disclaimer  #faq  #getting-started

HOW TO RUN:
    set DISCORD_BOT_TOKEN=your-bot-token
    set DISCORD_GUILD_ID=715825137785634859
    python discord_post_content.py
"""

import os
import discord

TOKEN    = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0") or 0)

CATEGORY_NAME = "📢 INFORMATION"
CONTACT       = "mrpacstar2@gmail.com"
# TODO: update CONTACT to support@yourdomain.com once domain is live
FOOTER        = "Ascent Terminal · educational · not financial advice"

C_WELCOME    = 0x5865F2
C_RULES      = 0xE67E22
C_DISCLAIMER = 0xE74C3C
C_FAQ        = 0x3498DB
C_START      = 0x2ECC71
C_PRIVACY    = 0x95A5A6

intents = discord.Intents.default()
client  = discord.Client(intents=intents)


# --------------------------------------------------------------------------- #
# Helper — wipe previous bot messages then repost                             #
# --------------------------------------------------------------------------- #

async def clear_bot_messages(channel, bot_user):
    """Delete all messages previously sent by this bot in the channel."""
    deleted = 0
    async for msg in channel.history(limit=200):
        if msg.author == bot_user:
            try:
                await msg.delete()
                deleted += 1
            except discord.HTTPException:
                pass
    if deleted:
        print(f"  🗑  Removed {deleted} old bot message(s) from #{channel.name}")


async def post_and_pin(channel, embeds, bot_user):
    """Clear old bot posts, then post each embed and pin it."""
    await clear_bot_messages(channel, bot_user)
    for embed in embeds:
        msg = await channel.send(embed=embed)
        try:
            await msg.pin()
        except discord.HTTPException:
            pass


# --------------------------------------------------------------------------- #
# Embed builders                                                               #
# --------------------------------------------------------------------------- #

def embed_welcome():
    e = discord.Embed(
        title="👋 Welcome to Ascent Terminal",
        description=(
            "Ascent Terminal is a **non-custodial, multi-broker crypto trading "
            "terminal** built for traders who want clarity, not noise.\n\n"
            "**What you get:**\n"
            "📈 **Live charts** across your favourite exchanges in one place.\n"
            "🧭 **A validated daily-trend signal model** — transparent trend "
            "signals (price vs 30-day EMA on daily candles), validated "
            "out-of-sample across ~40 coins.\n"
            "🔔 **Trend-flip alerts** posted to **#alerts** the moment a daily "
            "trend changes.\n\n"
            "**Optional add-ons:**\n"
            "🤖 An **automated trend bot** that runs on *your own machine* with "
            "*your own* trade-only API keys.\n"
            "🧠 A **Claude AI co-pilot** to help you reason about the market.\n\n"
            "🔐 **Non-custodial by design** — we never hold your API keys, your "
            "funds, or place trades on our servers. You stay in control, always.\n\n"
            "New here? Head to **#getting-started** to set up. Please read "
            "**#disclaimer** before trading with real capital."
        ),
        color=C_WELCOME,
    )
    e.set_footer(text=FOOTER)
    return e


def embed_rules():
    e = discord.Embed(
        title="📜 Community Rules",
        description=(
            "Keep this a great place for everyone. By participating you agree:\n\n"
            "**1.** Be respectful — treat every member with courtesy.\n"
            "**2.** No spam, shilling, scams, pump groups, or self-promotion.\n"
            "**3.** **Never** share, resell, or leak your access key — violation "
            "terminates your access without refund.\n"
            "**4.** Signals are **educational, not financial advice** — do not "
            "give other members financial advice.\n"
            "**5.** Keep questions in the right channels.\n"
            "**6.** English in main channels, please.\n"
            "**7.** No NSFW, illegal, or harmful content.\n"
            "**8.** Follow Discord's Terms of Service at all times.\n\n"
            "⚠️ **Enforcement:** warning → ban."
        ),
        color=C_RULES,
    )
    e.set_footer(text=FOOTER)
    return e


def embed_disclaimer():
    e = discord.Embed(
        title="⚠️ Risk Disclaimer — Read Before Trading",
        color=C_DISCLAIMER,
    )
    fields = [
        ("1. Educational Use Only",
         "Ascent Terminal is **educational software**. Nothing it produces — "
         "signals, alerts, charts, or bot activity — is financial, investment, "
         "or trading advice. We are not a licensed financial advisor. Consult "
         "a professional before making trading decisions."),
        ("2. No Profit Guarantees",
         "We make **no guarantees** of profitability or future performance. "
         "Past performance and backtested results are **not** indicative of "
         "future results."),
        ("3. Trading Risk",
         "Trading crypto and leveraged products is **extremely high risk**. "
         "You may lose **part or all** of your capital. Only trade money you "
         "can afford to lose entirely."),
        ("4. Your Responsibility",
         "You are **solely responsible** for all trading decisions, API key "
         "management, and risk settings. Always use **trade-only keys with "
         "withdrawal DISABLED**. Check that automated trading is legal in your "
         "jurisdiction."),
        ("5. Software Limitations",
         "The Service may contain bugs, delays, or data inaccuracies. We do not "
         "guarantee uninterrupted access, signal accuracy, or error-free operation."),
        ("6. Non-Custodial",
         "We **never** hold your API keys, funds, or positions. The optional bot "
         "runs on **your own machine** with **your own** keys. You are fully in "
         "control — and fully responsible."),
        ("7. No Liability",
         "To the maximum extent permitted by law, Ascent Terminal is not liable for "
         "trading losses, data loss, software errors, or any damages arising from "
         "use of the Service. **Use at your own risk.**"),
        ("8. Acknowledgement",
         "By using Ascent Terminal you confirm you understand these risks, assume "
         "full responsibility for your actions, and release Ascent Terminal and its "
         "affiliates from any resulting claims or losses."),
    ]
    for name, value in fields:
        e.add_field(name=name, value=value, inline=False)
    e.set_footer(text=FOOTER)
    return e


def embed_privacy():
    e = discord.Embed(
        title="🔒 Privacy Policy — Summary",
        description=(
            "Full policy is on the website. Key points:\n\n"
            "**What we collect:** name, email, subscription info, and usage/error "
            "logs to keep the Service running.\n\n"
            "**What we do NOT collect:** your exchange API keys, trading "
            "credentials, or balances. The Service is fully non-custodial.\n\n"
            "**How we use it:** to operate the Service, process payments, and "
            "send important updates. We do **not** sell your data.\n\n"
            "**Your rights (UK GDPR & others):** access, correct, or delete your "
            "data at any time — full contact details are on the website."
        ),
        color=C_PRIVACY,
    )
    e.set_footer(text=FOOTER)
    return e


def embed_faq():
    e = discord.Embed(title="❓ Frequently Asked Questions", color=C_FAQ)
    qa = [
        ("What is Ascent Terminal?",
         "A non-custodial, multi-broker terminal: live charts + a validated "
         "daily-trend signal model + alerts, with an optional automated bot and "
         "a Claude AI co-pilot."),
        ("What's the strategy?",
         "A daily trend model based on price vs a 30-day EMA, validated "
         "out-of-sample across ~40 coins. Simple, transparent, and robust — "
         "not a black box."),
        ("Does it guarantee profit?",
         "No. Nothing in trading is guaranteed. It's an educational tool with a "
         "transparent, backtested edge — results vary and losses happen."),
        ("Do you hold my keys or funds?",
         "Never. Fully non-custodial. The bot runs on your own machine with "
         "trade-only (no-withdrawal) keys. We never touch them."),
        ("Which exchanges are supported?",
         "MEXC natively, plus Binance, Bybit, OKX, KuCoin, Gate, Bitget, and "
         "Kraken via the multi-broker layer."),
        ("Where do trend-flip alerts go?",
         "Automatically to **#alerts** the moment a coin's daily trend changes. "
         "Right-click that channel and enable notifications to get pinged."),
        ("What returns / risk are realistic?",
         "It's a trend strategy: smoother than buy-and-hold but with real "
         "drawdowns — designed to ride trends and sidestep crashes, not get "
         "rich quick."),
        ("What are your legal terms?",
         "Full Terms of Service, Risk Disclaimer, and Privacy Policy are on the "
         "website. Pinned summaries are in **#disclaimer**. Governed by the "
         "laws of England and Wales."),
        ("Refunds?",
         "Subscriptions are non-refundable except where required by applicable "
         "law. See full Terms of Service on the website."),
        ("How do I start?",
         "See **#getting-started** for the full step-by-step guide."),
        ("Questions or support?",
         "Ask in the support channel — we're here to help."),
    ]
    for q, a in qa:
        e.add_field(name=q, value=a, inline=False)
    e.set_footer(text=FOOTER)
    return e


def embed_getting_started():
    e = discord.Embed(
        title="🚀 Getting Started",
        description=(
            "Welcome aboard! Here's how to go from zero to running:\n\n"
            "**1️⃣ Pick a tier** on Whop or Patreon.\n\n"
            "**2️⃣ Receive your access key** after checkout.\n\n"
            "**3️⃣ Open the web terminal** and unlock it with your key — or "
            "download the desktop app.\n\n"
            "**4️⃣ (Operator tier+) Run the trend bot** on your own machine. "
            "Connect your own exchange API keys — make them **TRADE-ONLY** with "
            "**withdrawal DISABLED**. This is essential.\n\n"
            "**5️⃣ Set your risk** (leverage / position size) to match your "
            "comfort level.\n\n"
            "**6️⃣ Let it run.** Check the dashboard and watch **#alerts** for "
            "trend-flip notifications.\n\n"
            "⚠️ Read **#disclaimer** before going live with real capital.\n\n"
            f"Questions? Ask in the support channel — we're happy to help."
        ),
        color=C_START,
    )
    e.set_footer(text=FOOTER)
    return e


# channel name → list of embed builders to post (in order)
CHANNELS = [
    ("welcome",         [embed_welcome]),
    ("rules",           [embed_rules]),
    ("disclaimer",      [embed_disclaimer, embed_privacy]),  # privacy posted here too
    ("faq",             [embed_faq]),
    ("getting-started", [embed_getting_started]),
]


# --------------------------------------------------------------------------- #
# Main routine                                                                 #
# --------------------------------------------------------------------------- #

async def run():
    guild = client.get_guild(GUILD_ID)
    if not guild:
        print(f"❌ Bot is not in guild {GUILD_ID}. Invite it first.")
        return

    cat = discord.utils.get(guild.categories, name=CATEGORY_NAME)
    if cat is None:
        cat = await guild.create_category(CATEGORY_NAME)
        print(f"＋ Category '{CATEGORY_NAME}' created")

    for channel_name, builders in CHANNELS:
        ch = discord.utils.get(guild.text_channels, name=channel_name)
        if ch is None:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=False
                )
            }
            ch = await guild.create_text_channel(
                channel_name, category=cat, overwrites=overwrites
            )
            print(f"＋ #{channel_name} created")

        await post_and_pin(ch, [b() for b in builders], client.user)
        print(f"✅ #{channel_name} updated")

    print("🎉 Done.")


@client.event
async def on_ready():
    print(f"Connected as {client.user}")
    try:
        await run()
    finally:
        await client.close()


if __name__ == "__main__":
    if not TOKEN or not GUILD_ID:
        raise SystemExit("Set DISCORD_BOT_TOKEN and DISCORD_GUILD_ID first.")
    client.run(TOKEN)
