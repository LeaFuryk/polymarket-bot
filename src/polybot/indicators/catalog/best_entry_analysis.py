"""Best entry analysis indicator — UP/DOWN ask comparison with R/R."""

from __future__ import annotations

from polybot.indicators.constants import ENTRY_SIGNIFICANT_DIFF, ENTRY_SLIGHT_DIFF
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult
from polybot.indicators.helpers import compute_rr


class BestEntryAnalysisIndicator:
    name = "best_entry_analysis"
    display_name = "Best Entry Analysis"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        up_ask = ctx.snapshot.orderbook.best_ask
        down_ask = ctx.snapshot.down_orderbook.best_ask
        if up_ask is None or down_ask is None:
            return None

        up_rr = compute_rr(up_ask)
        down_rr = compute_rr(down_ask)

        cheaper = "UP" if up_ask < down_ask else "DOWN"
        diff = abs(up_ask - down_ask)

        parts = [
            f"UP ask={up_ask:.3f} (R/R={up_rr:.1f}x)",
            f"DOWN ask={down_ask:.3f} (R/R={down_rr:.1f}x)",
        ]
        if diff > ENTRY_SIGNIFICANT_DIFF:
            parts.append(f"{cheaper} significantly cheaper")
        elif diff > ENTRY_SLIGHT_DIFF:
            parts.append(f"{cheaper} slightly cheaper")
        else:
            parts.append("similar pricing")

        return IndicatorResult(
            name="Best Entry Analysis",
            value=min(up_ask, down_ask),
            label=" | ".join(parts),
        )
