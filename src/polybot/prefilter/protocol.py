"""MarketFilter protocol — interface for composable filter criteria."""

from __future__ import annotations

from typing import Protocol

from polybot.models import MarketSnapshot


class MarketFilter(Protocol):
    """A single filter criterion that decides whether to skip a market cycle.

    Implementations return ``(should_skip, reason)`` where *reason* is a
    human-readable explanation used in logs and the dashboard.
    """

    def check(
        self,
        snapshot: MarketSnapshot,
        *,
        has_open_position: bool,
        streak: int,
        streak_direction: str,
        btc_range: float,
        best_entry: float,
    ) -> tuple[bool, str]:
        """Return (should_skip, reason)."""
        ...
