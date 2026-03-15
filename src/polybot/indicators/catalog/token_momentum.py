"""Token momentum indicator — rate of change on price history."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class TokenMomentumIndicator:
    name = "token_momentum"
    display_name = "Token Momentum"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        window = ctx.params.get("window", 10)
        history = ctx.snapshot.price_history
        if len(history) < window:
            return None
        segment = history[-window:]
        roc = segment[-1] - segment[0]
        direction = "bullish" if roc > 0 else "bearish" if roc < 0 else "flat"
        return IndicatorResult(
            name=f"Token Momentum ({window}pt)",
            value=roc,
            label=f"{roc:+.4f} ({direction})",
        )
