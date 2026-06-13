"""
ai_analyst.py — Claude's read on a setup, for the web terminal.

Port of the desktop bots' ClaudeAnalyser (brain/mexc_trend_bot.py /
bots/scalper_bot.py) into the platform: Claude reviews the current state of
an asset — EMA30 trend, the user's indicator-panel votes, positioning data,
Fear & Greed, recent price action — and returns structured reasoning: is the
trend intact, what supports it, what contradicts it, key risks.

Honesty rules:
  * This is AI commentary on the logic — context and education, NOT advice,
    and the prompt instructs Claude to say so and to defer to the validated
    EMA30 rule rather than invent trade calls.
  * Responses are cached per (symbol, direction) for AI_CACHE_TTL (15 min
    default) so the owner's API bill is bounded; the UI shows cache age.
  * No key / network error / parse error all return a clear message instead
    of raising — the panel degrades gracefully.

Env:
  ANTHROPIC_API_KEY  — the owner's key (never the subscriber's).
  CLAUDE_MODEL       — default "claude-sonnet-4-5" (matches the desktop bots).
  AI_MIN_TIER        — tier needed to use the panel (default "observer").
  AI_CACHE_TTL       — seconds (default 900).
"""

import json
import os
import threading
import time

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5")
AI_CACHE_TTL = int(os.environ.get("AI_CACHE_TTL", "900") or 900)

_lock = threading.Lock()
_cache = {}                   # (symbol, direction) -> {"data":.., "ts":..}

DEPTHS = {"brief": (350, "Keep the reasoning to 3-4 tight sentences."),
          "standard": (700, "Reason step by step, a focused paragraph or two."),
          "deep": (1100, "Go deep: walk every input step by step, weigh conflicts explicitly, "
                          "and explain WHY each factor matters, not just what it shows.")}
STYLES = {"plain": "Write in plain English for a newer trader: briefly explain any jargon "
                   "or indicator you reference the first time you use it.",
          "pro": "Write terse and professional for an experienced trader: jargon is fine, "
                 "zero filler."}


def _build_prompt(symbol: str, context: dict, opts: dict) -> tuple:
    """Returns (prompt, max_tokens) shaped by the user's settings."""
    depth = opts.get("depth") if opts.get("depth") in DEPTHS else "standard"
    style = opts.get("style") if opts.get("style") in STYLES else "plain"
    sections = opts.get("sections")
    if sections is None:                          # absent -> default; [] -> none
        sections = ["outlook", "risks"]
    max_tokens, depth_rule = DEPTHS[depth]

    steps = ["1. Is the daily trend intact, weakening, or broken? Use price vs EMA30, "
             "distance, and days held."]
    n = 2
    if "indicator_panel" in context:
        steps.append(f"{n}. Do the user's enabled indicator votes agree or fight the trend? "
                     f"Name the notable dissenters."); n += 1
    if "positioning" in context or "fear_greed" in context:
        steps.append(f"{n}. Does positioning (funding, long/short ratio, open interest, "
                     f"Fear & Greed) add risk or support?"); n += 1
    if "risks" in sections:
        steps.append(f"{n}. What are the 2-3 key risks to this setup right now?")

    json_lines = ['"verdict":"TREND_INTACT|WEAKENING|MIXED|COUNTERTREND"',
                  '"confidence":7',
                  '"reasoning":"Your read, referencing the actual numbers."']
    if "outlook" in sections:
        json_lines.append('"outlook":"1-2 sentences on what would confirm or invalidate the trend."')
    if "risks" in sections:
        json_lines.append('"risks":["risk one","risk two"]')

    prompt = f"""You are the in-terminal analyst for a trend-following trading terminal.
The platform's ONE validated, out-of-sample edge is the EMA30 daily trend rule:
long above the daily EMA30, flat/short below, exit when the daily close crosses it.
Everything else (the indicator panel, positioning data) is context, not a signal.

Current state of {symbol}:
{json.dumps(context, indent=2, default=str)[:6000]}

Analyse:
{chr(10).join(steps)}

{depth_rule} {STYLES[style]}
Rules: be specific to the numbers given; no hedging boilerplate; never tell the user
to buy or sell — describe the logic and the risks. This is educational context only.

Respond ONLY in this exact JSON (no markdown, no preamble):
{{{(", ".join(json_lines))}}}"""
    return prompt, max_tokens


def analyse(symbol: str, context: dict, force: bool = False, opts: dict = None) -> dict:
    """Get Claude's read, shaped by the user's settings. Cached; never raises."""
    opts = opts or {}
    direction = (context.get("trend") or {}).get("direction", "?")
    sig = f"{opts.get('depth','standard')}|{opts.get('style','plain')}|" \
          f"{','.join(sorted(opts.get('sections') or []))}|" \
          f"{','.join(sorted(context.keys()))}"
    key = (symbol, direction, sig)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and not force and now - hit["ts"] < AI_CACHE_TTL:
            out = dict(hit["data"])
            out["cached_for"] = int(now - hit["ts"])
            return out

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return _err("NO_KEY", "ANTHROPIC_API_KEY is not set on the server — "
                              "add it to .env to enable Claude's read.")
    try:
        import requests
    except ImportError:
        return _err("ERROR", "The 'requests' package is missing on the server.")

    prompt, max_tokens = _build_prompt(symbol.replace("_", "/"), context, opts)
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": CLAUDE_MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30)
    except Exception as e:
        return _err("ERROR", f"Network error reaching api.anthropic.com: {e}")

    if resp.status_code != 200:
        return _err("ERROR", f"Anthropic API {resp.status_code}: {resp.text[:180]}")

    try:
        text = resp.json()["content"][0]["text"].strip()
        if text.startswith("```"):                # tolerate fenced output
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text.strip())
        data = {
            "verdict": str(parsed.get("verdict", "MIXED"))[:20],
            "confidence": max(0, min(10, int(parsed.get("confidence", 0)))),
            "reasoning": str(parsed.get("reasoning", ""))[:2000],
            "outlook": str(parsed.get("outlook", ""))[:500],
            "risks": [str(r)[:200] for r in (parsed.get("risks") or [])][:5],
            "model": CLAUDE_MODEL,
            "ts": now,
            "cached_for": 0,
        }
    except Exception as e:
        return _err("PARSE_ERROR", f"Could not parse Claude's reply: {e}")

    with _lock:
        _cache[key] = {"data": data, "ts": now}
    return data


def _err(verdict: str, msg: str) -> dict:
    return {"verdict": verdict, "confidence": 0, "reasoning": msg,
            "outlook": "", "risks": [], "model": CLAUDE_MODEL,
            "ts": time.time(), "cached_for": 0}
