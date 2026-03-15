"""Composite filter — chains individual MarketFilter implementations."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.indicators.results import IndicatorResults

from polybot.models import MarketSnapshot
from polybot.prefilter.constants import (
    CHOPPY_MAX_ENTRY,
    CHOPPY_RANGE_THRESHOLD,
    MAX_SPREAD_PCT,
    MIN_BOOK_DEPTH,
    MIN_TIME_REMAINING,
    NO_STREAK_MAX_ENTRY,
)
from polybot.prefilter.filters import (
    ChoppyMarketFilter,
    NoStreakFilter,
    OpenPositionFilter,
    ThinBookFilter,
    TimeRemainingFilter,
    WideSpreadFilter,
)
from polybot.prefilter.protocol import MarketFilter
from polybot.prefilter.result import PreFilterResult
from polybot.prefilter.signals import (
    compute_best_entry,
    compute_btc_range_30m,
    compute_streak,
)

logger = logging.getLogger(__name__)


def default_filters(
    min_time_remaining: float = MIN_TIME_REMAINING,
    max_spread_pct: float = MAX_SPREAD_PCT,
    min_book_depth: float = MIN_BOOK_DEPTH,
    choppy_range_threshold: float = CHOPPY_RANGE_THRESHOLD,
    choppy_max_entry: float = CHOPPY_MAX_ENTRY,
    no_streak_max_entry: float = NO_STREAK_MAX_ENTRY,
) -> list[MarketFilter]:
    """Build the standard filter pipeline with configurable thresholds."""
    return [
        OpenPositionFilter(),
        TimeRemainingFilter(min_time=min_time_remaining),
        WideSpreadFilter(max_spread_pct=max_spread_pct),
        ThinBookFilter(min_depth=min_book_depth),
        ChoppyMarketFilter(
            range_threshold=choppy_range_threshold,
            max_entry=choppy_max_entry,
        ),
        NoStreakFilter(max_entry=no_streak_max_entry),
    ]


class PreFilter:
    """Cheap rules-based screen to skip obvious HOLD cycles before calling AI.

    Runs a pipeline of composable ``MarketFilter`` implementations.
    New filters can be added without modifying existing code (OCP).
    """

    def __init__(
        self,
        min_time_remaining: float = MIN_TIME_REMAINING,
        choppy_range_threshold: float = CHOPPY_RANGE_THRESHOLD,
        choppy_max_entry: float = CHOPPY_MAX_ENTRY,
        no_streak_max_entry: float = NO_STREAK_MAX_ENTRY,
        min_streak_for_trade: int = 0,
        max_spread_pct: float = MAX_SPREAD_PCT,
        min_book_depth: float = MIN_BOOK_DEPTH,
        filters: Sequence[MarketFilter] | None = None,
    ) -> None:
        self.min_time_remaining = min_time_remaining
        self.choppy_range_threshold = choppy_range_threshold
        self.choppy_max_entry = choppy_max_entry
        self.no_streak_max_entry = no_streak_max_entry
        self.min_streak_for_trade = min_streak_for_trade
        self.max_spread_pct = max_spread_pct
        self.min_book_depth = min_book_depth

        self._filters: Sequence[MarketFilter] = filters or default_filters(
            min_time_remaining=min_time_remaining,
            max_spread_pct=max_spread_pct,
            min_book_depth=min_book_depth,
            choppy_range_threshold=choppy_range_threshold,
            choppy_max_entry=choppy_max_entry,
            no_streak_max_entry=no_streak_max_entry,
        )

        # Stats tracking
        self.total_checks = 0
        self.total_skipped = 0

    @property
    def skip_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.total_skipped / self.total_checks

    def check(
        self,
        time_remaining: float,
        snapshot: MarketSnapshot,
        has_open_position: bool = False,
    ) -> PreFilterResult:
        """Run all pre-filter checks. Returns result with should_skip flag."""
        self.total_checks += 1

        # Compute shared signals once
        candles = snapshot.btc_candles
        streak, streak_dir = compute_streak(candles)
        btc_range = compute_btc_range_30m(candles)
        best_entry = compute_best_entry(snapshot)

        result = PreFilterResult(
            should_skip=False,
            reason="",
            consecutive_streak=streak,
            streak_direction=streak_dir,
            btc_range_30m=btc_range,
            best_entry_price=best_entry,
        )

        # Run filter pipeline — first skip wins
        for f in self._filters:
            should_skip, reason = f.check(
                time_remaining,
                snapshot,
                has_open_position=has_open_position,
                streak=streak,
                streak_direction=streak_dir,
                btc_range=btc_range,
                best_entry=best_entry,
            )
            if should_skip:
                result.should_skip = True
                result.reason = reason
                self.total_skipped += 1
                logger.info("Pre-filter SKIP: %s", reason)
                return result

        return result

    def check_with_indicators(
        self,
        time_remaining: float,
        snapshot: MarketSnapshot,
        indicator_results: IndicatorResults,
        has_open_position: bool = False,
    ) -> PreFilterResult:
        """Run filter pipeline using pre-computed signals from IndicatorResults.

        Same as :meth:`check` but reads streak, BTC range, and best entry
        from a shared ``IndicatorResults`` instead of computing them here.
        """
        self.total_checks += 1

        streak = int(indicator_results.get_value("Consecutive Streak", 0))
        streak_dir = ""
        streak_result = indicator_results.get("Consecutive Streak")
        if streak_result is not None and streak > 0:
            # Direction is the first word after the count in the label
            # e.g. "3 UP candles (...)" — parse from btc_candles directly
            candles = snapshot.btc_candles
            if candles:
                streak_dir = candles[-1].direction
        btc_range = indicator_results.get_value("BTC Range 30m", 0.0)
        best_entry = indicator_results.get_value("Best Entry", 1.0)

        result = PreFilterResult(
            should_skip=False,
            reason="",
            consecutive_streak=streak,
            streak_direction=streak_dir,
            btc_range_30m=btc_range,
            best_entry_price=best_entry,
        )

        for f in self._filters:
            should_skip, reason = f.check(
                time_remaining,
                snapshot,
                has_open_position=has_open_position,
                streak=streak,
                streak_direction=streak_dir,
                btc_range=btc_range,
                best_entry=best_entry,
            )
            if should_skip:
                result.should_skip = True
                result.reason = reason
                self.total_skipped += 1
                logger.info("Pre-filter SKIP: %s", reason)
                return result

        return result
