"""Tests for the exit_tracker package — constants, ExitRecord, ExitTracker."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from polybot.exit_tracker.constants import (
    EXIT_ANALYSIS_FILENAME,
    LOST_VALUE,
    PRICE_PRECISION,
    SIZE_PRECISION,
    TIME_PRECISION,
    WON_VALUE,
)
from polybot.exit_tracker.tracker import ExitRecord, ExitTracker

# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_filename(self):
        assert EXIT_ANALYSIS_FILENAME.endswith(".jsonl")

    def test_precision_values(self):
        assert PRICE_PRECISION == 4
        assert SIZE_PRECISION == 2
        assert TIME_PRECISION == 1

    def test_outcome_values(self):
        assert WON_VALUE == 1.0
        assert LOST_VALUE == 0.0

    def test_all_constants_importable_from_package(self):
        from polybot.exit_tracker import (
            EXIT_ANALYSIS_FILENAME,
            LOST_VALUE,
            WON_VALUE,
        )

        assert EXIT_ANALYSIS_FILENAME == "exit_analysis.jsonl"
        assert WON_VALUE == 1.0
        assert LOST_VALUE == 0.0


# ---------------------------------------------------------------------------
# ExitRecord tests
# ---------------------------------------------------------------------------


class TestExitRecord:
    def test_defaults(self):
        r = ExitRecord(
            slug="btc-5m-001",
            token_side="up",
            entry_price=0.55,
            exit_price=0.65,
            exit_size=10.0,
            time_remaining=120.0,
        )
        assert r.winner == ""
        assert r.held_value == 0.0
        assert r.actual_pnl == 0.0
        assert r.missed_pnl == 0.0

    def test_custom_values(self):
        r = ExitRecord(
            slug="btc-5m-002",
            token_side="down",
            entry_price=0.40,
            exit_price=0.60,
            exit_size=5.0,
            time_remaining=60.0,
            winner="down",
            held_value=1.0,
            actual_pnl=1.0,
            missed_pnl=1.0,
        )
        assert r.token_side == "down"
        assert r.winner == "down"
        assert r.held_value == 1.0


# ---------------------------------------------------------------------------
# ExitTracker tests
# ---------------------------------------------------------------------------


class TestExitTrackerInit:
    def test_creates_directory(self, tmp_path: Path):
        data_dir = tmp_path / "sub" / "dir"
        ExitTracker(data_dir)
        assert data_dir.exists()

    def test_injectable_logger(self, tmp_path: Path):
        custom_logger = logging.getLogger("test.exit_tracker")
        tracker = ExitTracker(tmp_path, logger=custom_logger)
        assert tracker._logger is custom_logger

    def test_default_logger(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        assert tracker._logger is not None

    def test_data_path(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        assert tracker._data_path == tmp_path / EXIT_ANALYSIS_FILENAME

    def test_initial_stats(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        assert tracker._total_exits == 0
        assert tracker._exits_better_than_hold == 0
        assert tracker._total_saved == 0.0
        assert tracker._total_missed == 0.0


class TestRegisterExit:
    def test_register_adds_to_pending(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        tracker.register_exit("slug-1", "up", 0.50, 0.60, 10.0, 120.0)
        assert "slug-1" in tracker._pending
        assert len(tracker._pending["slug-1"]) == 1

    def test_register_multiple_same_slug(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        tracker.register_exit("slug-1", "up", 0.50, 0.60, 10.0, 120.0)
        tracker.register_exit("slug-1", "up", 0.55, 0.65, 5.0, 60.0)
        assert len(tracker._pending["slug-1"]) == 2

    def test_register_different_slugs(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        tracker.register_exit("slug-1", "up", 0.50, 0.60, 10.0, 120.0)
        tracker.register_exit("slug-2", "down", 0.40, 0.50, 8.0, 90.0)
        assert len(tracker._pending) == 2


class TestRecordOutcome:
    def test_winning_exit_good(self, tmp_path: Path):
        """Exit from winning side at profit — still a GOOD EXIT if exit PnL >= hold PnL."""
        tracker = ExitTracker(tmp_path)
        # Bought UP at 0.50, sold at 0.90 — UP wins → held_value=1.0
        # actual_pnl = (0.90 - 0.50) * 10 = 4.0
        # held_pnl = (1.0 - 0.50) * 10 = 5.0
        # missed_pnl = 5.0 - 4.0 = 1.0 (positive → missed upside)
        tracker.register_exit("slug-1", "up", 0.50, 0.90, 10.0, 60.0)
        tracker.record_outcome("slug-1", "up")
        assert tracker._total_exits == 1
        assert tracker._total_missed == pytest.approx(1.0)

    def test_losing_side_exit_is_good(self, tmp_path: Path):
        """Exit from losing side — GOOD EXIT (avoided total loss)."""
        tracker = ExitTracker(tmp_path)
        # Bought UP at 0.50, sold at 0.45 — DOWN wins → held_value=0.0
        # actual_pnl = (0.45 - 0.50) * 10 = -0.5
        # held_pnl = (0.0 - 0.50) * 10 = -5.0
        # missed_pnl = -5.0 - (-0.5) = -4.5 (negative → good exit)
        tracker.register_exit("slug-1", "up", 0.50, 0.45, 10.0, 60.0)
        tracker.record_outcome("slug-1", "down")
        assert tracker._exits_better_than_hold == 1
        assert tracker._total_saved == pytest.approx(4.5)

    def test_no_pending_exits(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        tracker.record_outcome("nonexistent", "up")
        assert tracker._total_exits == 0

    def test_persists_to_jsonl(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        tracker.register_exit("slug-1", "up", 0.50, 0.60, 10.0, 120.0)
        tracker.record_outcome("slug-1", "up")

        data_path = tmp_path / EXIT_ANALYSIS_FILENAME
        assert data_path.exists()
        lines = [line for line in data_path.read_text().strip().split("\n") if line.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["slug"] == "slug-1"
        assert record["winner"] == "up"
        assert record["entry_price"] == 0.5
        assert record["exit_price"] == 0.6

    def test_clears_pending_after_outcome(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        tracker.register_exit("slug-1", "up", 0.50, 0.60, 10.0, 120.0)
        tracker.record_outcome("slug-1", "up")
        assert "slug-1" not in tracker._pending


class TestGetSummary:
    def test_empty_returns_empty_string(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        assert tracker.get_summary() == ""

    def test_with_exits(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        # Create a good exit (losing side)
        tracker.register_exit("slug-1", "up", 0.50, 0.45, 10.0, 60.0)
        tracker.record_outcome("slug-1", "down")

        summary = tracker.get_summary()
        assert "Exit Analysis" in summary
        assert "1/1 better than hold" in summary
        assert "100%" in summary


class TestGoodExitRate:
    def test_no_exits(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        assert tracker.good_exit_rate == 0.0

    def test_all_good(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        tracker.register_exit("slug-1", "up", 0.50, 0.45, 10.0, 60.0)
        tracker.record_outcome("slug-1", "down")
        assert tracker.good_exit_rate == 1.0

    def test_mixed(self, tmp_path: Path):
        tracker = ExitTracker(tmp_path)
        # Good exit (exit from losing side)
        tracker.register_exit("slug-1", "up", 0.50, 0.45, 10.0, 60.0)
        tracker.record_outcome("slug-1", "down")
        # Missed upside (exit from winning side early)
        tracker.register_exit("slug-2", "up", 0.50, 0.60, 10.0, 60.0)
        tracker.record_outcome("slug-2", "up")
        assert tracker.good_exit_rate == pytest.approx(0.5)


class TestLoadHistorical:
    def test_loads_existing_data(self, tmp_path: Path):
        data_path = tmp_path / EXIT_ANALYSIS_FILENAME
        records = [
            {
                "slug": "s1",
                "token_side": "up",
                "entry_price": 0.5,
                "exit_price": 0.45,
                "exit_size": 10,
                "time_remaining": 60,
                "winner": "down",
                "held_value": 0.0,
                "actual_pnl": -0.5,
                "missed_pnl": -4.5,
            },
            {
                "slug": "s2",
                "token_side": "up",
                "entry_price": 0.5,
                "exit_price": 0.6,
                "exit_size": 10,
                "time_remaining": 60,
                "winner": "up",
                "held_value": 1.0,
                "actual_pnl": 1.0,
                "missed_pnl": 3.0,
            },
        ]
        data_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

        tracker = ExitTracker(tmp_path)
        assert tracker._total_exits == 2
        assert tracker._exits_better_than_hold == 1
        assert tracker._total_saved == pytest.approx(4.5)
        assert tracker._total_missed == pytest.approx(3.0)

    def test_skips_unresolved_records(self, tmp_path: Path):
        data_path = tmp_path / EXIT_ANALYSIS_FILENAME
        record = {
            "slug": "s1",
            "token_side": "up",
            "entry_price": 0.5,
            "exit_price": 0.6,
            "exit_size": 10,
            "time_remaining": 60,
            "winner": "",
            "held_value": 0.0,
            "actual_pnl": 0.0,
            "missed_pnl": 0.0,
        }
        data_path.write_text(json.dumps(record) + "\n")

        tracker = ExitTracker(tmp_path)
        assert tracker._total_exits == 0

    def test_handles_corrupt_file(self, tmp_path: Path):
        data_path = tmp_path / EXIT_ANALYSIS_FILENAME
        data_path.write_text("not valid json\n")

        tracker = ExitTracker(tmp_path)
        assert tracker._total_exits == 0

    def test_handles_empty_file(self, tmp_path: Path):
        data_path = tmp_path / EXIT_ANALYSIS_FILENAME
        data_path.write_text("")

        tracker = ExitTracker(tmp_path)
        assert tracker._total_exits == 0


# ---------------------------------------------------------------------------
# Re-export tests
# ---------------------------------------------------------------------------


class TestReExports:
    def test_tracker_importable(self):
        from polybot.exit_tracker import ExitRecord, ExitTracker

        assert ExitTracker is not None
        assert ExitRecord is not None

    def test_constants_importable(self):
        from polybot.exit_tracker import (
            EXIT_ANALYSIS_FILENAME,
            LOST_VALUE,
            PRICE_PRECISION,
            WON_VALUE,
        )

        assert EXIT_ANALYSIS_FILENAME == "exit_analysis.jsonl"
        assert WON_VALUE == 1.0
        assert LOST_VALUE == 0.0
        assert PRICE_PRECISION == 4
