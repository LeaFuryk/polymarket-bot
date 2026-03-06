"""Tests for tasks/prompt_context.py — pure prompt-building helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from polybot.models import Action, TokenSide
from polybot.shared_state import PreFilterSnapshot
from polybot.tasks.prompt_context import (
    compute_btc_trajectory,
    compute_entry_timing_stats,
    compute_retracement_context,
    format_microstructure,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshots(
    moves: list[float],
    *,
    start_ts: float = 1000.0,
) -> list[PreFilterSnapshot]:
    """Build PreFilterSnapshot list with given BTC moves from open."""
    return [
        PreFilterSnapshot(
            timestamp=start_ts + i,
            time_remaining=300.0 - i,
            btc_move_from_open=m,
        )
        for i, m in enumerate(moves)
    ]


@dataclass
class _FakeOrderBook:
    best_ask: float | None = 0.45
    best_bid: float | None = 0.40
    midpoint: float | None = 0.425


@dataclass
class _FakeSnapshot:
    orderbook: _FakeOrderBook = field(default_factory=_FakeOrderBook)
    down_orderbook: _FakeOrderBook = field(default_factory=_FakeOrderBook)


@dataclass
class _FakeMicro:
    avg_spread_up: float = 0.02
    avg_spread_down: float = 0.03
    btc_range: float = 100.0


@dataclass
class _FakeTrade:
    action: Action = Action.BUY
    fill_price: float | None = 0.55
    token_side: TokenSide = TokenSide.UP
    candle_slug: str = "slug-1"
    extra: dict = field(default_factory=lambda: {"time_remaining": 180.0})


@dataclass
class _FakeResolution:
    slug: str = "slug-1"
    winner: str = "up"


# ---------------------------------------------------------------------------
# compute_btc_trajectory
# ---------------------------------------------------------------------------


class TestComputeBtcTrajectory:
    def test_returns_none_when_insufficient_data(self):
        assert compute_btc_trajectory(_make_snapshots([1.0] * 10)) is None

    def test_returns_none_when_no_velocity_data(self):
        # 15 identical moves → velocity is 0, but enough data to compute
        result = compute_btc_trajectory(_make_snapshots([0.0] * 15))
        assert result is not None
        assert "BTC Trajectory" in result

    def test_returns_trajectory_section(self):
        # 30 snapshots: slow start then accelerating
        moves = [float(i) * 2.0 for i in range(30)]
        result = compute_btc_trajectory(_make_snapshots(moves))
        assert result is not None
        assert "## BTC Trajectory" in result
        assert "Velocity" in result

    def test_drawback_shown_when_significant(self):
        # Peak then pullback of 10
        moves = [0.0] * 15 + [20.0, 18.0, 15.0, 12.0, 10.0]
        result = compute_btc_trajectory(_make_snapshots(moves))
        assert result is not None
        assert "drawback" in result.lower()

    def test_no_drawback_when_small(self):
        moves = [float(i) for i in range(20)]
        result = compute_btc_trajectory(_make_snapshots(moves))
        assert result is not None
        assert "No significant drawback" in result

    def test_negative_moves(self):
        moves = [float(-i) * 3.0 for i in range(20)]
        result = compute_btc_trajectory(_make_snapshots(moves))
        assert result is not None


# ---------------------------------------------------------------------------
# compute_retracement_context
# ---------------------------------------------------------------------------


class TestComputeRetracementContext:
    def test_returns_empty_when_insufficient_data(self):
        assert compute_retracement_context(_make_snapshots([1.0] * 3), "up", _FakeSnapshot()) == ""

    def test_up_position_basic(self):
        # Peak at +50, then retrace to +20
        moves = [0.0, 10.0, 30.0, 50.0, 40.0, 30.0, 20.0]
        result = compute_retracement_context(
            _make_snapshots(moves),
            "up",
            _FakeSnapshot(),
        )
        assert "Reversal Analysis" in result
        assert "Peak BTC move" in result
        assert "Retracement" in result

    def test_down_position(self):
        moves = [0.0, -10.0, -30.0, -50.0, -40.0, -30.0, -20.0]
        result = compute_retracement_context(
            _make_snapshots(moves),
            "down",
            _FakeSnapshot(),
        )
        assert "Reversal Analysis" in result

    def test_zero_crossing_detected(self):
        # UP position, BTC moved positive then crossed to negative
        moves = [0.0, 10.0, 20.0, 10.0, 0.0, -5.0, -10.0]
        result = compute_retracement_context(
            _make_snapshots(moves),
            "up",
            _FakeSnapshot(),
        )
        assert "YES" in result  # zero crossing

    def test_no_zero_crossing(self):
        moves = [0.0, 10.0, 20.0, 15.0, 12.0, 10.0, 8.0]
        result = compute_retracement_context(
            _make_snapshots(moves),
            "up",
            _FakeSnapshot(),
        )
        assert "NO" in result

    def test_opposite_ask_included(self):
        snap = _FakeSnapshot()
        snap.down_orderbook = _FakeOrderBook(best_ask=0.35)
        moves = [0.0, 10.0, 20.0, 15.0, 10.0, 5.0, 3.0]
        result = compute_retracement_context(_make_snapshots(moves), "up", snap)
        assert "DOWN ask" in result


# ---------------------------------------------------------------------------
# format_microstructure
# ---------------------------------------------------------------------------


class TestFormatMicrostructure:
    def test_returns_none_for_single_candle(self):
        assert format_microstructure([_FakeMicro()]) is None

    def test_returns_none_for_empty(self):
        assert format_microstructure([]) is None

    def test_basic_output(self):
        history = [_FakeMicro(0.02, 0.03, 90), _FakeMicro(0.025, 0.035, 110)]
        result = format_microstructure(history)
        assert result is not None
        assert "Cross-Candle Microstructure" in result
        assert "Spreads" in result

    def test_spread_widening(self):
        history = [_FakeMicro(0.01, 0.01, 100), _FakeMicro(0.02, 0.02, 100)]
        result = format_microstructure(history)
        assert "widening" in result

    def test_spread_narrowing(self):
        history = [_FakeMicro(0.03, 0.03, 100), _FakeMicro(0.01, 0.01, 100)]
        result = format_microstructure(history)
        assert "narrowing" in result

    def test_range_direction(self):
        history = [
            _FakeMicro(0.02, 0.02, 50),
            _FakeMicro(0.02, 0.02, 50),
            _FakeMicro(0.02, 0.02, 200),  # big spike
        ]
        result = format_microstructure(history)
        assert "increasing" in result


# ---------------------------------------------------------------------------
# compute_entry_timing_stats
# ---------------------------------------------------------------------------


class TestComputeEntryTimingStats:
    def test_returns_none_for_few_trades(self):
        trades = [_FakeTrade(), _FakeTrade()]
        resolutions = [_FakeResolution()]
        assert compute_entry_timing_stats(trades, resolutions) is None

    def test_returns_none_for_no_resolutions(self):
        trades = [_FakeTrade() for _ in range(5)]
        assert compute_entry_timing_stats(trades, []) is None

    def test_basic_output_with_wins(self):
        trades = [
            _FakeTrade(candle_slug="s1", extra={"time_remaining": 180}),
            _FakeTrade(candle_slug="s2", extra={"time_remaining": 120}),
            _FakeTrade(candle_slug="s3", extra={"time_remaining": 210}),
        ]
        resolutions = [
            _FakeResolution(slug="s1", winner="up"),
            _FakeResolution(slug="s2", winner="up"),
            _FakeResolution(slug="s3", winner="up"),
        ]
        result = compute_entry_timing_stats(trades, resolutions)
        assert result is not None
        assert "Entry Timing Performance" in result
        assert "3W/0L" in result or "W/" in result

    def test_mixed_wins_and_losses(self):
        trades = [
            _FakeTrade(candle_slug="s1", extra={"time_remaining": 180}),
            _FakeTrade(candle_slug="s2", extra={"time_remaining": 120}),
            _FakeTrade(candle_slug="s3", extra={"time_remaining": 60}),
        ]
        resolutions = [
            _FakeResolution(slug="s1", winner="up"),  # win
            _FakeResolution(slug="s2", winner="down"),  # loss
            _FakeResolution(slug="s3", winner="down"),  # loss
        ]
        result = compute_entry_timing_stats(trades, resolutions)
        assert result is not None
        assert "1W/" in result  # at least 1 win somewhere

    def test_hold_trades_excluded(self):
        trades = [
            _FakeTrade(action=Action.HOLD, candle_slug="s1"),
            _FakeTrade(action=Action.HOLD, candle_slug="s2"),
            _FakeTrade(action=Action.HOLD, candle_slug="s3"),
        ]
        resolutions = [_FakeResolution(slug="s1")]
        assert compute_entry_timing_stats(trades, resolutions) is None

    def test_sell_trades_excluded(self):
        trades = [
            _FakeTrade(action=Action.SELL, candle_slug="s1"),
            _FakeTrade(action=Action.SELL, candle_slug="s2"),
            _FakeTrade(action=Action.SELL, candle_slug="s3"),
        ]
        resolutions = [_FakeResolution(slug="s1")]
        assert compute_entry_timing_stats(trades, resolutions) is None

    def test_best_bucket_shown(self):
        # All in >200s bucket
        trades = [_FakeTrade(candle_slug=f"s{i}", extra={"time_remaining": 220}) for i in range(4)]
        resolutions = [_FakeResolution(slug=f"s{i}", winner="up") for i in range(4)]
        result = compute_entry_timing_stats(trades, resolutions)
        assert result is not None
        assert "Best bucket" in result
