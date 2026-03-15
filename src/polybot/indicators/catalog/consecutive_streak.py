"""Consecutive streak indicator — same-direction candle count."""

from __future__ import annotations

from polybot.indicators.constants import STREAK_MILD, STREAK_MODERATE, STREAK_STRONG
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class ConsecutiveStreakIndicator:
    name = "consecutive_streak"
    display_name = "Consecutive Streak"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.snapshot.btc_candles
        if not candles:
            return None
        streak = 1
        direction = candles[-1].direction
        for c in reversed(candles[:-1]):
            if c.direction == direction:
                streak += 1
            else:
                break
        if streak >= STREAK_STRONG:
            signal = f"strong {direction} streak — mean reversion likely"
        elif streak >= STREAK_MODERATE:
            signal = f"moderate {direction} streak — watch for reversal"
        elif streak >= STREAK_MILD:
            signal = f"mild {direction} continuation"
        else:
            signal = "no streak"
        return IndicatorResult(
            name="Consecutive Streak",
            value=float(streak),
            label=f"{streak} {direction.upper()} candles ({signal})",
        )
