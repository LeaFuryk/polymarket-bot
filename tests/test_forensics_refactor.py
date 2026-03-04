"""Tests for forensics refactor: constants, protocol, injectable logger, integration."""

from __future__ import annotations

import logging

from polybot.forensics import (
    ForensicsReport,
    Investigator,
    build_report,
)
from polybot.forensics.blocked import _classify, analyze_blocked
from polybot.forensics.constants import (
    BPS_MULTIPLIER,
    DEFAULT_TTL_GRID,
    ML_MODEL_PATH,
    REPRICE_BUY_MAX_ASK,
    REPRICE_SELL_MIN_BID,
    RISK_CATEGORY_MAP,
)
from polybot.forensics.context import _compute_ml_score, analyze_context
from polybot.forensics.execution import analyze_orders

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_ttl_grid_is_sorted(self):
        assert sorted(DEFAULT_TTL_GRID) == DEFAULT_TTL_GRID

    def test_bps_multiplier(self):
        assert BPS_MULTIPLIER == 10_000

    def test_reprice_thresholds(self):
        assert 0 < REPRICE_SELL_MIN_BID < REPRICE_BUY_MAX_ASK < 1

    def test_risk_category_map_not_empty(self):
        assert len(RISK_CATEGORY_MAP) > 0
        for pattern, category in RISK_CATEGORY_MAP:
            assert isinstance(pattern, str)
            assert isinstance(category, str)

    def test_ml_model_path(self):
        assert ML_MODEL_PATH.endswith(".json")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_runtime_checkable(self):
        """Investigator is runtime-checkable with name + analyze."""

        class DummyInvestigator:
            @property
            def name(self) -> str:
                return "dummy"

            def analyze(self, conn):
                return []

        assert isinstance(DummyInvestigator(), Investigator)

    def test_non_conforming_rejected(self):
        """Objects missing analyze() do not satisfy the protocol."""

        class NotAnInvestigator:
            @property
            def name(self) -> str:
                return "nope"

        assert not isinstance(NotAnInvestigator(), Investigator)


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


class TestClassify:
    def test_unknown_category(self):
        assert _classify("some random reason") == "other"

    def test_case_insensitive(self):
        assert _classify("Kill Switch Active") == "kill_switch"


# ---------------------------------------------------------------------------
# Injectable logger
# ---------------------------------------------------------------------------


class TestInjectableLogger:
    def test_custom_logger_accepted(self, tmp_db, sample_decisions):
        """analyze_orders accepts and uses a custom logger."""
        custom = logging.getLogger("test.forensics")
        metrics, agg = analyze_orders(tmp_db, logger=custom)
        assert agg.total_orders == 3

    def test_context_custom_logger(self, tmp_db, sample_decisions):
        """analyze_context accepts a custom logger."""
        custom = logging.getLogger("test.forensics.context")
        contexts = analyze_context(tmp_db, logger=custom)
        assert len(contexts) >= 3

    def test_blocked_custom_logger(self, tmp_db, sample_decisions):
        """analyze_blocked accepts a custom logger."""
        custom = logging.getLogger("test.forensics.blocked")
        blocked, agg = analyze_blocked(tmp_db, logger=custom)
        assert agg.total_blocked == 1


# ---------------------------------------------------------------------------
# ML scoring
# ---------------------------------------------------------------------------


class TestMLScoring:
    def test_compute_ml_score_basic(self):
        weights = {"intercept": 0.5, "momentum": 2.0, "volume": -1.0}
        indicators = {"momentum": 0.7, "volume": 0.3}
        score = _compute_ml_score(indicators, weights)
        assert abs(score - (0.5 + 2.0 * 0.7 + (-1.0) * 0.3)) < 0.001

    def test_compute_ml_score_missing_weight(self):
        weights = {"intercept": 1.0}
        indicators = {"unknown_indicator": 5.0}
        score = _compute_ml_score(indicators, weights)
        assert score == 1.0  # only intercept, unknown ignored


# ---------------------------------------------------------------------------
# Integration: build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_full_pipeline(self, tmp_db, sample_decisions, sample_snapshots):
        """build_report assembles all 6 analyses into a ForensicsReport."""
        report = build_report(tmp_db, ":memory:")
        assert isinstance(report, ForensicsReport)
        assert report.aggregate_metrics.total_orders == 3
        assert report.blocked_aggregate.total_blocked == 1
        assert len(report.round_trips) == 1
        assert len(report.decision_contexts) >= 3
        assert report.generated_at  # non-empty ISO timestamp

    def test_build_report_with_logger(self, tmp_db, sample_decisions):
        """build_report passes logger through to all sub-analyses."""
        custom = logging.getLogger("test.pipeline")
        report = build_report(tmp_db, ":memory:", logger=custom)
        assert isinstance(report, ForensicsReport)


# ---------------------------------------------------------------------------
# Re-exports
# ---------------------------------------------------------------------------


class TestReExports:
    def test_all_types_importable(self):
        from polybot.forensics import (
            AggregateMetrics,
            BlockedAggregate,
            BlockedOrder,
            CostAggregate,
            CostBreakdown,
            DecisionContext,
            OrderMetrics,
            RoundTrip,
            TTLAggregate,
            TTLCounterfactual,
        )

        assert all(
            t is not None
            for t in [
                AggregateMetrics,
                BlockedAggregate,
                BlockedOrder,
                CostAggregate,
                CostBreakdown,
                DecisionContext,
                OrderMetrics,
                RoundTrip,
                TTLAggregate,
                TTLCounterfactual,
            ]
        )
