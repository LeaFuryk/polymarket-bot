"""Chainlink divergence indicator — Binance vs Chainlink price divergence."""

from __future__ import annotations

from polybot.indicators.constants import (
    CHAINLINK_HIGH_DIV,
    CHAINLINK_MINOR_DIV,
    CHAINLINK_MODERATE_DIV,
)
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class ChainlinkDivergenceIndicator:
    name = "chainlink_divergence"
    display_name = "Chainlink Divergence"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        if not ctx.snapshot.btc_price or ctx.snapshot.btc_price.chainlink_price is None:
            return None

        divergence = ctx.snapshot.btc_price.price_divergence or 0.0
        abs_div = abs(divergence)
        chainlink = ctx.snapshot.btc_price.chainlink_price
        pct = divergence / chainlink * 100 if chainlink else 0

        if abs_div > CHAINLINK_HIGH_DIV:
            signal = "HIGH divergence — resolution risk"
        elif abs_div > CHAINLINK_MODERATE_DIV:
            signal = "moderate divergence — monitor"
        elif abs_div > CHAINLINK_MINOR_DIV:
            signal = "minor divergence"
        else:
            signal = "aligned"

        if divergence > CHAINLINK_MINOR_DIV:
            note = "Chainlink LOWER → resolution may differ from Binance"
        elif divergence < -CHAINLINK_MINOR_DIV:
            note = "Chainlink HIGHER → resolution may differ from Binance"
        else:
            note = ""

        label = f"${divergence:+,.0f} ({pct:+.3f}%) — {signal}"
        if note:
            label += f" | {note}"

        return IndicatorResult(
            name="Chainlink Divergence",
            value=divergence,
            label=label,
        )
