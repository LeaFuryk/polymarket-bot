"""Session streak indicator — win/loss count and win rate."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class SessionStreakIndicator:
    name = "session_streak"
    display_name = "Session Streak"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        if ctx.session is None:
            return None
        total = ctx.session.wins + ctx.session.losses
        if total == 0:
            return None
        wr = ctx.session.wins / total * 100
        return IndicatorResult(
            name="Session Streak",
            value=wr,
            label=f"{ctx.session.wins}W/{ctx.session.losses}L ({wr:.0f}% win rate)",
        )
