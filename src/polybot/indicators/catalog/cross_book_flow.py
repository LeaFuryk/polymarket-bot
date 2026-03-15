"""Cross-book flow indicator — UP vs DOWN liquidity comparison."""

from __future__ import annotations

from polybot.indicators.constants import (
    CROSS_BOOK_BALANCED_THRESHOLD,
    CROSS_BOOK_HEAVY_THRESHOLD,
    NEAR_ZERO,
)
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class CrossBookFlowIndicator:
    name = "cross_book_flow"
    display_name = "Cross-Book Flow"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        snap = ctx.snapshot
        up_depth = snap.orderbook.bid_depth + snap.orderbook.ask_depth
        down_depth = snap.down_orderbook.bid_depth + snap.down_orderbook.ask_depth
        total = up_depth + down_depth
        if total < NEAR_ZERO:
            return None
        up_share = up_depth / total
        down_share = down_depth / total

        if up_share > CROSS_BOOK_HEAVY_THRESHOLD:
            signal = "heavy UP liquidity — possible informed bullish flow"
        elif down_share > CROSS_BOOK_HEAVY_THRESHOLD:
            signal = "heavy DOWN liquidity — possible informed bearish flow"
        elif abs(up_share - 0.5) < CROSS_BOOK_BALANCED_THRESHOLD:
            signal = "balanced liquidity"
        else:
            signal = f"UP={up_share:.0%} DOWN={down_share:.0%}"

        return IndicatorResult(
            name="Cross-Book Flow",
            value=up_share - down_share,
            label=f"UP={up_share:.0%} DOWN={down_share:.0%} ({signal})",
        )
