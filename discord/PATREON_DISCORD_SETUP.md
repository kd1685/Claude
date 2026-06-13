# Patreon → Discord Role Sync

Patreon has **native Discord integration** — no code needed.

## Steps (5 minutes):

**1. Connect Patreon to Discord**
- Go to **Patreon Creator Dashboard**
- Left sidebar → **Integrations** → **Discord**
- Click **Connect to Discord**
- Authorise with your Discord account

**2. Link your server**
- Select your **Ascent Terminal** server from the dropdown
- Patreon will ask for permission to manage roles — allow it

**3. Map tiers to roles**
Patreon will show your tiers on the left and your Discord roles on the right.
Map them like this:

| Patreon Tier   | Discord Role |
|----------------|--------------|
| Observer tier  | Observer     |
| Runner tier    | Runner       |
| Developer tier | Developer    |

Click **Save**.

**4. Done.**
When someone subscribes on Patreon they'll automatically receive the
matching Discord role. When they cancel, it's removed automatically.

## For Whop:
Use `discord_role_sync.py` + `role_sync_setup.bat` instead (see those files).
You need to:
1. Add your actual Whop plan IDs to the `PLAN_TO_ROLE` dict in `discord_role_sync.py`
2. Deploy it on your VPS alongside the web app
3. Add the webhook URL in Whop dashboard → Settings → Webhooks

## Finding your Whop plan IDs:
Whop dashboard → Your product → Plans → click each plan → copy the ID from
the URL or plan details page (format: `plan_xxxxxxxxxx`)
