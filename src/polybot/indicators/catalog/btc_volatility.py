"""BTC volatility indicator — standard deviation of BTC price."""

from __future__ import annotations

import statistics

from polybot.indicators.constants import BTC_VOL_HIGH, BTC_VOL_MODERATE
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcVolatilityIndicator:
    name = "btc_volatility"
    display_name = "BTC Volatility"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        window = ctx.params.get("window", 20)
        history = ctx.snapshot.btc_price_history
        if len(history) < max(window, 2):
            return None
        segment = history[-window:]
        vol = statistics.stdev(segment)
        level = "high" if vol > BTC_VOL_HIGH else "moderate" if vol > BTC_VOL_MODERATE else "low"
        return IndicatorResult(
            name=f"BTC Volatility ({window}pt)",
            value=vol,
            label=f"${vol:.0f} ({level})",
        )
