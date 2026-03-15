"""Tests for indicator classes that replaced tasks/prompt_context.py helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from polybot.indicators.catalog.btc_retracement import BtcRetracementIndicator
from polybot.indicators.catalog.btc_trajectory import BtcTrajectoryIndicator
from polybot.indicators.catalog.entry_timing import EntryTimingIndicator
from polybot.indicators.catalog.microstructure import MicrostructureIndicator
from polybot.indicators.context import IndicatorContext
from polybot.models import Action, TokenSide
from polybot.models.core import MarketSnapshot
from polybot.shared_state.candle_microstructure import CandleMicrostructure

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANDLE_OPEN = 65000.0


def _make_ctx(
    moves: list[float],
    *,
    position_side: str = "",
) -> IndicatorContext:
    """Build IndicatorContext with btc_price_history derived from BTC moves."""
    return IndicatorContext(
        snapshot=MarketSnapshot(
            condition_id="test",
            btc_price_history=[CANDLE_OPEN + m for m in moves],
        ),
        candle_open_btc=CANDLE_OPEN,
        position_side=position_side,
    )


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
# BtcTrajectoryIndicator (was compute_btc_trajectory)
# ---------------------------------------------------------------------------


class TestBtcTrajectoryIndicator:
    def test_returns_none_when_insufficient_data(self):
        indicator = BtcTrajectoryIndicator()
        assert indicator.compute(_make_ctx([1.0] * 10)) is None

    def test_returns_result_when_enough_data(self):
        indicator = BtcTrajectoryIndicator()
        result = indicator.compute(_make_ctx([0.0] * 15))
        assert result is not None
        assert result.name == "BTC Trajectory"

    def test_returns_trajectory_result(self):
        indicator = BtcTrajectoryIndicator()
        moves = [float(i) * 2.0 for i in range(30)]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None
        assert result.name == "BTC Trajectory"
        assert "/s" in result.label  # velocity shown

    def test_drawback_shown_when_significant(self):
        indicator = BtcTrajectoryIndicator()
        moves = [0.0] * 15 + [20.0, 18.0, 15.0, 12.0, 10.0]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None
        assert "drawback" in result.label.lower()

    def test_no_drawback_when_small(self):
        indicator = BtcTrajectoryIndicator()
        moves = [float(i) for i in range(20)]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None
        assert "no significant drawback" in result.label.lower()

    def test_negative_moves(self):
        indicator = BtcTrajectoryIndicator()
        moves = [float(-i) * 3.0 for i in range(20)]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None


# ---------------------------------------------------------------------------
# BtcRetracementIndicator (was compute_retracement_context)
# ---------------------------------------------------------------------------


class TestBtcRetracementIndicator:
    def test_returns_none_when_no_position(self):
        indicator = BtcRetracementIndicator()
        moves = [0.0, 10.0, 30.0, 50.0, 40.0, 30.0, 20.0]
        result = indicator.compute(_make_ctx(moves, position_side=""))
        assert result is None

    def test_returns_none_when_insufficient_data(self):
        indicator = BtcRetracementIndicator()
        result = indicator.compute(_make_ctx([1.0] * 3, position_side="up"))
        assert result is None

    def test_up_position_basic(self):
        indicator = BtcRetracementIndicator()
        moves = [0.0, 10.0, 30.0, 50.0, 40.0, 30.0, 20.0]
        result = indicator.compute(_make_ctx(moves, position_side="up"))
        assert result is not None
        assert result.name == "BTC Retracement"
        assert "peak" in result.label.lower()
        assert "retrace" in result.label.lower()

    def test_down_position(self):
        indicator = BtcRetracementIndicator()
        moves = [0.0, -10.0, -30.0, -50.0, -40.0, -30.0, -20.0]
        result = indicator.compute(_make_ctx(moves, position_side="down"))
        assert result is not None
        assert result.name == "BTC Retracement"

    def test_zero_crossing_detected(self):
        indicator = BtcRetracementIndicator()
        # UP position, BTC moved positive then crossed to negative
        moves = [0.0, 10.0, 20.0, 10.0, 0.0, -5.0, -10.0]
        result = indicator.compute(_make_ctx(moves, position_side="up"))
        assert result is not None
        assert "YES" in result.label

    def test_no_zero_crossing(self):
        indicator = BtcRetracementIndicator()
        moves = [0.0, 10.0, 20.0, 15.0, 12.0, 10.0, 8.0]
        result = indicator.compute(_make_ctx(moves, position_side="up"))
        assert result is not None
        assert "NO" in result.label


# ---------------------------------------------------------------------------
# MicrostructureIndicator (was format_microstructure)
# ---------------------------------------------------------------------------


class TestMicrostructureIndicator:
    def _make_micro_ctx(self, history: list) -> IndicatorContext:
        return IndicatorContext(
            snapshot=MarketSnapshot(condition_id="test"),
            microstructure_history=tuple(
                CandleMicrostructure(
                    avg_spread_up=h.avg_spread_up,
                    avg_spread_down=h.avg_spread_down,
                    btc_range=h.btc_range,
                )
                for h in history
            ),
        )

    def test_returns_none_for_single_candle(self):
        indicator = MicrostructureIndicator()
        assert indicator.compute(self._make_micro_ctx([_FakeMicro()])) is None

    def test_returns_none_for_empty(self):
        indicator = MicrostructureIndicator()
        assert indicator.compute(self._make_micro_ctx([])) is None

    def test_basic_output(self):
        indicator = MicrostructureIndicator()
        history = [_FakeMicro(0.02, 0.03, 90), _FakeMicro(0.025, 0.035, 110)]
        result = indicator.compute(self._make_micro_ctx(history))
        assert result is not None
        assert result.name == "Cross-Candle Microstructure"
        assert "spread" in result.label.lower() or "Spread" in result.label

    def test_spread_widening(self):
        indicator = MicrostructureIndicator()
        history = [_FakeMicro(0.01, 0.01, 100), _FakeMicro(0.02, 0.02, 100)]
        result = indicator.compute(self._make_micro_ctx(history))
        assert result is not None
        assert "widening" in result.label

    def test_spread_narrowing(self):
        indicator = MicrostructureIndicator()
        history = [_FakeMicro(0.03, 0.03, 100), _FakeMicro(0.01, 0.01, 100)]
        result = indicator.compute(self._make_micro_ctx(history))
        assert result is not None
        assert "narrowing" in result.label

    def test_range_direction(self):
        indicator = MicrostructureIndicator()
        history = [
            _FakeMicro(0.02, 0.02, 50),
            _FakeMicro(0.02, 0.02, 50),
            _FakeMicro(0.02, 0.02, 200),
        ]
        result = indicator.compute(self._make_micro_ctx(history))
        assert result is not None
        assert "increasing" in result.label


# ---------------------------------------------------------------------------
# EntryTimingIndicator (was compute_entry_timing_stats)
# ---------------------------------------------------------------------------


class TestEntryTimingIndicator:
    def _make_timing_ctx(
        self,
        trades: list,
        resolutions: list,
    ) -> IndicatorContext:
        return IndicatorContext(
            snapshot=MarketSnapshot(condition_id="test"),
            session_trades=tuple(trades),
            session_resolutions=tuple(resolutions),
        )

    def test_returns_none_for_few_trades(self):
        indicator = EntryTimingIndicator()
        trades = [_FakeTrade(), _FakeTrade()]
        resolutions = [_FakeResolution()]
        assert indicator.compute(self._make_timing_ctx(trades, resolutions)) is None

    def test_returns_none_for_no_resolutions(self):
        indicator = EntryTimingIndicator()
        trades = [_FakeTrade() for _ in range(5)]
        assert indicator.compute(self._make_timing_ctx(trades, [])) is None

    def test_basic_output_with_wins(self):
        indicator = EntryTimingIndicator()
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
        result = indicator.compute(self._make_timing_ctx(trades, resolutions))
        assert result is not None
        assert result.name == "Entry Timing"
        assert "3W" in result.label or "W/" in result.label

    def test_mixed_wins_and_losses(self):
        indicator = EntryTimingIndicator()
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
        result = indicator.compute(self._make_timing_ctx(trades, resolutions))
        assert result is not None
        assert "1W/" in result.label

    def test_hold_trades_excluded(self):
        indicator = EntryTimingIndicator()
        trades = [
            _FakeTrade(action=Action.HOLD, candle_slug="s1"),
            _FakeTrade(action=Action.HOLD, candle_slug="s2"),
            _FakeTrade(action=Action.HOLD, candle_slug="s3"),
        ]
        resolutions = [_FakeResolution(slug="s1")]
        assert indicator.compute(self._make_timing_ctx(trades, resolutions)) is None

    def test_sell_trades_excluded(self):
        indicator = EntryTimingIndicator()
        trades = [
            _FakeTrade(action=Action.SELL, candle_slug="s1"),
            _FakeTrade(action=Action.SELL, candle_slug="s2"),
            _FakeTrade(action=Action.SELL, candle_slug="s3"),
        ]
        resolutions = [_FakeResolution(slug="s1")]
        assert indicator.compute(self._make_timing_ctx(trades, resolutions)) is None

    def test_best_bucket_shown(self):
        indicator = EntryTimingIndicator()
        trades = [_FakeTrade(candle_slug=f"s{i}", extra={"time_remaining": 220}) for i in range(4)]
        resolutions = [_FakeResolution(slug=f"s{i}", winner="up") for i in range(4)]
        result = indicator.compute(self._make_timing_ctx(trades, resolutions))
        assert result is not None
        assert "best" in result.label.lower()
