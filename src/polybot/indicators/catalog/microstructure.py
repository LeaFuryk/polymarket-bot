"""Microstructure indicator — cross-candle spread and volatility trends."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class MicrostructureIndicator:
    name = "microstructure"
    display_name = "Cross-Candle Microstructure"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        history = ctx.microstructure_history
        if len(history) < 2:
            return None

        recent = history[-1]
        prev = history[-2]

        # Spread trend
        spread_up_delta = recent.avg_spread_up - prev.avg_spread_up
        spread_down_delta = recent.avg_spread_down - prev.avg_spread_down
        spread_dir = (
            "widening"
            if (spread_up_delta + spread_down_delta) > 0.002
            else "narrowing"
            if (spread_up_delta + spread_down_delta) < -0.002
            else "stable"
        )

        # Volatility trend (BTC range per candle)
        ranges = [h.btc_range for h in history]
        avg_range = sum(ranges) / len(ranges)
        range_dir = (
            "increasing"
            if recent.btc_range > avg_range * 1.2
            else "decreasing"
            if recent.btc_range < avg_range * 0.8
            else "stable"
        )

        spread_delta = spread_up_delta + spread_down_delta

        label = (
            f"spreads {spread_dir} "
            f"(UP {recent.avg_spread_up:.2%}, DOWN {recent.avg_spread_down:.2%}), "
            f"BTC range ${recent.btc_range:.0f} ({range_dir}, avg ${avg_range:.0f})"
        )

        return IndicatorResult(name=self.display_name, value=spread_delta, label=label)
