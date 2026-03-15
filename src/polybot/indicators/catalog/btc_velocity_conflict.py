"""BTC velocity-magnitude conflict indicator.

Detects when BTC velocity direction conflicts with magnitude direction,
signaling a potential reversal in progress.
"""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class BtcVelocityConflictIndicator:
    name = "btc_velocity_conflict"
    display_name = "BTC Velocity Conflict"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        history = ctx.snapshot.btc_price_history
        candle_open = ctx.candle_open_btc
        if candle_open is None or len(history) < 15:
            return IndicatorResult(name=self.display_name, value=0.0, label="ALIGNED")

        moves = [p - candle_open for p in history]

        recent = moves[-10:]
        earlier = moves[-30:-20] if len(moves) >= 30 else moves[:10]

        if len(recent) < 2 or len(earlier) < 2:
            return IndicatorResult(name=self.display_name, value=0.0, label="ALIGNED")

        current_vel = (recent[-1] - recent[0]) / len(recent)
        current_move = moves[-1]

        # Peak drawback
        if current_move >= 0:
            peak = max(moves)
            drawback = peak - current_move
        else:
            peak = min(moves)
            drawback = abs(peak) - abs(current_move)

        drawback_pct = drawback / abs(peak) if abs(peak) > 0.01 else 0.0
        drawback_pct = max(0.0, min(drawback_pct, 1.0))

        mag_dir = "UP" if current_move >= 0 else "DOWN"
        vel_dir = "UP" if current_vel >= 0 else "DOWN"
        abs_vel = abs(current_vel)

        has_conflict = mag_dir != vel_dir and abs_vel > 0.5

        if not has_conflict:
            return IndicatorResult(
                name=self.display_name,
                value=0.0,
                label=f"ALIGNED (mag {mag_dir}, vel {vel_dir})",
            )

        # Severity scoring
        velocity_factor = min(abs_vel / 3.0, 1.0)
        drawback_factor = drawback_pct
        time_factor = min(ctx.time_remaining / 200.0, 1.0)
        severity = 0.4 * velocity_factor + 0.35 * drawback_factor + 0.25 * time_factor
        severity = max(0.0, min(severity, 1.0))

        if severity >= 0.7:
            label = (
                f"STRONG_CONFLICT: mag {mag_dir} ${current_move:+,.0f}, "
                f"vel ${current_vel:+.1f}/s {vel_dir}, "
                f"drawback {drawback_pct:.0%}, {ctx.time_remaining:.0f}s left, "
                f"severity {severity:.0%} — size auto-reduced 50%"
            )
        elif severity >= 0.4:
            label = (
                f"MODERATE_CONFLICT: mag {mag_dir} ${current_move:+,.0f}, "
                f"vel ${current_vel:+.1f}/s {vel_dir}, "
                f"drawback {drawback_pct:.0%}, severity {severity:.0%} — size auto-reduced 75%"
            )
        else:
            label = (
                f"ALIGNED: mag {mag_dir} ${current_move:+,.0f}, "
                f"vel ${current_vel:+.1f}/s {vel_dir}, severity {severity:.0%}"
            )

        return IndicatorResult(name=self.display_name, value=severity, label=label)
