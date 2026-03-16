"""30-minute volatility indicator — stdev of candle ranges."""

from __future__ import annotations

import statistics

from polybot.indicators.constants import VOL30_HIGH, VOL30_LOW, VOL30_MODERATE
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class Volatility30mIndicator:
    name = "volatility_30m"
    display_name = "30min Volatility"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.btc_candles
        if len(candles) < 6:
            return None
        recent = candles[-6:]
        ranges = [c.high - c.low for c in recent]
        vol = statistics.stdev(ranges) if len(ranges) >= 2 else 0
        avg_range = statistics.mean(ranges)

        if avg_range > VOL30_HIGH:
            regime = "high volatility — trending market"
        elif avg_range > VOL30_MODERATE:
            regime = "moderate volatility"
        elif avg_range > VOL30_LOW:
            regime = "low volatility — range-bound"
        else:
            regime = "very low volatility — choppy"

        return IndicatorResult(
            name="30min Volatility",
            value=avg_range,
            label=f"avg_range=${avg_range:.0f} stdev=${vol:.0f} ({regime})",
        )
