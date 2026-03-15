"""DOWN token orderbook imbalance indicator."""

from __future__ import annotations

from polybot.indicators.constants import (
    IMBALANCE_SLIGHT_BUY,
    IMBALANCE_SLIGHT_SELL,
    IMBALANCE_STRONG_BUY,
    IMBALANCE_STRONG_SELL,
    NEAR_ZERO,
)
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class DownOrderbookImbalanceIndicator:
    name = "down_orderbook_imbalance"
    display_name = "Down Book Imbalance"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        bid_d = ctx.snapshot.down_orderbook.bid_depth
        ask_d = ctx.snapshot.down_orderbook.ask_depth
        if ask_d < NEAR_ZERO:
            return None
        ratio = bid_d / ask_d
        if ratio > IMBALANCE_STRONG_BUY:
            signal = "strong buy pressure on DOWN"
        elif ratio > IMBALANCE_SLIGHT_BUY:
            signal = "slight buy pressure on DOWN"
        elif ratio < IMBALANCE_STRONG_SELL:
            signal = "strong sell pressure on DOWN"
        elif ratio < IMBALANCE_SLIGHT_SELL:
            signal = "slight sell pressure on DOWN"
        else:
            signal = "balanced"
        return IndicatorResult(
            name="Down Book Imbalance",
            value=ratio,
            label=f"{ratio:.2f} ({signal})",
        )
