"""backtest.py — Back-testing engine for Ascent Terminal.

Exposes a single POST /backtest/run endpoint that accepts a strategy
definition and a symbol/interval, fetches historical OHLCV data from
Binance (public endpoint — no API key required), runs the strategy,
and returns a performance summary.

Strategy spec (simplified):
  - entry_signal: "crossover" | "rsi_oversold" | "macd_cross"
  - exit_signal:  "crossover" | "rsi_overbought" | "fixed_tp_sl"
  - params: dict of strategy-specific numeric parameters
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    limit: int = Field(500, ge=100, le=1000)
    entry_signal: str = "crossover"
    exit_signal: str = "fixed_tp_sl"
    params: dict[str, Any] = {}


class Trade(BaseModel):
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    pnl_pct: float
    direction: str


class BacktestResult(BaseModel):
    symbol: str
    interval: str
    total_trades: int
    win_rate_pct: float
    avg_pnl_pct: float
    max_drawdown_pct: float
    trades: list[Trade]


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------


async def _fetch_ohlcv(symbol: str, interval: str, limit: int) -> list[list]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            BINANCE_KLINES,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch OHLCV data from Binance.")
    return resp.json()


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------


def _ema(prices: list[float], period: int) -> list[float | None]:
    emas: list[float | None] = [None] * (period - 1)
    sma = sum(prices[:period]) / period
    emas.append(sma)
    k = 2 / (period + 1)
    for p in prices[period:]:
        emas.append(emas[-1] * (1 - k) + p * k)  # type: ignore[operator]
    return emas


def _rsi(prices: list[float], period: int = 14) -> list[float | None]:
    if len(prices) < period + 1:
        return [None] * len(prices)
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    result: list[float | None] = [None] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(prices)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss else float("inf")
        result.append(100 - 100 / (1 + rs))
    return result


def _entry_signals(closes: list[float], signal: str, params: dict) -> list[bool]:
    n = len(closes)
    if signal == "crossover":
        fast = params.get("fast", 9)
        slow = params.get("slow", 21)
        ema_fast = _ema(closes, fast)
        ema_slow = _ema(closes, slow)
        signals = [False] * n
        for i in range(1, n):
            if ema_fast[i] and ema_slow[i] and ema_fast[i - 1] and ema_slow[i - 1]:
                if ema_fast[i - 1] <= ema_slow[i - 1] and ema_fast[i] > ema_slow[i]:  # type: ignore[operator]
                    signals[i] = True
        return signals
    if signal == "rsi_oversold":
        threshold = params.get("rsi_threshold", 30)
        rsi = _rsi(closes)
        return [bool(r and r < threshold) for r in rsi]
    # Default: no entry
    return [False] * n


# ---------------------------------------------------------------------------
# Back-test runner
# ---------------------------------------------------------------------------


def _run_backtest(ohlcv: list[list], req: BacktestRequest) -> BacktestResult:
    closes = [float(c[4]) for c in ohlcv]
    entries = _entry_signals(closes, req.entry_signal, req.params)

    tp_pct = req.params.get("tp_pct", 2.0) / 100
    sl_pct = req.params.get("sl_pct", 1.0) / 100

    trades: list[Trade] = []
    in_trade = False
    entry_price = 0.0
    entry_idx = 0

    for i, close in enumerate(closes):
        if not in_trade and entries[i]:
            in_trade = True
            entry_price = close
            entry_idx = i
        elif in_trade:
            change = (close - entry_price) / entry_price
            if change >= tp_pct or change <= -sl_pct or i == len(closes) - 1:
                pnl = (close - entry_price) / entry_price * 100
                trades.append(
                    Trade(
                        entry_index=entry_idx,
                        exit_index=i,
                        entry_price=entry_price,
                        exit_price=close,
                        pnl_pct=round(pnl, 4),
                        direction="long",
                    )
                )
                in_trade = False

    total = len(trades)
    if total == 0:
        return BacktestResult(
            symbol=req.symbol,
            interval=req.interval,
            total_trades=0,
            win_rate_pct=0.0,
            avg_pnl_pct=0.0,
            max_drawdown_pct=0.0,
            trades=[],
        )

    wins = sum(1 for t in trades if t.pnl_pct > 0)
    pnls = [t.pnl_pct for t in trades]
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    return BacktestResult(
        symbol=req.symbol,
        interval=req.interval,
        total_trades=total,
        win_rate_pct=round(wins / total * 100, 2),
        avg_pnl_pct=round(statistics.mean(pnls), 4),
        max_drawdown_pct=round(max_dd, 4),
        trades=trades,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/run", response_model=BacktestResult)
async def run_backtest(
    req: BacktestRequest,
    _user=Depends(require_tier("scout")),
):
    """Run a back-test for the given strategy and symbol."""
    ohlcv = await _fetch_ohlcv(req.symbol, req.interval, req.limit)
    return _run_backtest(ohlcv, req)
