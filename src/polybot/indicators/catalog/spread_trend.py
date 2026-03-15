"""Spread trend indicator — spread percentage levels."""

from __future__ import annotations

from polybot.indicators.constants import SPREAD_NORMAL, SPREAD_VERY_WIDE, SPREAD_WIDE
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class SpreadTrendIndicator:
    name = "spread_trend"
    display_name = "Spread Level"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        sp = ctx.snapshot.orderbook.spread_pct
        if sp is None:
            return None
        if sp > SPREAD_VERY_WIDE:
            level = "very wide"
        elif sp > SPREAD_WIDE:
            level = "wide"
        elif sp > SPREAD_NORMAL:
            level = "normal"
        else:
            level = "tight"
        return IndicatorResult(
            name="Spread Level",
            value=sp,
            label=f"{sp:.2%} ({level})",
        )
