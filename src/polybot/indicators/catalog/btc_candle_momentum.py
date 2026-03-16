"""BTC candle momentum indicator — up/down ratio of last N candles."""

from __future__ import annotations

from polybot.indicators.constants import CANDLE_BEARISH_RATIO, CANDLE_BULLISH_RATIO
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcCandleMomentumIndicator:
    name = "btc_candle_momentum"
    display_name = "BTC Candle Momentum"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        window = ctx.params.get("window", 6)
        candles = ctx.btc_candles
        if len(candles) < window:
            return None
        recent = candles[-window:]
        up_count = sum(1 for c in recent if c.direction == "up")
        ratio = up_count / window
        if ratio >= CANDLE_BULLISH_RATIO:
            signal = "bullish momentum"
        elif ratio <= CANDLE_BEARISH_RATIO:
            signal = "bearish momentum"
        else:
            signal = "mixed"
        return IndicatorResult(
            name=f"BTC Candle Momentum ({window})",
            value=ratio,
            label=f"{up_count}/{window} up ({signal})",
        )
