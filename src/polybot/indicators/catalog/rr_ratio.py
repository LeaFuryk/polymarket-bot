"""Risk/reward ratio indicator — consolidates R/R computation."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult
from polybot.indicators.helpers import compute_rr


class RiskRewardIndicator:
    name = "rr_ratio"
    display_name = "Risk/Reward"

    def __init__(self) -> None:
        self.last_rr_up: float = 0.0
        self.last_rr_down: float = 0.0

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        up_ask = ctx.snapshot.orderbook.best_ask
        down_ask = ctx.snapshot.down_orderbook.best_ask
        if up_ask is None or down_ask is None:
            return None

        self.last_rr_up = compute_rr(up_ask)
        self.last_rr_down = compute_rr(down_ask)
        best_rr = max(self.last_rr_up, self.last_rr_down)
        best_side = "UP" if self.last_rr_up >= self.last_rr_down else "DOWN"

        return IndicatorResult(
            name="Risk/Reward",
            value=best_rr,
            label=f"UP={self.last_rr_up:.2f}x DOWN={self.last_rr_down:.2f}x (best: {best_side})",
        )
