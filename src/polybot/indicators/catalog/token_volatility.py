"""Token volatility indicator — standard deviation of token price."""

from __future__ import annotations

import statistics

from polybot.indicators.constants import TOKEN_VOL_HIGH, TOKEN_VOL_MODERATE
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class TokenVolatilityIndicator:
    name = "token_volatility"
    display_name = "Token Volatility"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        window = ctx.params.get("window", 20)
        history = ctx.snapshot.price_history
        if len(history) < max(window, 2):
            return None
        segment = history[-window:]
        vol = statistics.stdev(segment)
        level = "high" if vol > TOKEN_VOL_HIGH else "moderate" if vol > TOKEN_VOL_MODERATE else "low"
        return IndicatorResult(
            name=f"Token Volatility ({window}pt)",
            value=vol,
            label=f"{vol:.4f} ({level})",
        )
