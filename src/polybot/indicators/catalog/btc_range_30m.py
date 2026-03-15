"""BTC 30-minute range indicator — consolidates BTC range computation."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult
from polybot.prefilter.constants import BTC_RANGE_CANDLE_WINDOW


class BtcRange30mIndicator:
    name = "btc_range_30m"
    display_name = "BTC Range 30m"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.snapshot.btc_candles
        if len(candles) < 2:
            return None
        recent = candles[-BTC_RANGE_CANDLE_WINDOW:]
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        btc_range = max(highs) - min(lows)
        return IndicatorResult(
            name="BTC Range 30m",
            value=btc_range,
            label=f"${btc_range:,.0f}",
        )
