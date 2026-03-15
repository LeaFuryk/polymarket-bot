"""Market trend indicator — EMA-based regime detection."""

from __future__ import annotations

from polybot.indicators.constants import (
    EMA_DIFF_SCALE,
    PRICE_DIFF_SCALE,
    TREND_MILD_THRESHOLD,
    TREND_STRONG_THRESHOLD,
)
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult
from polybot.indicators.helpers import ema


class MarketTrendIndicator:
    name = "market_trend"
    display_name = "Market Trend"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        candles = ctx.snapshot.btc_candles
        if len(candles) < 50:
            return None

        closes = [c.close for c in candles]
        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        price = closes[-1]

        ema_diff = ema20 - ema50
        ema_signal = max(-1, min(1, ema_diff / EMA_DIFF_SCALE))

        price_diff = price - ema50
        price_signal = max(-1, min(1, price_diff / PRICE_DIFF_SCALE))

        last_12 = candles[-12:]
        up_ratio = sum(1 for c in last_12 if c.direction == "up") / len(last_12)
        candle_signal = (up_ratio - 0.5) * 2

        score = 0.4 * ema_signal + 0.35 * price_signal + 0.25 * candle_signal
        score = max(-1, min(1, score))

        if score >= TREND_STRONG_THRESHOLD:
            label_text = "STRONG BULLISH"
        elif score >= TREND_MILD_THRESHOLD:
            label_text = "BULLISH"
        elif score > -TREND_MILD_THRESHOLD:
            label_text = "NEUTRAL"
        elif score > -TREND_STRONG_THRESHOLD:
            label_text = "BEARISH"
        else:
            label_text = "STRONG BEARISH"

        return IndicatorResult(
            name="Market Trend",
            value=score,
            label=f"{score:+.2f} ({label_text}) | EMA20=${ema20:,.0f} EMA50=${ema50:,.0f}",
        )
