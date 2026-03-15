"""Token MA crossover indicator — short/long moving average comparison."""

from __future__ import annotations

import statistics

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class TokenMaCrossoverIndicator:
    name = "token_ma_crossover"
    display_name = "Token MA Crossover"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        short_w = ctx.params.get("short_window", 5)
        long_w = ctx.params.get("long_window", 20)
        history = ctx.snapshot.price_history
        if len(history) < long_w:
            return None
        short_ma = statistics.mean(history[-short_w:])
        long_ma = statistics.mean(history[-long_w:])
        diff = short_ma - long_ma
        signal = "bullish cross" if diff > 0 else "bearish cross"
        return IndicatorResult(
            name=f"Token MA Crossover ({short_w}/{long_w})",
            value=diff,
            label=f"{diff:+.4f} ({signal})",
        )
