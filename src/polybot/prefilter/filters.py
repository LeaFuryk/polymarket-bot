"""Concrete filter implementations — one class per criterion.

Each filter implements the MarketFilter protocol. All are stateless;
thresholds are injected at construction time.
"""

from __future__ import annotations

from polybot.models import MarketSnapshot
from polybot.prefilter.constants import (
    CHOPPY_MAX_ENTRY,
    CHOPPY_RANGE_THRESHOLD,
    MAX_SPREAD_PCT,
    MIN_BOOK_DEPTH,
    MIN_TIME_REMAINING,
    NO_STREAK_MAX_ENTRY,
)


class OpenPositionFilter:
    """Skip AI when a position is already open — exits are handled elsewhere."""

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
        if has_open_position:
            return True, "Position open — exits handled by PositionMonitor"
        return False, ""


class TimeRemainingFilter:
    """Skip when too little time remains for a new entry."""

    def __init__(self, min_time: float = MIN_TIME_REMAINING) -> None:
        self.min_time = min_time

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
        if snapshot.time_remaining < self.min_time:
            return (
                True,
                f"Time remaining {snapshot.time_remaining:.0f}s < {self.min_time:.0f}s minimum",
            )
        return False, ""


class WideSpreadFilter:
    """Skip when both orderbooks have wide spreads."""

    def __init__(self, max_spread_pct: float = MAX_SPREAD_PCT) -> None:
        self.max_spread_pct = max_spread_pct

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
        up_spread = snapshot.orderbook.spread_pct
        down_spread = snapshot.down_orderbook.spread_pct
        if (
            up_spread is not None
            and up_spread > self.max_spread_pct
            and down_spread is not None
            and down_spread > self.max_spread_pct
        ):
            return (
                True,
                f"Both spreads wide: UP={up_spread:.2%}, DOWN={down_spread:.2%}",
            )
        return False, ""


class ThinBookFilter:
    """Skip when both orderbooks lack depth."""

    def __init__(self, min_depth: float = MIN_BOOK_DEPTH) -> None:
        self.min_depth = min_depth

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
        up_depth = snapshot.orderbook.bid_depth + snapshot.orderbook.ask_depth
        down_depth = snapshot.down_orderbook.bid_depth + snapshot.down_orderbook.ask_depth
        if up_depth < self.min_depth and down_depth < self.min_depth:
            return (
                True,
                f"Both books thin: UP={up_depth:.0f}, DOWN={down_depth:.0f}",
            )
        return False, ""


class ChoppyMarketFilter:
    """Skip when BTC range is low and no cheap entry exists."""

    def __init__(
        self,
        range_threshold: float = CHOPPY_RANGE_THRESHOLD,
        max_entry: float = CHOPPY_MAX_ENTRY,
    ) -> None:
        self.range_threshold = range_threshold
        self.max_entry = max_entry

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
        if btc_range < self.range_threshold and best_entry > self.max_entry:
            return (
                True,
                f"Choppy market (range=${btc_range:.0f} < ${self.range_threshold:.0f}) "
                f"and no cheap entry (best={best_entry:.3f} > {self.max_entry:.3f})",
            )
        return False, ""


class NoStreakFilter:
    """Skip when there's no clear directional streak and no cheap entry."""

    def __init__(self, max_entry: float = NO_STREAK_MAX_ENTRY) -> None:
        self.max_entry = max_entry

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
        if streak < 2 and best_entry > self.max_entry:
            return (
                True,
                f"No clear setup: streak={streak}, best entry={best_entry:.3f} > {self.max_entry:.3f}",
            )
        return False, ""
