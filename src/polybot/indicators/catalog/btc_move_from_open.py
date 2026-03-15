"""BTC move from candle open indicator — consolidates BTC move computation."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcMoveFromOpenIndicator:
    name = "btc_move_from_open"
    display_name = "BTC Move From Open"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        if not ctx.snapshot.btc_price:
            return None

        btc_price = ctx.snapshot.btc_price.price_usd
        candle_open = ctx.candle_open_btc
        if candle_open is None and ctx.session:
            candle_open = ctx.session.candle_open_btc

        if candle_open is None or btc_price <= 0:
            return None

        move = btc_price - candle_open
        direction = "UP winning" if move > 0 else "DOWN winning" if move < 0 else "flat"

        return IndicatorResult(
            name="BTC Move From Open",
            value=move,
            label=f"${move:+,.0f} ({direction})",
        )
