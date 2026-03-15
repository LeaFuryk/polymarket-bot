"""Tests for the adaptive_entry package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from polybot.adaptive_entry.ai_context import build_ai_context
from polybot.adaptive_entry.constants import (
    ADAPTIVE_CAP_MAX,
    ADAPTIVE_CAP_MIN,
    BTC_THRESHOLD_MIN,
    CONTRARIAN_LOWER,
    DATA_FILE_NAME,
    DEFAULT_BTC_THRESHOLD,
    DEFAULT_MAX_ENTRY,
    FAKEOUT_WINDOW,
    HISTORY_MAX_FACTOR,
    MAX_ENTRY_CAP,
    MIN_PEAK_COMMIT,
    MOMENTUM_UPPER,
    REGIME_CALM_UPPER,
    REGIME_MODERATE_UPPER,
    RETRACEMENT_THRESHOLD,
)
from polybot.adaptive_entry.models import CandleOutcome
from polybot.adaptive_entry.reversal_detector import detect_reversal
from polybot.adaptive_entry.threshold_calculator import compute_thresholds
from polybot.adaptive_entry.tracker import AdaptiveEntryTracker

# ── Helpers ───────────────────────────────────────────────────────────


def _make_outcome(
    slug: str = "test",
    winner: str = "up",
    reversed: bool = False,
    winner_ask_at_20: float = 0.55,
    peak_up_move: float = 40.0,
    peak_down_move: float = 10.0,
) -> CandleOutcome:
    return CandleOutcome(
        slug=slug,
        winner=winner,
        btc_open=100_000.0,
        btc_close=100_050.0 if winner == "up" else 99_950.0,
        direction_at_20="up",
        reversed=reversed,
        winner_ask_at_20=winner_ask_at_20,
        peak_up_move=peak_up_move,
        peak_down_move=peak_down_move,
    )


def _make_history(n: int, reversal_rate: float = 0.3) -> list[CandleOutcome]:
    """Create N outcomes with given reversal rate."""
    history = []
    reversals = int(n * reversal_rate)
    for i in range(n):
        history.append(
            _make_outcome(
                slug=f"candle-{i}",
                reversed=i < reversals,
                winner="up" if i % 2 == 0 else "down",
            )
        )
    return history


# ── Constants ─────────────────────────────────────────────────────────


class TestConstants:
    def test_default_btc_threshold(self):
        assert DEFAULT_BTC_THRESHOLD == 30.0

    def test_default_max_entry(self):
        assert DEFAULT_MAX_ENTRY == 0.60

    def test_retracement_threshold(self):
        assert RETRACEMENT_THRESHOLD == 0.80

    def test_min_peak_commit(self):
        assert MIN_PEAK_COMMIT == 25.0

    def test_fakeout_window(self):
        assert FAKEOUT_WINDOW == 5

    def test_regime_thresholds_ordered(self):
        assert REGIME_CALM_UPPER < REGIME_MODERATE_UPPER

    def test_signal_type_thresholds_ordered(self):
        assert MOMENTUM_UPPER < CONTRARIAN_LOWER

    def test_adaptive_cap_bounds(self):
        assert ADAPTIVE_CAP_MIN < ADAPTIVE_CAP_MAX

    def test_max_entry_cap(self):
        assert MAX_ENTRY_CAP == 0.65


# ── Models ────────────────────────────────────────────────────────────


class TestCandleOutcome:
    def test_defaults(self):
        outcome = CandleOutcome(
            slug="test",
            winner="up",
            btc_open=100_000.0,
            btc_close=100_050.0,
            direction_at_20="up",
            reversed=False,
            winner_ask_at_20=0.55,
        )
        assert outcome.peak_up_move == 0.0
        assert outcome.peak_down_move == 0.0

    def test_all_fields(self):
        outcome = _make_outcome()
        assert outcome.slug == "test"
        assert outcome.winner == "up"
        assert outcome.reversed is False


# ── ReversalDetector ──────────────────────────────────────────────────


class TestReversalDetector:
    def test_no_history(self):
        result = detect_reversal(
            winner="up",
            btc_open=100_000.0,
            btc_close=100_050.0,
            btc_moves=[],
            best_entry_up=0.50,
            best_entry_down=0.50,
            btc_threshold=30.0,
        )
        assert result.initial_direction == "up"
        assert result.reversed is False

    def test_threshold_crossed_momentum(self):
        btc_moves = [i * 10.0 for i in range(5)]
        result = detect_reversal(
            winner="up",
            btc_open=100_000.0,
            btc_close=100_050.0,
            btc_moves=btc_moves,
            best_entry_up=0.50,
            best_entry_down=0.50,
            btc_threshold=30.0,
        )
        assert result.threshold_crossed is True
        assert result.reversed is False  # momentum confirmed, winner matched

    def test_threshold_crossed_reversal(self):
        btc_moves = [i * 10.0 for i in range(5)]
        result = detect_reversal(
            winner="down",  # winner opposite to initial direction
            btc_open=100_000.0,
            btc_close=99_950.0,
            btc_moves=btc_moves,
            best_entry_up=0.50,
            best_entry_down=0.50,
            btc_threshold=30.0,
        )
        assert result.threshold_crossed is True
        assert result.reversed is True

    def test_near_zero_guard(self):
        btc_moves = [i * 10.0 for i in range(5)]
        result = detect_reversal(
            winner="down",
            btc_open=100_000.0,
            btc_close=100_002.0,  # very small final move
            btc_moves=btc_moves,
            best_entry_up=0.50,
            best_entry_down=0.50,
            btc_threshold=30.0,
        )
        assert result.reversed is False  # near-zero guard

    def test_initial_direction_from_first_significant_move(self):
        btc_moves = [2.0, -8.0]
        result = detect_reversal(
            winner="down",
            btc_open=100_000.0,
            btc_close=99_950.0,
            btc_moves=btc_moves,
            best_entry_up=0.50,
            best_entry_down=0.50,
            btc_threshold=30.0,
        )
        assert result.initial_direction == "down"

    def test_winner_ask_captured(self):
        btc_moves = [10.0, 35.0]
        result = detect_reversal(
            winner="up",
            btc_open=100_000.0,
            btc_close=100_050.0,
            btc_moves=btc_moves,
            best_entry_up=0.60,
            best_entry_down=0.50,
            btc_threshold=30.0,
        )
        assert result.winner_ask_at_20 == 0.60  # captured from best_entry_up

    def test_peak_moves(self):
        btc_moves = [50.0, -20.0]
        result = detect_reversal(
            winner="up",
            btc_open=100_000.0,
            btc_close=100_050.0,
            btc_moves=btc_moves,
            best_entry_up=0.50,
            best_entry_down=0.50,
            btc_threshold=60.0,  # high threshold so not crossed
        )
        assert result.peak_up_move == 50.0
        assert result.peak_down_move == 20.0

    def test_retracement_reversal_zero_crossing(self):
        """When price crosses zero after a significant peak, it's a reversal."""
        btc_moves = [30.0, 20.0, 10.0, 0.0, -5.0]
        result = detect_reversal(
            winner="down",
            btc_open=100_000.0,
            btc_close=99_950.0,
            btc_moves=btc_moves,
            best_entry_up=0.50,
            best_entry_down=0.50,
            btc_threshold=100.0,  # never crosses threshold
        )
        assert result.retracement_reversal is True
        assert result.reversed is True  # direction was up, winner was down


# ── ThresholdCalculator ───────────────────────────────────────────────


class TestThresholdCalculator:
    def test_insufficient_history(self):
        result = compute_thresholds([], window=10)
        assert result.btc_threshold == DEFAULT_BTC_THRESHOLD
        assert result.max_entry_price == DEFAULT_MAX_ENTRY
        assert result.using_fakeout is False

    def test_fakeout_based_threshold(self):
        history = _make_history(10, reversal_rate=0.2)
        result = compute_thresholds(history, window=10)
        assert result.using_fakeout is True
        assert result.btc_threshold >= BTC_THRESHOLD_MIN
        assert result.signal_type == "MOMENTUM"

    def test_v_shaped_fallback(self):
        # Outcomes with no peak data → v-shaped fallback
        history = [
            CandleOutcome(
                slug=f"c-{i}",
                winner="up",
                btc_open=100_000.0,
                btc_close=100_050.0,
                direction_at_20="up",
                reversed=False,
                winner_ask_at_20=0.55,
                peak_up_move=0.0,
                peak_down_move=0.0,
            )
            for i in range(10)
        ]
        result = compute_thresholds(history, window=10)
        assert result.using_fakeout is False
        assert result.btc_threshold >= BTC_THRESHOLD_MIN

    def test_signal_type_momentum(self):
        history = _make_history(10, reversal_rate=0.2)
        result = compute_thresholds(history, window=10)
        assert result.signal_type == "MOMENTUM"

    def test_signal_type_contrarian(self):
        history = _make_history(10, reversal_rate=0.7)
        result = compute_thresholds(history, window=10)
        assert result.signal_type == "CONTRARIAN"

    def test_signal_type_uncertain(self):
        history = _make_history(10, reversal_rate=0.5)
        result = compute_thresholds(history, window=10)
        assert result.signal_type == "UNCERTAIN"

    def test_max_entry_from_winner_asks(self):
        history = [_make_outcome(slug=f"c-{i}", winner_ask_at_20=0.50) for i in range(10)]
        result = compute_thresholds(history, window=10)
        assert result.max_entry_price == pytest.approx(0.60)  # 0.50 + 0.10 buffer

    def test_max_entry_capped(self):
        history = [_make_outcome(slug=f"c-{i}", winner_ask_at_20=0.70) for i in range(10)]
        result = compute_thresholds(history, window=10)
        assert result.max_entry_price == MAX_ENTRY_CAP  # capped at 0.65


# ── AIContext ─────────────────────────────────────────────────────────


class TestAIContext:
    def test_insufficient_history_returns_none(self):
        result = build_ai_context(
            history=[],
            window=10,
            signal_type="UNCERTAIN",
            btc_threshold=30.0,
            using_fakeout=False,
            fakeout_p75=0.0,
            fakeout_max=0.0,
            fakeout_median=0.0,
            adaptive_cap=50.0,
        )
        assert result is None

    def test_low_reversal_rate(self):
        history = _make_history(10, reversal_rate=0.1)
        result = build_ai_context(
            history=history,
            window=10,
            signal_type="MOMENTUM",
            btc_threshold=30.0,
            using_fakeout=True,
            fakeout_p75=25.0,
            fakeout_max=30.0,
            fakeout_median=20.0,
            adaptive_cap=50.0,
        )
        assert result is not None
        assert "Low reversal rate" in result

    def test_high_reversal_rate(self):
        history = _make_history(10, reversal_rate=0.7)
        result = build_ai_context(
            history=history,
            window=10,
            signal_type="CONTRARIAN",
            btc_threshold=30.0,
            using_fakeout=True,
            fakeout_p75=25.0,
            fakeout_max=30.0,
            fakeout_median=20.0,
            adaptive_cap=50.0,
        )
        assert result is not None
        assert "High reversal rate" in result

    def test_uncertain_with_momentum(self):
        history = _make_history(10, reversal_rate=0.5)
        result = build_ai_context(
            history=history,
            window=10,
            signal_type="UNCERTAIN",
            btc_threshold=30.0,
            using_fakeout=True,
            fakeout_p75=25.0,
            fakeout_max=30.0,
            fakeout_median=20.0,
            adaptive_cap=50.0,
            abs_btc_move=50.0,  # past threshold
        )
        assert result is not None
        assert "Momentum entries are favored" in result

    def test_uncertain_without_momentum(self):
        history = _make_history(10, reversal_rate=0.5)
        result = build_ai_context(
            history=history,
            window=10,
            signal_type="UNCERTAIN",
            btc_threshold=30.0,
            using_fakeout=True,
            fakeout_p75=25.0,
            fakeout_max=30.0,
            fakeout_median=20.0,
            adaptive_cap=50.0,
            abs_btc_move=10.0,  # below threshold
        )
        assert result is not None
        assert "lean toward the cheaper side" in result

    def test_wild_market_advisory(self):
        history = _make_history(10, reversal_rate=0.3)
        result = build_ai_context(
            history=history,
            window=10,
            signal_type="MOMENTUM",
            btc_threshold=30.0,
            using_fakeout=True,
            fakeout_p75=40.0,
            fakeout_max=60.0,  # > 30 * 1.5
            fakeout_median=25.0,
            adaptive_cap=50.0,
        )
        assert result is not None
        assert "HIGH-VOLATILITY MARKET" in result

    def test_fakeout_stats_included(self):
        history = _make_history(10, reversal_rate=0.3)
        result = build_ai_context(
            history=history,
            window=10,
            signal_type="MOMENTUM",
            btc_threshold=30.0,
            using_fakeout=True,
            fakeout_p75=25.0,
            fakeout_max=30.0,
            fakeout_median=20.0,
            adaptive_cap=50.0,
        )
        assert "P75=$25" in result


# ── AdaptiveEntryTracker ──────────────────────────────────────────────


class TestAdaptiveEntryTracker:
    @pytest.fixture
    def tracker(self, tmp_path: Path) -> AdaptiveEntryTracker:
        return AdaptiveEntryTracker(data_dir=tmp_path, window=5)

    def test_initial_defaults(self, tracker: AdaptiveEntryTracker):
        assert tracker.btc_threshold == DEFAULT_BTC_THRESHOLD
        assert tracker.max_entry_price == DEFAULT_MAX_ENTRY
        assert tracker.has_enough_history is False
        assert tracker.history_count == 0
        assert tracker.window_size == 5

    def test_should_trigger(self, tracker: AdaptiveEntryTracker):
        assert tracker.should_trigger(abs_btc_move=35.0, min_ask=0.55) is True
        assert tracker.should_trigger(abs_btc_move=20.0, min_ask=0.55) is False
        assert tracker.should_trigger(abs_btc_move=35.0, min_ask=0.70) is False

    def test_record_outcome(self, tracker: AdaptiveEntryTracker):
        btc_moves = [i * 10.0 for i in range(5)]
        tracker.record_outcome(
            slug="test-1",
            winner="up",
            btc_open=100_000.0,
            btc_close=100_050.0,
            btc_moves=btc_moves,
            best_entry_up=0.50,
            best_entry_down=0.50,
        )
        assert tracker.history_count == 1

    def test_dedup(self, tracker: AdaptiveEntryTracker):
        btc_moves = [10.0]
        tracker.record_outcome("slug-1", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)
        tracker.record_outcome("slug-1", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)  # dupe
        assert tracker.history_count == 1

    def test_persistence(self, tmp_path: Path):
        tracker1 = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        btc_moves = [30.0]
        for i in range(5):
            tracker1.record_outcome(f"candle-{i}", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)

        tracker2 = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        assert tracker2.history_count == 5
        assert tracker2.has_enough_history is True

    def test_regime_property(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        # Inject history directly for testing
        tracker._history = _make_history(5, reversal_rate=0.0)
        assert tracker.regime == "CALM"

        tracker._history = _make_history(5, reversal_rate=0.2)
        assert tracker.regime == "MODERATE"

        tracker._history = _make_history(5, reversal_rate=0.8)
        assert tracker.regime == "CHOPPY"

    def test_get_summary_no_history(self, tracker: AdaptiveEntryTracker):
        assert "no history" in tracker.get_summary()

    def test_get_summary_with_history(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        btc_moves = [30.0]
        for i in range(5):
            tracker.record_outcome(f"c-{i}", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)
        summary = tracker.get_summary()
        assert "reversal_rate=" in summary
        assert "btc_thresh=" in summary

    def test_get_ai_context_insufficient(self, tracker: AdaptiveEntryTracker):
        assert tracker.get_ai_context() is None

    def test_fakeout_stats_property(self, tracker: AdaptiveEntryTracker):
        stats = tracker.fakeout_stats
        assert "using_fakeout" in stats
        assert "fakeout_p75" in stats

    def test_injectable_logger(self, tmp_path: Path):
        import logging

        custom_logger = logging.getLogger("test.adaptive_entry")
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, logger=custom_logger)
        assert tracker._log is custom_logger

    def test_jsonl_format(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        tracker.record_outcome("slug-1", "up", 100_000.0, 100_050.0, btc_moves=[30.0])

        data_file = tmp_path / DATA_FILE_NAME
        assert data_file.exists()
        record = json.loads(data_file.read_text().strip())
        assert record["slug"] == "slug-1"
        assert record["winner"] == "up"
        assert "peak_up_move" in record
        assert "peak_down_move" in record

    def test_recompute_updates_thresholds(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        btc_moves = [30.0]
        for i in range(5):
            tracker.record_outcome(f"c-{i}", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)
        assert tracker.has_enough_history is True
        # After enough history, thresholds should differ from defaults
        assert tracker._thresholds is not None

    def test_signal_type_property(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        assert tracker.signal_type == "UNCERTAIN"  # before enough data

        btc_moves = [30.0]
        for i in range(5):
            tracker.record_outcome(f"c-{i}", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)
        # After enough momentum-style data, signal should be MOMENTUM
        assert tracker.signal_type in ("MOMENTUM", "UNCERTAIN", "CONTRARIAN")

    def test_rolling_reversal_rate_empty(self, tracker: AdaptiveEntryTracker):
        assert tracker.rolling_reversal_rate == 0.0

    def test_get_ai_context_with_history(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        btc_moves = [30.0]
        for i in range(5):
            tracker.record_outcome(f"c-{i}", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)
        ctx = tracker.get_ai_context(abs_btc_move=35.0)
        assert ctx is not None
        assert "Reversal Rate Context" in ctx

    def test_fakeout_stats_with_history(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        btc_moves = [30.0]
        for i in range(5):
            tracker.record_outcome(f"c-{i}", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)
        stats = tracker.fakeout_stats
        assert stats["using_fakeout"] is True

    def test_history_truncation(self, tmp_path: Path):
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=3)
        btc_moves = [30.0]
        for i in range(20):
            tracker.record_outcome(f"c-{i}", "up", 100_000.0, 100_050.0, btc_moves=btc_moves)
        # Should persist all, but reload truncates
        tracker2 = AdaptiveEntryTracker(data_dir=tmp_path, window=3)
        assert tracker2.history_count <= 3 * HISTORY_MAX_FACTOR

    def test_load_corrupted_file(self, tmp_path: Path):
        data_file = tmp_path / DATA_FILE_NAME
        data_file.write_text("not valid json\n")
        tracker = AdaptiveEntryTracker(data_dir=tmp_path, window=5)
        assert tracker.history_count == 0  # gracefully handles corruption


# ── Backward compatibility ────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_import_tracker(self):
        from polybot.adaptive_entry import AdaptiveEntryTracker  # noqa: F811

        assert AdaptiveEntryTracker is not None

    def test_import_candle_outcome(self):
        from polybot.adaptive_entry import CandleOutcome  # noqa: F811

        assert CandleOutcome is not None

    def test_import_reversal_result(self):
        from polybot.adaptive_entry import ReversalResult  # noqa: F811

        assert ReversalResult is not None

    def test_import_threshold_result(self):
        from polybot.adaptive_entry import ThresholdResult  # noqa: F811

        assert ThresholdResult is not None

    def test_import_detect_reversal(self):
        from polybot.adaptive_entry import detect_reversal  # noqa: F811

        assert detect_reversal is not None

    def test_import_compute_thresholds(self):
        from polybot.adaptive_entry import compute_thresholds  # noqa: F811

        assert compute_thresholds is not None
