"""BTC vs candle open indicator — current price vs candle open."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcVsCandleOpenIndicator:
    name = "btc_vs_candle_open"
    display_name = "BTC vs Candle Open"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        if not ctx.snapshot.btc_price:
            return None

        candle_open = None
        if ctx.session and ctx.session.candle_open_btc is not None:
            candle_open = ctx.session.candle_open_btc
        elif ctx.candle_open_btc is not None:
            candle_open = ctx.candle_open_btc
        elif ctx.snapshot.btc_candles:
            candle_open = ctx.snapshot.btc_candles[-1].close

        if candle_open is None:
            return None

        current_price = ctx.snapshot.btc_price.price_usd
        diff = current_price - candle_open
        pct = diff / candle_open * 100 if candle_open else 0

        source = "recorded" if (ctx.session and ctx.session.candle_open_btc) or ctx.candle_open_btc else "estimated"
        if diff > 0:
            signal = "UP currently winning"
        elif diff < 0:
            signal = "DOWN currently winning"
        else:
            signal = "flat — UP wins ties"

        return IndicatorResult(
            name="BTC vs Candle Open",
            value=diff,
            label=f"${diff:+,.0f} ({pct:+.3f}%) — {signal} (open ${candle_open:,.0f} [{source}])",
        )
