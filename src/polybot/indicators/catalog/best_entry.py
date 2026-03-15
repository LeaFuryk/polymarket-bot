"""Best entry indicator — cheapest entry price across both tokens."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult
from polybot.prefilter.constants import DEFAULT_BEST_ENTRY


class BestEntryIndicator:
    name = "best_entry"
    display_name = "Best Entry"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        prices: list[float] = []
        up_ask = ctx.snapshot.orderbook.best_ask
        down_ask = ctx.snapshot.down_orderbook.best_ask
        if up_ask is not None:
            prices.append(up_ask)
        if down_ask is not None:
            prices.append(down_ask)
        best = min(prices) if prices else DEFAULT_BEST_ENTRY
        side = ""
        if up_ask is not None and down_ask is not None:
            side = " (UP)" if up_ask <= down_ask else " (DOWN)"
        return IndicatorResult(
            name="Best Entry",
            value=best,
            label=f"${best:.3f}{side}",
        )
