"""Tests for tasks/context_builder.py — pure context-building helpers."""

from __future__ import annotations

from polybot.tasks.context_builder import (
    append_section,
    build_chainlink_warning,
    build_counter_trend_advisory,
    build_stop_loss_warning,
    format_ml_line,
)

# ---------------------------------------------------------------------------
# append_section
# ---------------------------------------------------------------------------


class TestAppendSection:
    def test_appends_to_base(self):
        result = append_section("base", "extra")
        assert result == "base\n\nextra"

    def test_returns_base_when_section_none(self):
        assert append_section("base", None) == "base"

    def test_returns_base_when_section_empty(self):
        assert append_section("base", "") == "base"

    def test_returns_section_when_base_empty(self):
        assert append_section("", "extra") == "extra"


# ---------------------------------------------------------------------------
# format_ml_line
# ---------------------------------------------------------------------------


class TestFormatMlLine:
    def test_trained_model(self):
        result = format_ml_line(
            model_trained=True,
            up_probability=0.72,
            confidence="high",
            feature_contributions={"momentum": 0.5, "volume": -0.3, "spread": 0.1},
        )
        assert "72% UP probability" in result
        assert "high" in result
        assert "momentum" in result

    def test_trained_model_top_3(self):
        contribs = {f"feat_{i}": float(i) for i in range(5)}
        result = format_ml_line(
            model_trained=True,
            up_probability=0.6,
            confidence="medium",
            feature_contributions=contribs,
        )
        # Top 3 by abs value should be feat_4, feat_3, feat_2
        assert "feat_4" in result
        assert "feat_3" in result

    def test_untrained_model(self):
        result = format_ml_line(
            model_trained=False,
            scorer_summary="collecting data (15/50 samples)",
        )
        assert "collecting data" in result

    def test_no_contributions(self):
        result = format_ml_line(
            model_trained=True,
            up_probability=0.5,
            confidence="neutral",
            feature_contributions=None,
        )
        assert "ML Baseline" in result


# ---------------------------------------------------------------------------
# build_chainlink_warning
# ---------------------------------------------------------------------------


class TestBuildChainlinkWarning:
    def test_returns_none_below_threshold(self):
        assert build_chainlink_warning(50.0) is None
        assert build_chainlink_warning(-80.0) is None

    def test_returns_none_at_threshold(self):
        assert build_chainlink_warning(100.0) is None

    def test_returns_warning_above_threshold(self):
        result = build_chainlink_warning(150.0)
        assert result is not None
        assert "CHAINLINK DIVERGENCE" in result
        assert "+150" in result

    def test_negative_divergence(self):
        result = build_chainlink_warning(-200.0)
        assert result is not None
        assert "-200" in result


# ---------------------------------------------------------------------------
# build_counter_trend_advisory
# ---------------------------------------------------------------------------


class TestBuildCounterTrendAdvisory:
    def test_returns_none_weak_trend(self):
        assert build_counter_trend_advisory(0.1) is None
        assert build_counter_trend_advisory(-0.2) is None

    def test_bullish_trend(self):
        result = build_counter_trend_advisory(0.5)
        assert result is not None
        assert "BULLISH" in result
        assert "DOWN" in result

    def test_bearish_trend(self):
        result = build_counter_trend_advisory(-0.4)
        assert result is not None
        assert "BEARISH" in result
        assert "UP" in result

    def test_exact_threshold(self):
        result = build_counter_trend_advisory(0.3)
        assert result is not None


# ---------------------------------------------------------------------------
# build_stop_loss_warning
# ---------------------------------------------------------------------------


class TestBuildStopLossWarning:
    def test_basic(self):
        result = build_stop_loss_warning("up", -0.15)
        assert "POST-STOP-LOSS" in result
        assert "UP" in result
        assert "-15.0%" in result

    def test_down_side(self):
        result = build_stop_loss_warning("down", -0.08)
        assert "DOWN" in result
