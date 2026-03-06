"""Tests for the calibration module."""

from __future__ import annotations

import logging

import pytest

from polybot.calibration.constants import (
    BIN_WIDTH,
    CONFIDENCE_PRECISION,
    DATA_FILE_NAME,
    DEFAULT_BREAK_EVEN,
    DEFAULT_CONFIDENCE,
    MIN_SAMPLES,
)
from polybot.calibration.tracker import CalibrationBin, CalibrationResult, ConfidenceCalibrator

# ── Constants ──────────────────────────────────────────────────────────


class TestConstants:
    def test_bin_width(self):
        assert BIN_WIDTH == 0.10

    def test_min_samples(self):
        assert MIN_SAMPLES == 10

    def test_default_break_even(self):
        assert DEFAULT_BREAK_EVEN == 0.55

    def test_data_file_name(self):
        assert DATA_FILE_NAME == "calibration_data.jsonl"

    def test_default_confidence(self):
        assert DEFAULT_CONFIDENCE == 0.5

    def test_confidence_precision(self):
        assert CONFIDENCE_PRECISION == 4


# ── CalibrationBin ─────────────────────────────────────────────────────


class TestCalibrationBin:
    def test_empty_bin(self):
        b = CalibrationBin(bin_lower=0.5, bin_upper=0.6)
        assert b.total == 0
        assert b.win_rate == 0.0
        assert not b.is_reliable

    def test_win_rate(self):
        b = CalibrationBin(bin_lower=0.5, bin_upper=0.6, wins=7, losses=3)
        assert b.total == 10
        assert b.win_rate == 0.7
        assert b.is_reliable

    def test_below_min_samples(self):
        b = CalibrationBin(bin_lower=0.5, bin_upper=0.6, wins=3, losses=2)
        assert b.total == 5
        assert not b.is_reliable

    def test_all_wins(self):
        b = CalibrationBin(bin_lower=0.5, bin_upper=0.6, wins=10, losses=0)
        assert b.win_rate == 1.0

    def test_all_losses(self):
        b = CalibrationBin(bin_lower=0.5, bin_upper=0.6, wins=0, losses=10)
        assert b.win_rate == 0.0


# ── CalibrationResult ──────────────────────────────────────────────────


class TestCalibrationResult:
    def test_fields(self):
        r = CalibrationResult(
            stated_confidence=0.75,
            calibrated_win_rate=0.65,
            sample_count=20,
            is_reliable=True,
            should_trade=True,
            reason="test",
        )
        assert r.stated_confidence == 0.75
        assert r.calibrated_win_rate == 0.65
        assert r.sample_count == 20
        assert r.is_reliable
        assert r.should_trade

    def test_default_reason(self):
        r = CalibrationResult(
            stated_confidence=0.5,
            calibrated_win_rate=0.5,
            sample_count=0,
            is_reliable=False,
            should_trade=True,
        )
        assert r.reason == ""


# ── ConfidenceCalibrator ───────────────────────────────────────────────


class TestConfidenceCalibrator:
    def test_init_creates_bins(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        assert len(cal._bins) == 10  # 0.0 to 0.9 in 0.1 increments

    def test_injectable_logger(self, tmp_path):
        custom_logger = logging.getLogger("test.calibration")
        cal = ConfidenceCalibrator(tmp_path, logger=custom_logger)
        assert cal._logger is custom_logger

    def test_default_logger(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        assert cal._logger.name == "polybot.calibration.tracker"

    def test_bin_key(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        assert cal._bin_key(0.0) == 0.0
        assert cal._bin_key(0.05) == 0.0
        assert cal._bin_key(0.10) == 0.1
        assert cal._bin_key(0.75) == 0.7
        assert cal._bin_key(0.99) == 0.9

    def test_register_trade(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_trade("slug1", 0.75, "up", 0.50)
        assert "slug1" in cal._pending
        assert cal._pending["slug1"] == (0.75, "up", 0.50)

    def test_register_shadow_valid(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_shadow("slug1", "up", 0.6)
        assert "slug1" in cal._shadow_pending

    def test_register_shadow_invalid_direction(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_shadow("slug1", "sideways", 0.6)
        assert "slug1" not in cal._shadow_pending

    def test_record_outcome_win(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_trade("slug1", 0.75, "up", 0.50)
        cal.record_outcome("slug1", "up")

        key = cal._bin_key(0.75)
        assert cal._bins[key].wins == 1
        assert cal._bins[key].losses == 0
        assert "slug1" not in cal._pending

    def test_record_outcome_loss(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_trade("slug1", 0.75, "up", 0.50)
        cal.record_outcome("slug1", "down")

        key = cal._bin_key(0.75)
        assert cal._bins[key].wins == 0
        assert cal._bins[key].losses == 1

    def test_record_outcome_shadow_correct(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_shadow("slug1", "up", 0.6)
        cal.record_outcome("slug1", "up")
        assert cal._shadow_correct == 1
        assert cal._shadow_total == 1

    def test_record_outcome_shadow_wrong(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_shadow("slug1", "up", 0.6)
        cal.record_outcome("slug1", "down")
        assert cal._shadow_correct == 0
        assert cal._shadow_total == 1

    def test_record_outcome_unknown_slug(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        # Should not raise
        cal.record_outcome("unknown", "up")

    def test_save_and_load(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal.register_trade("s1", 0.75, "up", 0.50)
        cal.record_outcome("s1", "up")

        # Create new instance — should load persisted data
        cal2 = ConfidenceCalibrator(tmp_path)
        key = cal2._bin_key(0.75)
        assert cal2._bins[key].wins == 1
        assert cal2.total_records == 1

    def test_load_empty_file(self, tmp_path):
        (tmp_path / DATA_FILE_NAME).write_text("")
        cal = ConfidenceCalibrator(tmp_path)
        assert cal.total_records == 0

    def test_load_corrupt_file(self, tmp_path):
        (tmp_path / DATA_FILE_NAME).write_text("not json\n")
        # Should not raise, just log warning
        cal = ConfidenceCalibrator(tmp_path)
        assert cal.total_records == 0

    def test_check_unreliable(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        result = cal.check(0.75)
        assert not result.is_reliable
        assert result.should_trade  # allow when uncalibrated
        assert result.calibrated_win_rate == 0.75  # use stated as fallback

    def test_check_reliable_should_trade(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        key = cal._bin_key(0.75)
        cal._bins[key].wins = 8
        cal._bins[key].losses = 2  # 80% win rate

        result = cal.check(0.75)
        assert result.is_reliable
        assert result.should_trade
        assert result.calibrated_win_rate == 0.8

    def test_check_reliable_should_not_trade(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        key = cal._bin_key(0.75)
        cal._bins[key].wins = 3
        cal._bins[key].losses = 7  # 30% win rate, below break-even

        result = cal.check(0.75)
        assert result.is_reliable
        assert not result.should_trade
        assert result.calibrated_win_rate == pytest.approx(0.3)

    def test_check_custom_break_even(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path, break_even=0.80)
        key = cal._bin_key(0.75)
        cal._bins[key].wins = 7
        cal._bins[key].losses = 3  # 70% — below 80% break-even

        result = cal.check(0.75)
        assert result.is_reliable
        assert not result.should_trade


class TestCalibrationSummary:
    def test_empty_summary(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        assert cal.get_calibration_summary() == "No calibration data yet."

    def test_summary_with_data(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        key = cal._bin_key(0.75)
        cal._bins[key].wins = 3
        cal._bins[key].losses = 2

        summary = cal.get_calibration_summary()
        assert "0.70-0.80" in summary
        assert "60% win rate" in summary
        assert "insufficient data" in summary

    def test_summary_overconfident(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        key = cal._bin_key(0.75)
        # 40% win rate but stated 70-80% confidence → overconfident
        cal._bins[key].wins = 4
        cal._bins[key].losses = 6

        summary = cal.get_calibration_summary()
        assert "OVERCONFIDENT" in summary

    def test_summary_with_shadow(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        cal._shadow_correct = 7
        cal._shadow_total = 10

        summary = cal.get_calibration_summary()
        assert "Shadow Predictions" in summary
        assert "7/10" in summary
        assert "70%" in summary

    def test_total_records(self, tmp_path):
        cal = ConfidenceCalibrator(tmp_path)
        assert cal.total_records == 0

        key = cal._bin_key(0.75)
        cal._bins[key].wins = 5
        cal._bins[key].losses = 3
        assert cal.total_records == 8


# ── __init__.py re-exports ─────────────────────────────────────────────


class TestReExports:
    def test_calibrator_reexported(self):
        from polybot.calibration import ConfidenceCalibrator

        assert ConfidenceCalibrator is not None

    def test_bin_reexported(self):
        from polybot.calibration import CalibrationBin

        assert CalibrationBin is not None

    def test_result_reexported(self):
        from polybot.calibration import CalibrationResult

        assert CalibrationResult is not None

    def test_constants_reexported(self):
        from polybot.calibration import BIN_WIDTH, DEFAULT_BREAK_EVEN, MIN_SAMPLES

        assert BIN_WIDTH == 0.10
        assert MIN_SAMPLES == 10
        assert DEFAULT_BREAK_EVEN == 0.55
