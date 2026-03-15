"""BTC retracement indicator — reversal analysis for exit decisions."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcRetracementIndicator:
    name = "btc_retracement"
    display_name = "BTC Retracement"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        if not ctx.position_side:
            return None

        history = ctx.snapshot.btc_price_history
        candle_open = ctx.candle_open_btc
        if candle_open is None or len(history) < 5:
            return None

        moves = [p - candle_open for p in history]
        current_move = moves[-1]
        is_up = ctx.position_side.lower() == "up"

        # Peak in the direction favoring the held position
        if is_up:
            peak_val = max(moves)
            peak_idx = moves.index(peak_val)
        else:
            peak_val = min(moves)
            peak_idx = moves.index(peak_val)

        peak_age = len(moves) - 1 - peak_idx  # ticks since peak

        # Retracement %
        if abs(peak_val) > 0.01:
            retracement_pct = (1.0 - current_move / peak_val) * 100
        else:
            retracement_pct = 0.0
        retracement_pct = max(0.0, min(retracement_pct, 200.0))

        # Zero crossing
        if is_up:
            crossed_zero = current_move < 0
        else:
            crossed_zero = current_move > 0

        # Retreat velocity
        tail = moves[-15:] if len(moves) >= 15 else moves[-10:]
        if len(tail) >= 5:
            recent_chunk = tail[-5:]
            vel_recent = (recent_chunk[-1] - recent_chunk[0]) / len(recent_chunk)

            if is_up:
                retreat_vel = -vel_recent
            else:
                retreat_vel = vel_recent
        else:
            retreat_vel = 0.0

        cross_str = "YES (switched sides)" if crossed_zero else "NO"
        peak_label = "sustained" if peak_age > 30 else "recent"

        label = (
            f"peak ${peak_val:+,.0f} ({peak_age}s ago, {peak_label}), "
            f"now ${current_move:+,.0f}, "
            f"retraced {retracement_pct:.0f}%, "
            f"zero-cross={cross_str}, "
            f"retreat ${retreat_vel:+.1f}/s"
        )

        return IndicatorResult(
            name=self.display_name,
            value=retracement_pct,
            label=label,
        )
