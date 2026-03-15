"""BTC momentum indicator — rate of change on BTC price history."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcMomentumIndicator:
    name = "btc_momentum"
    display_name = "BTC Momentum"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        window = ctx.params.get("window", 10)
        history = ctx.snapshot.btc_price_history
        if len(history) < window:
            return None
        segment = history[-window:]
        roc = segment[-1] - segment[0]
        direction = "bullish" if roc > 0 else "bearish" if roc < 0 else "flat"
        return IndicatorResult(
            name=f"BTC Momentum ({window}pt)",
            value=roc,
            label=f"${roc:+.0f} ({direction})",
        )
