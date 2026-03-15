"""BTC trajectory indicator — intra-candle velocity and peak drawback."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcTrajectoryIndicator:
    name = "btc_trajectory"
    display_name = "BTC Trajectory"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        history = ctx.snapshot.btc_price_history
        candle_open = ctx.candle_open_btc
        if candle_open is None or len(history) < 15:
            return None

        moves = [p - candle_open for p in history]

        recent = moves[-10:]
        earlier = moves[-30:-20] if len(moves) >= 30 else moves[:10]

        if len(recent) < 2 or len(earlier) < 2:
            return None

        current_vel = (recent[-1] - recent[0]) / len(recent)
        earlier_vel = (earlier[-1] - earlier[0]) / len(earlier)
        current_move = moves[-1]

        if current_move >= 0:
            peak = max(moves)
            drawback = peak - current_move
        else:
            peak = min(moves)
            drawback = abs(peak) - abs(current_move)

        vel_dir = (
            "accelerating"
            if abs(current_vel) > abs(earlier_vel) * 1.2
            else "decelerating"
            if abs(current_vel) < abs(earlier_vel) * 0.8
            else "steady"
        )

        if abs(drawback) >= 5.0:
            label = (
                f"${current_vel:+.1f}/s ({vel_dir}, was ${earlier_vel:+.1f}/s), "
                f"peak ${peak:+,.0f} → now ${current_move:+,.0f} (drawback ${drawback:.0f})"
            )
        else:
            label = (
                f"${current_vel:+.1f}/s ({vel_dir}, was ${earlier_vel:+.1f}/s), "
                f"no significant drawback (peak ${peak:+,.0f})"
            )

        return IndicatorResult(name=self.display_name, value=current_vel, label=label)
