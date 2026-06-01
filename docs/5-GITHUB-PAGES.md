# 5. Publish the website on GitHub Pages (free, public)

This puts the **website** online for free at a public GitHub URL. The data pages
are public (no login). GitHub Pages hosts static files only, so the page talks to
your **tracker backend** (the VPS from guide 2) for live data. Until that backend
is online, the site loads and shows a friendly "backend isn't connected yet"
banner — and fills in automatically once it is. **No redeploy needed.**

```
 GitHub Pages (this website, public)  ──API calls──▶  your VPS backend (data + bot)
 https://kd1685.github.io/claude/                      https://rok.example.com
```

## One-time setup (you do this once, in the browser)

1. Push this repo to GitHub (already done if you've been committing).
2. On GitHub: **Settings → Pages → Build and deployment → Source = "GitHub Actions"**.
3. Make sure the repo is **Public** (Pages is free for public repos), or that you
   have GitHub Pro for private Pages.

That's the only manual step. The deploy workflow (`.github/workflows/pages.yml`)
is already in the repo; it runs on every push that touches `web/`.

## Your public link

```
https://kd1685.github.io/claude/
```

Check **Actions** tab → "Deploy website to GitHub Pages" for the green run, and
**Settings → Pages** shows the live URL once it finishes (~1 minute).

## Point it at your backend (when the bot/data is ready)

Edit **`web/config.js`**:

```js
window.API_BASE = "https://rok.example.com";   // your VPS / Caddy URL from guide 2
```

Commit + push — the workflow redeploys and the public site now shows live data.

For the browser to accept cross-site API calls, set these on the **backend**
(`deploy/.env` or the app's env) and restart it:

```bash
CORS_ORIGINS=https://kd1685.github.io   # the Pages origin (no path, no trailing slash)
# Only needed if officers will use the Control page FROM the Pages site:
COOKIE_SAMESITE=none
COOKIE_SECURE=true
```

> Tip: the public **data** pages work with just `CORS_ORIGINS`. For the
> **Control** page (titles/ranks/rotations) it's simplest to just use your VPS
> URL directly (e.g. `https://rok.example.com/control.html`) — then you don't
> need the cross-site cookie settings at all.

## Notes
- The site is fully static + self-contained (Chart.js is vendored), so it works
  on Pages with no build step.
- Links and assets use relative paths, so the `/claude/` subpath just works.
