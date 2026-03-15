"""Token price divergence indicator — UP+DOWN midpoint deviation from 1.0."""

from __future__ import annotations

from polybot.indicators.constants import DIVERGENCE_MINOR, DIVERGENCE_SIGNIFICANT
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class TokenPriceDivergenceIndicator:
    name = "token_price_divergence"
    display_name = "Token Price Divergence"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        up_mid = ctx.snapshot.orderbook.midpoint
        down_mid = ctx.snapshot.down_orderbook.midpoint
        if up_mid is None or down_mid is None:
            return None
        total = up_mid + down_mid
        deviation = total - 1.0
        if abs(deviation) > DIVERGENCE_SIGNIFICANT:
            flag = "significant divergence"
        elif abs(deviation) > DIVERGENCE_MINOR:
            flag = "minor divergence"
        else:
            flag = "well-priced"
        return IndicatorResult(
            name="Token Price Divergence",
            value=deviation,
            label=f"{deviation:+.4f} ({flag})",
        )
