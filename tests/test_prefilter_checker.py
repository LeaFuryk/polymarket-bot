"""Tests for PrefilterChecker."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from polybot.models.core import (
    BtcPrice,
    MarketSnapshot,
    OrderbookLevel,
    OrderbookSnapshot,
)
from polybot.prefilter.checker import CheckResult, PrefilterChecker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orderbook(best_bid: float, best_ask: float, depth: float = 100.0):
    return OrderbookSnapshot(
        bids=[OrderbookLevel(price=best_bid, size=depth / best_bid)],
        asks=[OrderbookLevel(price=best_ask, size=depth / best_ask)],
    )


def _make_snapshot(
    up_bid=0.48,
    up_ask=0.52,
    down_bid=0.46,
    down_ask=0.50,
    btc_price=65000.0,
):
    return MarketSnapshot(
        condition_id="cond_test",
        orderbook=_make_orderbook(up_bid, up_ask),
        down_orderbook=_make_orderbook(down_bid, down_ask),
        btc_price=BtcPrice(price_usd=btc_price),
    )


def _make_prefilter_result(should_skip=False, reason="", streak=0, direction=""):
    result = MagicMock()
    result.should_skip = should_skip
    result.reason = reason
    result.consecutive_streak = streak
    result.streak_direction = direction
    result.btc_range_30m = 0.0
    result.best_entry_price = 1.0
    return result


def _make_checker():
    prefilter = MagicMock()
    prefilter.check.return_value = _make_prefilter_result()
    return PrefilterChecker(prefilter), prefilter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPrefilterChecker:
    def test_returns_check_result(self):
        checker, _ = _make_checker()
        result = checker.check(_make_snapshot(), 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert isinstance(result, CheckResult)
        assert isinstance(result.passed, bool)

    def test_passed_true_when_prefilter_passes(self):
        checker, pf = _make_checker()
        pf.check.return_value = _make_prefilter_result(should_skip=False)
        result = checker.check(_make_snapshot(), 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.passed is True

    def test_passed_false_when_prefilter_skips(self):
        checker, pf = _make_checker()
        pf.check.return_value = _make_prefilter_result(should_skip=True, reason="spread too wide")
        result = checker.check(_make_snapshot(), 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.passed is False

    def test_rr_values_computed(self):
        checker, _ = _make_checker()
        snapshot = _make_snapshot(up_ask=0.50, down_ask=0.40)
        result = checker.check(snapshot, 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.snapshot.rr_up == pytest.approx(1.0)
        assert result.snapshot.rr_down == pytest.approx(1.5)

    def test_btc_move_computed(self):
        checker, _ = _make_checker()
        snapshot = _make_snapshot(btc_price=65100.0)
        result = checker.check(snapshot, 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.snapshot.btc_move_from_open == pytest.approx(100.0)

    def test_btc_move_zero_when_no_candle_open(self):
        checker, _ = _make_checker()
        snapshot = _make_snapshot(btc_price=65100.0)
        result = checker.check(snapshot, 120.0, has_open_position=False, candle_open_btc=None)
        assert result.snapshot.btc_move_from_open == 0.0

    def test_checks_populated_on_skip(self):
        checker, pf = _make_checker()
        pf.check.return_value = _make_prefilter_result(should_skip=True, reason="spread too wide")
        result = checker.check(_make_snapshot(), 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.snapshot.checks["prefilter_passed"] is False
        assert result.snapshot.checks["spread_ok"] is False
        assert result.snapshot.checks["time_ok"] is True
        assert result.snapshot.reasons == ["spread too wide"]

    def test_all_checks_pass(self):
        checker, pf = _make_checker()
        pf.check.return_value = _make_prefilter_result(should_skip=False)
        result = checker.check(_make_snapshot(), 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.snapshot.checks["prefilter_passed"] is True
        assert result.snapshot.checks["spread_ok"] is True
        assert result.snapshot.checks["depth_ok"] is True
        assert result.snapshot.checks["choppy_ok"] is True
        assert result.snapshot.checks["setup_ok"] is True

    def test_streak_propagated(self):
        checker, pf = _make_checker()
        pf.check.return_value = _make_prefilter_result(streak=5, direction="up")
        result = checker.check(_make_snapshot(), 120.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.snapshot.streak == 5
        assert result.snapshot.streak_direction == "up"

    def test_time_ok_false_below_45(self):
        checker, _ = _make_checker()
        result = checker.check(_make_snapshot(), 30.0, has_open_position=False, candle_open_btc=65000.0)
        assert result.snapshot.checks["time_ok"] is False

    def test_has_open_position_forwarded(self):
        checker, pf = _make_checker()
        checker.check(_make_snapshot(), 120.0, has_open_position=True, candle_open_btc=65000.0)
        _, kwargs = pf.check.call_args
        # PreFilter.check receives has_open_position as positional arg 3
        args = pf.check.call_args[0]
        assert args[2] is True  # has_open_position
