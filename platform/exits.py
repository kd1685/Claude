"""exits.py — Exit strategy engine for Ascent Terminal.

Provides the /exits/evaluate endpoint which, given a current position and
market data, recommends whether to hold, take partial profit, or exit.

Strategies supported:
  - fixed_tp_sl   : simple take-profit / stop-loss levels
  - trailing_stop : ATR-based trailing stop
  - rsi_exit      : exit when RSI crosses overbought threshold
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exits", tags=["exits"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Position(BaseModel):
    symbol: str
    side: Literal["long", "short"]
    entry_price: float
    current_price: float
    size: float = 1.0


class MarketContext(BaseModel):
    closes: list[float] = Field(default_factory=list)
    atr: float | None = None
    rsi: float | None = None


class ExitRequest(BaseModel):
    position: Position
    context: MarketContext = MarketContext()
    strategy: str = "fixed_tp_sl"
    params: dict = Field(default_factory=dict)


class ExitRecommendation(BaseModel):
    action: Literal["hold", "partial_exit", "full_exit"]
    reason: str
    exit_price: float | None = None


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------


def _fixed_tp_sl(pos: Position, params: dict) -> ExitRecommendation:
    tp_pct = params.get("tp_pct", 2.0) / 100
    sl_pct = params.get("sl_pct", 1.0) / 100
    if pos.side == "long":
        change = (pos.current_price - pos.entry_price) / pos.entry_price
        if change >= tp_pct:
            return ExitRecommendation(action="full_exit", reason="TP reached", exit_price=pos.current_price)
        if change <= -sl_pct:
            return ExitRecommendation(action="full_exit", reason="SL hit", exit_price=pos.current_price)
    else:  # short
        change = (pos.entry_price - pos.current_price) / pos.entry_price
        if change >= tp_pct:
            return ExitRecommendation(action="full_exit", reason="TP reached", exit_price=pos.current_price)
        if change <= -sl_pct:
            return ExitRecommendation(action="full_exit", reason="SL hit", exit_price=pos.current_price)
    return ExitRecommendation(action="hold", reason="Within TP/SL range")


def _trailing_stop(pos: Position, ctx: MarketContext, params: dict) -> ExitRecommendation:
    multiplier = params.get("atr_multiplier", 2.0)
    atr = ctx.atr or params.get("atr", 0)
    if not atr:
        return ExitRecommendation(action="hold", reason="ATR unavailable")
    trail = atr * multiplier
    if pos.side == "long":
        stop = pos.current_price - trail
        if pos.current_price <= stop:
            return ExitRecommendation(action="full_exit", reason="Trailing stop hit", exit_price=pos.current_price)
    else:
        stop = pos.current_price + trail
        if pos.current_price >= stop:
            return ExitRecommendation(action="full_exit", reason="Trailing stop hit", exit_price=pos.current_price)
    return ExitRecommendation(action="hold", reason="Above trailing stop")


def _rsi_exit(pos: Position, ctx: MarketContext, params: dict) -> ExitRecommendation:
    threshold = params.get("rsi_threshold", 70)
    rsi = ctx.rsi or params.get("rsi")
    if rsi is None:
        return ExitRecommendation(action="hold", reason="RSI unavailable")
    if pos.side == "long" and rsi >= threshold:
        return ExitRecommendation(
            action="partial_exit", reason=f"RSI overbought ({rsi:.1f} >= {threshold})"
        )
    return ExitRecommendation(action="hold", reason=f"RSI within range ({rsi:.1f})")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/evaluate", response_model=ExitRecommendation)
async def evaluate_exit(
    req: ExitRequest,
    _user=Depends(require_tier("scout")),
):
    """Evaluate exit strategy for an open position."""
    strategy = req.strategy
    if strategy == "fixed_tp_sl":
        return _fixed_tp_sl(req.position, req.params)
    if strategy == "trailing_stop":
        return _trailing_stop(req.position, req.context, req.params)
    if strategy == "rsi_exit":
        return _rsi_exit(req.position, req.context, req.params)
    raise HTTPException(status_code=400, detail=f"Unknown exit strategy: '{strategy}'.")
