"""Flat market edge indicator — UP structural advantage in flat conditions."""

from __future__ import annotations

from polybot.indicators.constants import DEFAULT_FLAT_THRESHOLD
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class FlatMarketEdgeIndicator:
    name = "flat_market_edge"
    display_name = "Flat Market Edge"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.btc_candles
        if len(candles) < 3:
            return None

        flat_threshold = ctx.params.get("flat_threshold", DEFAULT_FLAT_THRESHOLD)
        recent = candles[-6:] if len(candles) >= 6 else candles
        flat_count = sum(1 for c in recent if abs(c.close - c.open) < flat_threshold)
        flat_ratio = flat_count / len(recent)

        up_mid = ctx.snapshot.orderbook.midpoint

        signal_parts = [f"{flat_count}/{len(recent)} flat candles"]

        if flat_ratio >= 0.5 and up_mid is not None and up_mid < 0.50:
            signal_parts.append(f"UP underpriced at {up_mid:.3f} — structural edge")
            return IndicatorResult(
                name="Flat Market Edge",
                value=flat_ratio,
                label=" | ".join(signal_parts),
            )
        elif flat_ratio >= 0.5:
            signal_parts.append("flat market — UP wins ties")
            return IndicatorResult(
                name="Flat Market Edge",
                value=flat_ratio,
                label=" | ".join(signal_parts),
            )

        return IndicatorResult(
            name="Flat Market Edge",
            value=flat_ratio,
            label=f"{flat_count}/{len(recent)} flat candles (no edge)",
        )
