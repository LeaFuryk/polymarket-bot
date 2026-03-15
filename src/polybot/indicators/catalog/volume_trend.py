"""Volume trend indicator — recent vs prior volume ratio."""

from __future__ import annotations

import statistics

from polybot.indicators.constants import (
    NEAR_ZERO,
    VOLUME_DECREASING,
    VOLUME_INCREASING,
    VOLUME_SLIGHTLY_DECREASING,
    VOLUME_SLIGHTLY_INCREASING,
)
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class VolumeTrendIndicator:
    name = "volume_trend"
    display_name = "Volume Trend"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.snapshot.btc_candles
        if len(candles) < 6:
            return None
        recent_3 = candles[-3:]
        prior_3 = candles[-6:-3]
        recent_vol = statistics.mean([c.volume for c in recent_3])
        prior_vol = statistics.mean([c.volume for c in prior_3])
        if prior_vol < NEAR_ZERO:
            return None
        ratio = recent_vol / prior_vol
        if ratio > VOLUME_INCREASING:
            signal = "increasing — confirms direction"
        elif ratio > VOLUME_SLIGHTLY_INCREASING:
            signal = "slightly increasing"
        elif ratio < VOLUME_DECREASING:
            signal = "decreasing — weakening momentum"
        elif ratio < VOLUME_SLIGHTLY_DECREASING:
            signal = "slightly decreasing"
        else:
            signal = "flat"

        return IndicatorResult(
            name="Volume Trend",
            value=ratio,
            label=f"{ratio:.2f}x ({signal})",
        )
