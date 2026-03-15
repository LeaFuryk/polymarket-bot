"""Token mean reversion indicator — z-score analysis."""

from __future__ import annotations

import statistics

from polybot.indicators.constants import NEAR_ZERO, Z_OVEREXTENDED, Z_STRETCHED
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class TokenMeanReversionIndicator:
    name = "token_mean_reversion"
    display_name = "Token Mean Reversion"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        window = ctx.params.get("window", 20)
        history = ctx.snapshot.price_history
        if len(history) < max(window, 2):
            return None
        segment = history[-window:]
        mean = statistics.mean(segment)
        std = statistics.stdev(segment)
        if std < NEAR_ZERO:
            return None
        z = (history[-1] - mean) / std
        if abs(z) > Z_OVEREXTENDED:
            flag = "overextended"
        elif abs(z) > Z_STRETCHED:
            flag = "stretched"
        else:
            flag = "normal"
        return IndicatorResult(
            name=f"Token Mean Reversion ({window}pt)",
            value=z,
            label=f"z={z:+.2f} ({flag})",
        )
