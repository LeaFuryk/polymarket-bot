"""Tests for the knowledge package — constants, scorecard, observation management, feedback context."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from polybot.knowledge.constants import (
    CACHE_TTL_SECONDS,
    CHEAP_SIDE_THRESHOLD,
    DRAWDOWN_ALERT_THRESHOLD,
    EXPENSIVE_SIDE_THRESHOLD,
    LOSING_STREAK_THRESHOLD,
    MAX_NEW_OBSERVATIONS,
    MIN_TRAILING_TRADES,
    PNL_THRESHOLD,
    RECENT_RESOLUTIONS_WINDOW,
    REFLECTION_MAX_TOKENS,
    REFLECTION_TEMPERATURE,
    SESSION_HISTORY_MAX_ROWS,
)
from polybot.knowledge.manager import KnowledgeManager
from polybot.knowledge.scorecard import compute_scorecard, format_scorecard
from polybot.models import (
    Observation,
    ObservationCategory,
    Scorecard,
    ScorecardDelta,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resolution(**kwargs):
    m = MagicMock()
    m.slug = kwargs.get("slug", "btc-updown-5m-001")
    m.winner = kwargs.get("winner", "up")
    m.btc_open = kwargs.get("btc_open", 85000.0)
    m.btc_close = kwargs.get("btc_close", 85100.0)
    m.total_pnl = kwargs.get("total_pnl", 0.50)
    return m


def _make_trade(**kwargs):
    m = MagicMock()
    m.action.value = kwargs.get("action", "BUY")
    m.token_side.value = kwargs.get("token_side", "up")
    m.fill_price = kwargs.get("fill_price", 0.45)
    m.confidence = kwargs.get("confidence", 0.70)
    m.reasoning = kwargs.get("reasoning", "test trade reasoning text")
    m.candle_slug = kwargs.get("candle_slug", "btc-updown-5m-001")
    m.cycle_number = kwargs.get("cycle_number", 1)
    m.extra = kwargs.get("extra", {})
    return m


def _make_ai_config():
    cfg = MagicMock()
    cfg.api_key = "test-key"
    cfg.model = "claude-test"
    cfg.input_cost_per_mtok = 3.0
    cfg.output_cost_per_mtok = 15.0
    return cfg


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_pnl_threshold_positive(self):
        assert PNL_THRESHOLD > 0
        assert PNL_THRESHOLD < 0.01

    def test_cache_ttl_reasonable(self):
        assert CACHE_TTL_SECONDS > 0

    def test_reflection_settings(self):
        assert REFLECTION_MAX_TOKENS > 0
        assert 0 < REFLECTION_TEMPERATURE < 1

    def test_window_sizes(self):
        assert RECENT_RESOLUTIONS_WINDOW > 0
        assert SESSION_HISTORY_MAX_ROWS > 0
        assert MAX_NEW_OBSERVATIONS > 0
        assert MIN_TRAILING_TRADES > 0

    def test_thresholds_ordering(self):
        assert EXPENSIVE_SIDE_THRESHOLD > CHEAP_SIDE_THRESHOLD
        assert DRAWDOWN_ALERT_THRESHOLD < 0
        assert LOSING_STREAK_THRESHOLD >= 2

    def test_all_constants_importable_from_package(self):
        from polybot.knowledge import (
            CACHE_TTL_SECONDS,
            DEFAULT_OBSERVATION_EXPIRY,
            PNL_THRESHOLD,
            REFLECTION_MAX_TOKENS,
        )

        assert PNL_THRESHOLD > 0
        assert CACHE_TTL_SECONDS > 0
        assert DEFAULT_OBSERVATION_EXPIRY > 0
        assert REFLECTION_MAX_TOKENS > 0


# ---------------------------------------------------------------------------
# Scorecard tests
# ---------------------------------------------------------------------------


class TestComputeScorecard:
    def test_empty_resolutions(self):
        sc = compute_scorecard([], [])
        assert sc.resolutions == 0
        assert sc.win_rate == 0.0

    def test_all_wins(self):
        resolutions = [_make_resolution(total_pnl=0.50), _make_resolution(total_pnl=0.30)]
        trades = [_make_trade()]
        sc = compute_scorecard(resolutions, trades)
        assert sc.resolutions == 2
        assert sc.win_rate == pytest.approx(1.0)
        assert sc.avg_win_size > 0

    def test_all_losses(self):
        resolutions = [_make_resolution(total_pnl=-0.40), _make_resolution(total_pnl=-0.20)]
        trades = [_make_trade()]
        sc = compute_scorecard(resolutions, trades)
        assert sc.win_rate == pytest.approx(0.0)
        assert sc.avg_loss_size < 0

    def test_mixed_results(self):
        resolutions = [
            _make_resolution(total_pnl=0.50),
            _make_resolution(total_pnl=-0.30),
            _make_resolution(total_pnl=0.20),
        ]
        trades = [_make_trade(), _make_trade()]
        sc = compute_scorecard(resolutions, trades)
        assert sc.resolutions == 3
        assert sc.trades_taken == 2
        assert 0 < sc.win_rate < 1.0

    def test_flat_resolutions_count_as_holds(self):
        """Resolutions with tiny PnL are flat/hold — not counted as win or loss."""
        resolutions = [
            _make_resolution(total_pnl=0.0001),  # flat
            _make_resolution(total_pnl=0.50),  # win
        ]
        sc = compute_scorecard(resolutions, [])
        assert sc.win_rate == pytest.approx(1.0)
        assert sc.hold_rate == pytest.approx(0.5)

    def test_holds_not_counted_as_trades(self):
        hold = _make_trade(action="HOLD", fill_price=None)
        buy = _make_trade(action="BUY", fill_price=0.45)
        sc = compute_scorecard([_make_resolution()], [hold, buy])
        assert sc.trades_taken == 1


class TestFormatScorecard:
    def test_first_reflection_no_previous(self):
        sc = Scorecard(resolutions=5, trades_taken=3, win_rate=0.6)
        delta = ScorecardDelta(current=sc, previous=None)
        text = format_scorecard(delta)
        assert "Current Batch" in text
        assert "first reflection" in text
        assert "60%" in text

    def test_with_previous(self):
        current = Scorecard(resolutions=5, trades_taken=3, win_rate=0.8, avg_pnl_per_trade=0.10)
        previous = Scorecard(resolutions=5, trades_taken=4, win_rate=0.6, avg_pnl_per_trade=0.05)
        delta = ScorecardDelta(current=current, previous=previous)
        text = format_scorecard(delta)
        assert "Previous Batch (for comparison)" in text
        assert "80%" in text


# ---------------------------------------------------------------------------
# KnowledgeManager construction + state
# ---------------------------------------------------------------------------


class TestKnowledgeManagerInit:
    @patch("polybot.knowledge.manager.anthropic")
    def test_creates_directory(self, mock_anthropic, tmp_path: Path):
        kdir = tmp_path / "knowledge_test"
        KnowledgeManager(str(kdir), _make_ai_config())
        assert kdir.exists()

    @patch("polybot.knowledge.manager.anthropic")
    def test_injectable_logger(self, mock_anthropic, tmp_path: Path):
        custom_logger = logging.getLogger("test.knowledge")
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config(), logger=custom_logger)
        assert km._logger is custom_logger

    @patch("polybot.knowledge.manager.anthropic")
    def test_save_load_state(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km._total_resolutions = 42
        km._previous_scorecard = Scorecard(resolutions=10, win_rate=0.7)

        state = km.save_state()
        assert state["total_resolutions"] == 42
        assert state["previous_scorecard"] is not None

        # Load into fresh manager
        km2 = KnowledgeManager(str(tmp_path / "k2"), _make_ai_config())
        km2.load_state(state)
        assert km2._total_resolutions == 42
        assert km2._previous_scorecard is not None
        assert km2._previous_scorecard.win_rate == pytest.approx(0.7)

    @patch("polybot.knowledge.manager.anthropic")
    def test_load_state_empty(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km.load_state({})
        assert km._total_resolutions == 0
        assert km._previous_scorecard is None


# ---------------------------------------------------------------------------
# Observation management tests
# ---------------------------------------------------------------------------


class TestObservations:
    @patch("polybot.knowledge.manager.anthropic")
    def test_load_empty(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        assert km.load_active_observations() == []

    @patch("polybot.knowledge.manager.anthropic")
    def test_append_and_load(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km._total_resolutions = 10

        obs = Observation(
            category=ObservationCategory.PATTERN,
            text="test observation",
            based_on_resolutions=5,
            resolution_count_at_creation=10,
            expires_after_resolutions=30,
        )
        km._append_observation(obs)

        active = km.load_active_observations()
        assert len(active) == 1
        assert active[0].text == "test observation"

    @patch("polybot.knowledge.manager.anthropic")
    def test_expired_observations_filtered(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km._total_resolutions = 100

        obs = Observation(
            category=ObservationCategory.EDGE,
            text="old observation",
            based_on_resolutions=5,
            resolution_count_at_creation=10,
            expires_after_resolutions=30,
        )
        km._append_observation(obs)

        # With total_resolutions=100, age=90 > expiry=30 → filtered out
        active = km.load_active_observations()
        assert len(active) == 0

    @patch("polybot.knowledge.manager.anthropic")
    def test_expire_by_id(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km._total_resolutions = 10

        obs1 = Observation(
            category=ObservationCategory.PATTERN,
            text="keep me",
            based_on_resolutions=5,
            resolution_count_at_creation=10,
            expires_after_resolutions=100,
        )
        obs2 = Observation(
            category=ObservationCategory.BIAS,
            text="remove me",
            based_on_resolutions=5,
            resolution_count_at_creation=10,
            expires_after_resolutions=100,
        )
        km._append_observation(obs1)
        km._append_observation(obs2)

        km._expire_observations([obs2.id])
        active = km.load_active_observations()
        assert len(active) == 1
        assert active[0].text == "keep me"

    @patch("polybot.knowledge.manager.anthropic")
    def test_compact_observations(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km._total_resolutions = 50

        # Write one fresh, one expired directly
        fresh = Observation(
            category=ObservationCategory.REGIME,
            text="fresh",
            based_on_resolutions=5,
            resolution_count_at_creation=45,
            expires_after_resolutions=30,
        )
        expired = Observation(
            category=ObservationCategory.PATTERN,
            text="expired",
            based_on_resolutions=5,
            resolution_count_at_creation=5,
            expires_after_resolutions=10,
        )
        km._append_observation(fresh)
        km._append_observation(expired)

        km._compact_observations()
        active = km.load_active_observations()
        assert len(active) == 1
        assert active[0].text == "fresh"


# ---------------------------------------------------------------------------
# Base knowledge cache tests
# ---------------------------------------------------------------------------


class TestBaseKnowledge:
    @patch("polybot.knowledge.manager.anthropic")
    def test_load_base_knowledge_no_files(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        result = km._load_base_knowledge()
        assert result == ""

    @patch("polybot.knowledge.manager.anthropic")
    def test_load_base_knowledge_with_files(self, mock_anthropic, tmp_path: Path):
        kdir = tmp_path / "k"
        kdir.mkdir()
        (kdir / "trading_patterns.md").write_text("# Patterns\nBuy low sell high")
        (kdir / "self_assessment.md").write_text("# Assessment\nDoing well")

        km = KnowledgeManager(str(kdir), _make_ai_config())
        result = km._load_base_knowledge()
        assert "Patterns" in result
        assert "Assessment" in result
        assert "---" in result

    @patch("polybot.knowledge.manager.anthropic")
    def test_cache_is_used(self, mock_anthropic, tmp_path: Path):
        kdir = tmp_path / "k"
        kdir.mkdir()
        (kdir / "trading_patterns.md").write_text("# Patterns")

        km = KnowledgeManager(str(kdir), _make_ai_config())
        first = km._load_base_knowledge()
        # Modify file — should still return cached value
        (kdir / "trading_patterns.md").write_text("# MODIFIED")
        second = km._load_base_knowledge()
        assert first == second


# ---------------------------------------------------------------------------
# Session history tests
# ---------------------------------------------------------------------------


class TestSessionHistory:
    @patch("polybot.knowledge.manager.anthropic")
    def test_append_creates_file(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km._append_session_history("Test session summary")
        assert km._session_history_path.exists()
        content = km._session_history_path.read_text()
        assert "Test session summary" in content
        assert "Session History" in content

    @patch("polybot.knowledge.manager.anthropic")
    def test_max_rows_enforced(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        for i in range(SESSION_HISTORY_MAX_ROWS + 5):
            km._append_session_history(f"Entry {i}")
        content = km._session_history_path.read_text()
        rows = [
            line
            for line in content.strip().split("\n")
            if line.startswith("|") and "Date" not in line and "---" not in line
        ]
        assert len(rows) == SESSION_HISTORY_MAX_ROWS


# ---------------------------------------------------------------------------
# Feedback context tests
# ---------------------------------------------------------------------------


class TestBuildFeedbackContext:
    @patch("polybot.knowledge.manager.anthropic")
    def test_basic_context(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        ctx = km.build_feedback_context([], 3, 2, 1.50)
        assert "3W/2L" in ctx
        assert "60%" in ctx

    @patch("polybot.knowledge.manager.anthropic")
    def test_drawdown_alert(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        resolutions = [_make_resolution(total_pnl=-1.0) for _ in range(10)]
        ctx = km.build_feedback_context(resolutions, 0, 10, -10.0)
        assert "DRAWDOWN ALERT" in ctx

    @patch("polybot.knowledge.manager.anthropic")
    def test_no_drawdown_alert_when_positive(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        resolutions = [_make_resolution(total_pnl=0.50) for _ in range(5)]
        ctx = km.build_feedback_context(resolutions, 5, 0, 2.50)
        assert "DRAWDOWN ALERT" not in ctx

    @patch("polybot.knowledge.manager.anthropic")
    def test_includes_resolutions_table(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        resolutions = [_make_resolution(slug="btc-test-slug-001")]
        ctx = km.build_feedback_context(resolutions, 1, 0, 0.50)
        assert "Recent resolutions:" in ctx
        assert "test-slug-001" in ctx

    @patch("polybot.knowledge.manager.anthropic")
    def test_includes_calibration(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        ctx = km.build_feedback_context([], 0, 0, 0.0, calibration_summary="Cal: 70% accurate")
        assert "Cal: 70% accurate" in ctx

    @patch("polybot.knowledge.manager.anthropic")
    def test_includes_base_knowledge(self, mock_anthropic, tmp_path: Path):
        kdir = tmp_path / "k"
        kdir.mkdir()
        (kdir / "trading_patterns.md").write_text("# Key Patterns")
        km = KnowledgeManager(str(kdir), _make_ai_config())
        ctx = km.build_feedback_context([], 0, 0, 0.0)
        assert "Strategy & Bias Notes" in ctx
        assert "Key Patterns" in ctx

    @patch("polybot.knowledge.manager.anthropic")
    def test_includes_observations(self, mock_anthropic, tmp_path: Path):
        km = KnowledgeManager(str(tmp_path / "k"), _make_ai_config())
        km._total_resolutions = 10
        obs = Observation(
            category=ObservationCategory.EDGE,
            text="momentum working well",
            based_on_resolutions=5,
            resolution_count_at_creation=5,
            expires_after_resolutions=30,
        )
        km._append_observation(obs)
        ctx = km.build_feedback_context([], 0, 0, 0.0)
        assert "momentum working well" in ctx
        assert "Recent Observations" in ctx


# ---------------------------------------------------------------------------
# Re-export tests
# ---------------------------------------------------------------------------


class TestReExports:
    def test_manager_importable(self):
        from polybot.knowledge import KnowledgeManager

        assert KnowledgeManager is not None

    def test_scorecard_functions_importable(self):
        from polybot.knowledge import compute_scorecard, format_scorecard

        assert callable(compute_scorecard)
        assert callable(format_scorecard)

    def test_constants_importable(self):
        from polybot.knowledge import (
            CACHE_TTL_SECONDS,
            PNL_THRESHOLD,
            REFLECTION_PROMPT,
        )

        assert PNL_THRESHOLD > 0
        assert CACHE_TTL_SECONDS > 0
        assert "observations" in REFLECTION_PROMPT
