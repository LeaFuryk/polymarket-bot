"""Streak magnitude indicator — total BTC $ move during streak."""

from __future__ import annotations

from polybot.indicators.constants import (
    MAGNITUDE_EXHAUSTION,
    MAGNITUDE_MODERATE,
    MAGNITUDE_STRONG,
)
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class StreakMagnitudeIndicator:
    name = "streak_magnitude"
    display_name = "Streak Magnitude"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.btc_candles
        if len(candles) < 2:
            return None
        direction = candles[-1].direction
        streak_start = len(candles) - 1
        for i in range(len(candles) - 2, -1, -1):
            if candles[i].direction == direction:
                streak_start = i
            else:
                break
        magnitude = candles[-1].close - candles[streak_start].open
        abs_mag = abs(magnitude)
        if abs_mag > MAGNITUDE_EXHAUSTION:
            signal = "exhaustion zone — reversal risk high"
        elif abs_mag > MAGNITUDE_STRONG:
            signal = "strong move — consider fade"
        elif abs_mag > MAGNITUDE_MODERATE:
            signal = "moderate move"
        else:
            signal = "small move"
        return IndicatorResult(
            name="Streak Magnitude",
            value=magnitude,
            label=f"${magnitude:+,.0f} ({signal})",
        )
