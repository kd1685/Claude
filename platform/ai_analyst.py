"""ai_analyst.py — AI-powered market analyst for Ascent Terminal.

Provides the /ai/analyse endpoint (POST) and a helper used by the
WebSocket hub to push periodic AI commentary to connected clients.

Supported back-ends (configured via env vars):
  - OpenAI  (OPENAI_API_KEY)
  - Anthropic / Claude  (ANTHROPIC_API_KEY)

If neither key is set the module still loads; the endpoint returns a
503 with a clear message instead of crashing the whole server.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_tier  # tier-gate helper from main app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

SYSTEM_PROMPT = (
    "You are Ascent, an expert quantitative trading analyst. "
    "Analyse the supplied market data and return a concise, actionable "
    "commentary (3–6 sentences). Focus on: dominant trend, key support/resistance, "
    "notable order-flow or liquidation clusters, and one concrete trade idea "
    "with entry, stop, and target. Be direct — no disclaimers."
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AnalyseRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "15m"
    market_data: dict[str, Any] = {}


class AnalyseResponse(BaseModel):
    commentary: str
    model_used: str
    latency_ms: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _call_openai(prompt: str) -> tuple[str, str]:
    """Returns (commentary, model_id)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 300,
                "temperature": 0.4,
            },
        )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip(), OPENAI_MODEL


async def _call_anthropic(prompt: str) -> tuple[str, str]:
    """Returns (commentary, model_id)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
            },
        )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"].strip(), ANTHROPIC_MODEL


def _build_prompt(req: AnalyseRequest) -> str:
    md_json = json.dumps(req.market_data, indent=2) if req.market_data else "(none provided)"
    return (
        f"Symbol: {req.symbol}  |  Interval: {req.interval}\n\n"
        f"Market data:\n{md_json}"
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/analyse", response_model=AnalyseResponse)
async def analyse(
    req: AnalyseRequest,
    _user=Depends(require_tier("operator")),  # operator+ required
):
    """Run AI market analysis on the supplied data snapshot."""
    if not OPENAI_API_KEY and not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="No AI provider configured. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env.",
        )

    prompt = _build_prompt(req)
    t0 = time.monotonic()

    try:
        if OPENAI_API_KEY:
            commentary, model_used = await _call_openai(prompt)
        else:
            commentary, model_used = await _call_anthropic(prompt)
    except httpx.HTTPStatusError as exc:
        logger.error("AI provider error: %s", exc.response.text)
        raise HTTPException(status_code=502, detail="AI provider returned an error.") from exc
    except httpx.RequestError as exc:
        logger.error("AI provider network error: %s", exc)
        raise HTTPException(status_code=502, detail="Could not reach AI provider.") from exc

    latency_ms = int((time.monotonic() - t0) * 1000)
    return AnalyseResponse(commentary=commentary, model_used=model_used, latency_ms=latency_ms)
