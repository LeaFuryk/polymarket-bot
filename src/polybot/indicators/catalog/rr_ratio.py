"""Risk/reward ratio indicator — consolidates R/R computation."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult
from polybot.indicators.helpers import compute_rr


class RiskRewardIndicator:
    name = "rr_ratio"
    display_name = "Risk/Reward"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        up_ask = ctx.snapshot.orderbook.best_ask
        down_ask = ctx.snapshot.down_orderbook.best_ask
        if up_ask is None or down_ask is None:
            return None

        rr_up = compute_rr(up_ask)
        rr_down = compute_rr(down_ask)
        best_rr = max(rr_up, rr_down)
        best_side = "UP" if rr_up >= rr_down else "DOWN"

        return IndicatorResult(
            name="Risk/Reward",
            value=best_rr,
            label=f"UP={rr_up:.2f}x DOWN={rr_down:.2f}x (best: {best_side})",
        )
