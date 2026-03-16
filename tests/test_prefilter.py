"""Tests for the prefilter package."""

from __future__ import annotations

import logging

import pytest

from polybot.models import BtcCandle, MarketSnapshot, OrderbookSnapshot
from polybot.prefilter import (
    PreFilter,
    PreFilterResult,
    compute_best_entry,
    compute_btc_range_30m,
    compute_streak,
)
from polybot.prefilter.constants import (
    BTC_RANGE_CANDLE_WINDOW,
    CHOPPY_MAX_ENTRY,
    CHOPPY_RANGE_THRESHOLD,
    DEFAULT_BEST_ENTRY,
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

# ── Helpers ──────────────────────────────────────────────────────────


def _candle(direction: str = "up", high: float = 65100.0, low: float = 65000.0) -> BtcCandle:
    o, c = (low, high) if direction == "up" else (high, low)
    return BtcCandle(open_time=0, open=o, high=high, low=low, close=c, volume=1.0, close_time=300)


def _book(bid: float = 0.50, ask: float = 0.52, depth: float = 100.0) -> OrderbookSnapshot:
    """Build an OrderbookSnapshot with the given total depth.

    Depth = sum(price * size) per side, so we solve size = depth / (2 * price)
    to get the desired total depth across both sides.
    """
    from polybot.models import OrderbookLevel

    bid_size = (depth / 2) / bid if bid else 0.0
    ask_size = (depth / 2) / ask if ask else 0.0
    return OrderbookSnapshot(
        bids=[OrderbookLevel(price=bid, size=bid_size)],
        asks=[OrderbookLevel(price=ask, size=ask_size)],
    )


def _snapshot(
    up_bid: float = 0.50,
    up_ask: float = 0.52,
    down_bid: float = 0.48,
    down_ask: float = 0.50,
    up_depth: float = 100.0,
    down_depth: float = 100.0,
) -> MarketSnapshot:
    return MarketSnapshot(
        condition_id="test",
        orderbook=_book(up_bid, up_ask, up_depth),
        down_orderbook=_book(down_bid, down_ask, down_depth),
    )


# ── Constants ────────────────────────────────────────────────────────


class TestConstants:
    def test_defaults_are_used_by_prefilter(self):
        pf = PreFilter(logger=logging.getLogger("test"))
        assert pf.min_time_remaining == MIN_TIME_REMAINING
        assert pf.max_spread_pct == MAX_SPREAD_PCT
        assert pf.min_book_depth == MIN_BOOK_DEPTH
        assert pf.choppy_range_threshold == CHOPPY_RANGE_THRESHOLD
        assert pf.choppy_max_entry == CHOPPY_MAX_ENTRY
        assert pf.no_streak_max_entry == NO_STREAK_MAX_ENTRY

    def test_btc_range_window(self):
        assert BTC_RANGE_CANDLE_WINDOW == 6

    def test_default_best_entry(self):
        assert DEFAULT_BEST_ENTRY == 1.0


# ── Signal computations ─────────────────────────────────────────────


class TestComputeStreak:
    def test_empty_candles(self):
        assert compute_streak([]) == (0, "")

    def test_single_candle(self):
        assert compute_streak([_candle("up")]) == (1, "up")

    def test_consecutive_up(self):
        candles = [_candle("up") for _ in range(4)]
        assert compute_streak(candles) == (4, "up")

    def test_mixed_ends_with_down(self):
        candles = [_candle("up"), _candle("up"), _candle("down"), _candle("down")]
        assert compute_streak(candles) == (2, "down")

    def test_break_in_middle(self):
        candles = [_candle("up"), _candle("down"), _candle("up")]
        assert compute_streak(candles) == (1, "up")


class TestComputeBtcRange:
    def test_empty(self):
        assert compute_btc_range_30m([]) == 0.0

    def test_single_candle(self):
        assert compute_btc_range_30m([_candle()]) == 0.0

    def test_two_candles(self):
        candles = [
            _candle(high=65100, low=65000),
            _candle(high=65200, low=65050),
        ]
        assert compute_btc_range_30m(candles) == pytest.approx(200.0)

    def test_uses_last_6_candles(self):
        # 8 candles, only last 6 should be used
        old = [_candle(high=99999, low=1)] * 2  # extreme range, should be excluded
        recent = [_candle(high=65100, low=65000)] * 6
        assert compute_btc_range_30m(old + recent) == pytest.approx(100.0)


class TestComputeBestEntry:
    def test_both_asks_present(self):
        assert compute_best_entry(_snapshot(up_ask=0.30, down_ask=0.25)) == pytest.approx(0.25)

    def test_only_up_ask(self):
        snap = MarketSnapshot(
            condition_id="test",
            orderbook=_book(ask=0.35),
            down_orderbook=OrderbookSnapshot(),
        )
        assert compute_best_entry(snap) == pytest.approx(0.35)

    def test_no_asks(self):
        snap = MarketSnapshot(
            condition_id="test",
            orderbook=OrderbookSnapshot(),
            down_orderbook=OrderbookSnapshot(),
        )
        assert compute_best_entry(snap) == DEFAULT_BEST_ENTRY


# ── Individual filters ───────────────────────────────────────────────

_COMMON_KWARGS = {
    "has_open_position": False,
    "streak": 3,
    "streak_direction": "up",
    "btc_range": 100.0,
    "best_entry": 0.20,
}


class TestOpenPositionFilter:
    def test_skip_when_position_open(self):
        f = OpenPositionFilter()
        skip, reason = f.check(_snapshot(), **{**_COMMON_KWARGS, "has_open_position": True})
        assert skip is True
        assert "Position open" in reason

    def test_pass_when_no_position(self):
        f = OpenPositionFilter()
        skip, _ = f.check(_snapshot(), **_COMMON_KWARGS)
        assert skip is False


class TestTimeRemainingFilter:
    def test_skip_below_threshold(self):
        f = TimeRemainingFilter(min_time=45.0)
        snap = _snapshot()
        snap.time_remaining = 30.0
        skip, reason = f.check(snap, **_COMMON_KWARGS)
        assert skip is True
        assert "30s" in reason

    def test_pass_above_threshold(self):
        f = TimeRemainingFilter(min_time=45.0)
        snap = _snapshot()
        snap.time_remaining = 60.0
        skip, _ = f.check(snap, **_COMMON_KWARGS)
        assert skip is False


class TestWideSpreadFilter:
    def test_skip_both_wide(self):
        f = WideSpreadFilter(max_spread_pct=0.05)
        # Both books have spread_pct ≈ 0.04/0.51 ≈ 0.078 > 0.05
        snap = _snapshot(up_bid=0.50, up_ask=0.54, down_bid=0.46, down_ask=0.50)
        skip, reason = f.check(snap, **_COMMON_KWARGS)
        assert skip is True
        assert "spreads wide" in reason

    def test_pass_one_tight(self):
        f = WideSpreadFilter(max_spread_pct=0.05)
        # UP tight, DOWN wide
        snap = _snapshot(up_bid=0.50, up_ask=0.51, down_bid=0.46, down_ask=0.50)
        skip, _ = f.check(snap, **_COMMON_KWARGS)
        assert skip is False


class TestThinBookFilter:
    def test_skip_both_thin(self):
        f = ThinBookFilter(min_depth=50.0)
        snap = _snapshot(up_depth=20.0, down_depth=30.0)
        skip, reason = f.check(snap, **_COMMON_KWARGS)
        assert skip is True
        assert "books thin" in reason

    def test_pass_one_deep(self):
        f = ThinBookFilter(min_depth=50.0)
        snap = _snapshot(up_depth=100.0, down_depth=20.0)
        skip, _ = f.check(snap, **_COMMON_KWARGS)
        assert skip is False


class TestChoppyMarketFilter:
    def test_skip_choppy_expensive(self):
        f = ChoppyMarketFilter(range_threshold=50.0, max_entry=0.28)
        skip, reason = f.check(_snapshot(), **{**_COMMON_KWARGS, "btc_range": 30.0, "best_entry": 0.35})
        assert skip is True
        assert "Choppy" in reason

    def test_pass_volatile(self):
        f = ChoppyMarketFilter(range_threshold=50.0, max_entry=0.28)
        skip, _ = f.check(_snapshot(), **{**_COMMON_KWARGS, "btc_range": 80.0, "best_entry": 0.35})
        assert skip is False

    def test_pass_cheap_entry(self):
        f = ChoppyMarketFilter(range_threshold=50.0, max_entry=0.28)
        skip, _ = f.check(_snapshot(), **{**_COMMON_KWARGS, "btc_range": 30.0, "best_entry": 0.20})
        assert skip is False


class TestNoStreakFilter:
    def test_skip_no_streak_expensive(self):
        f = NoStreakFilter(max_entry=0.50)
        skip, reason = f.check(_snapshot(), **{**_COMMON_KWARGS, "streak": 1, "best_entry": 0.60})
        assert skip is True
        assert "No clear setup" in reason

    def test_pass_with_streak(self):
        f = NoStreakFilter(max_entry=0.50)
        skip, _ = f.check(_snapshot(), **{**_COMMON_KWARGS, "streak": 3, "best_entry": 0.60})
        assert skip is False

    def test_pass_cheap_entry(self):
        f = NoStreakFilter(max_entry=0.50)
        skip, _ = f.check(_snapshot(), **{**_COMMON_KWARGS, "streak": 0, "best_entry": 0.30})
        assert skip is False


# ── Composite PreFilter ──────────────────────────────────────────────


class TestPreFilter:
    def test_all_pass(self):
        pf = PreFilter(logger=logging.getLogger("test"))
        candles = [_candle("up") for _ in range(4)]
        snap = _snapshot(up_ask=0.20, down_ask=0.22)
        snap.time_remaining = 120.0
        result = pf.check(snap, btc_candles=candles)
        assert result.should_skip is False
        assert result.consecutive_streak == 4
        assert result.streak_direction == "up"

    def test_skip_open_position(self):
        pf = PreFilter(logger=logging.getLogger("test"))
        snap = _snapshot()
        snap.time_remaining = 120.0
        result = pf.check(snap, has_open_position=True)
        assert result.should_skip is True
        assert "Position open" in result.reason

    def test_skip_time(self):
        pf = PreFilter(logger=logging.getLogger("test"))
        snap = _snapshot()
        snap.time_remaining = 10.0
        result = pf.check(snap)
        assert result.should_skip is True
        assert "Time remaining" in result.reason

    def test_stats_tracking(self):
        pf = PreFilter(logger=logging.getLogger("test"))
        candles = [_candle("up")] * 3
        snap1 = _snapshot(up_ask=0.20, down_ask=0.22)
        snap1.time_remaining = 120.0
        pf.check(snap1, btc_candles=candles)
        snap2 = _snapshot()
        snap2.time_remaining = 10.0
        pf.check(snap2)
        assert pf.total_checks == 2
        assert pf.total_skipped == 1
        assert pf.skip_rate == pytest.approx(0.5)

    def test_skip_rate_zero_checks(self):
        pf = PreFilter(logger=logging.getLogger("test"))
        assert pf.skip_rate == 0.0

    def test_custom_filters(self):
        """Inject a custom filter list."""
        pf = PreFilter(logger=logging.getLogger("test"), filters=[OpenPositionFilter()])
        snap = _snapshot()
        snap.time_remaining = 5.0
        # Only the open-position filter is active — time < 45s but no time filter
        result = pf.check(snap)
        assert result.should_skip is False

    def test_result_carries_signals(self):
        candles = [_candle("down", high=65200, low=65000)] * 3
        snap = _snapshot(up_ask=0.25, down_ask=0.30)
        snap.time_remaining = 120.0
        pf = PreFilter(logger=logging.getLogger("test"))
        result = pf.check(snap, btc_candles=candles)
        assert result.consecutive_streak == 3
        assert result.streak_direction == "down"
        assert result.btc_range_30m == pytest.approx(200.0)
        assert result.best_entry_price == pytest.approx(0.25)

    def test_backward_compatible_import(self):
        """Verify old import path still works."""
        from polybot.prefilter import PreFilter as PF
        from polybot.prefilter import PreFilterResult as PFR

        assert PF is PreFilter
        assert PFR is PreFilterResult
