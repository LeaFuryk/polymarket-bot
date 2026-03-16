"""BTC candle MA cross indicator — MA5 vs MA12 on candle closes."""

from __future__ import annotations

import statistics

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcCandleMaCrossIndicator:
    name = "btc_candle_ma_cross"
    display_name = "BTC Candle MA Cross"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.btc_candles
        if len(candles) < 12:
            return None
        closes = [c.close for c in candles]
        ma5 = statistics.mean(closes[-5:])
        ma12 = statistics.mean(closes[-12:])
        diff = ma5 - ma12
        signal = "bullish cross" if diff > 0 else "bearish cross"
        return IndicatorResult(
            name="BTC Candle MA Cross (5/12)",
            value=diff,
            label=f"${diff:+.0f} ({signal})",
        )
