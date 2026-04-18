"""Tests for the shared strategy engine module."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "notebooks"))

import pandas as pd
from strategy_engine import StrategyConfig, StrategyGrid, WalkForwardEvaluator, run_scaling

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candle(candle_id, truth, snapshots):
    return {"candle_id": candle_id, "truth": truth, "snapshots": snapshots}


def _make_snap(tick, elapsed_pct, pred, prob, up_ask=0.55, down_ask=0.45):
    return {
        "tick": tick,
        "elapsed_pct": elapsed_pct,
        "pred": pred,
        "prob": prob,
        "up_ask": up_ask,
        "down_ask": down_ask,
    }


def _make_test_candles(n=50):
    candles = []
    for i in range(n):
        truth = i % 2
        candles.append(
            _make_candle(
                f"c{i}",
                truth,
                [
                    _make_snap(0, 0.10, 1, 0.7),
                    _make_snap(1, 0.20, 1, 0.7),
                    _make_snap(2, 0.30, 1, 0.7),
                    _make_snap(3, 0.50, 1, 0.7),
                    _make_snap(4, 0.70, 1, 0.7),
                ],
            )
        )
    return candles


# ---------------------------------------------------------------------------
# Task 1: StrategyConfig
# ---------------------------------------------------------------------------


class TestStrategyConfig:
    def test_auto_name_single_entry(self):
        cfg = StrategyConfig(entry_points=[(0.30, 3)], min_confidence=0.0)
        assert cfg.name == "1x e30%"

    def test_auto_name_two_entries(self):
        cfg = StrategyConfig(entry_points=[(0.05, 3), (0.50, 2)], min_confidence=0.0)
        assert cfg.name == "2x e5%+e50%"

    def test_auto_name_with_confidence(self):
        cfg = StrategyConfig(entry_points=[(0.30, 3)], min_confidence=0.65)
        assert cfg.name == "1x e30% conf>0.65"

    def test_custom_name_preserved(self):
        cfg = StrategyConfig(entry_points=[(0.30, 3)], min_confidence=0.0, name="custom")
        assert cfg.name == "custom"


# ---------------------------------------------------------------------------
# Task 1: StrategyGrid
# ---------------------------------------------------------------------------


class TestStrategyGrid:
    def test_single_entry_count(self):
        grid = StrategyGrid(
            elapsed_values=[0.10, 0.20, 0.30],
            n_consecutive_values=[1, 2],
            confidence_values=[0.0, 0.6],
            max_entries=1,
        )
        strategies = grid.generate()
        assert len(strategies) == 12

    def test_two_entry_filters_gap(self):
        grid = StrategyGrid(
            elapsed_values=[0.10, 0.20, 0.30],
            n_consecutive_values=[1],
            confidence_values=[0.0],
            max_entries=2,
            min_elapsed_gap=0.10,
        )
        strategies = grid.generate()
        single = [s for s in strategies if len(s.entry_points) == 1]
        double = [s for s in strategies if len(s.entry_points) == 2]
        assert len(single) == 3
        # e2 > e1 + 0.10: only (0.10, 0.30) qualifies
        assert len(double) == 1
        assert double[0].entry_points == [(0.10, 1), (0.30, 1)]

    def test_max_elapsed_filter(self):
        grid = StrategyGrid(
            elapsed_values=[0.70, 0.80, 0.90],
            n_consecutive_values=[1],
            confidence_values=[0.0],
            max_entries=1,
            max_elapsed=0.80,
        )
        strategies = grid.generate()
        assert len(strategies) == 2
        elapsed_vals = [s.entry_points[0][0] for s in strategies]
        assert 0.90 not in elapsed_vals

    def test_default_grid_size(self):
        grid = StrategyGrid()
        strategies = grid.generate()
        assert len(strategies) > 1000
        assert len(strategies) < 5000

    def test_all_configs_are_valid(self):
        grid = StrategyGrid(
            elapsed_values=[0.10, 0.30, 0.50, 0.70],
            n_consecutive_values=[1, 3],
            confidence_values=[0.0, 0.6],
            max_entries=2,
            min_elapsed_gap=0.10,
        )
        for s in grid.generate():
            assert len(s.entry_points) >= 1
            assert len(s.entry_points) <= 2
            assert s.min_confidence >= 0.0
            assert s.name
            for elapsed, n_c in s.entry_points:
                assert 0 < elapsed <= 0.80
                assert n_c >= 1
            if len(s.entry_points) == 2:
                e1 = s.entry_points[0][0]
                e2 = s.entry_points[1][0]
                assert e2 > e1 + 0.10 - 1e-9


# ---------------------------------------------------------------------------
# Task 2: run_scaling
# ---------------------------------------------------------------------------


class TestRunScaling:
    def test_winning_bet_increases_balance(self):
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[
                _make_snap(0, 0.10, 1, 0.7),
                _make_snap(1, 0.20, 1, 0.7),
                _make_snap(2, 0.30, 1, 0.7),
                _make_snap(3, 0.40, 1, 0.7),
            ],
        )
        cfg = StrategyConfig(entry_points=[(0.30, 3)])
        result = run_scaling(cfg, [candle])
        assert result["balance"] > 1000.0
        assert result["wins"] == 1
        assert result["total_bets"] == 1
        assert result["win_rate"] == 1.0

    def test_losing_bet_decreases_balance(self):
        candle = _make_candle(
            "c1",
            truth=0,
            snapshots=[
                _make_snap(0, 0.10, 1, 0.7),
                _make_snap(1, 0.20, 1, 0.7),
                _make_snap(2, 0.30, 1, 0.7),
            ],
        )
        cfg = StrategyConfig(entry_points=[(0.30, 3)])
        result = run_scaling(cfg, [candle])
        assert result["balance"] == 990.0
        assert result["wins"] == 0

    def test_confidence_filter_skips_low_confidence(self):
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[
                _make_snap(0, 0.10, 1, 0.55),
                _make_snap(1, 0.20, 1, 0.55),
                _make_snap(2, 0.30, 1, 0.55),
            ],
        )
        cfg = StrategyConfig(entry_points=[(0.30, 3)], min_confidence=0.60)
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 0
        assert result["balance"] == 1000.0

    def test_no_entry_when_consecutive_broken(self):
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[
                _make_snap(0, 0.10, 1, 0.7),
                _make_snap(1, 0.20, 0, 0.3),
                _make_snap(2, 0.30, 1, 0.7),
            ],
        )
        cfg = StrategyConfig(entry_points=[(0.10, 3)])
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 0

    def test_direction_consistency_blocks_second_entry(self):
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[
                _make_snap(0, 0.05, 1, 0.7),
                _make_snap(1, 0.10, 1, 0.7),
                _make_snap(2, 0.50, 0, 0.3),
                _make_snap(3, 0.60, 0, 0.3),
            ],
        )
        cfg = StrategyConfig(entry_points=[(0.05, 2), (0.50, 2)])
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 1

    def test_per_candle_pnl_length(self):
        candles = [
            _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.7)]),
            _make_candle("c2", 1, [_make_snap(0, 0.05, 1, 0.7)]),
        ]
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, candles)
        assert len(result["per_candle_pnl"]) == 2

    def test_per_candle_pnl_zero_for_skipped(self):
        candle = _make_candle("c1", 1, [_make_snap(0, 0.05, 1, 0.7)])
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, [candle])
        assert result["per_candle_pnl"] == [0.0]

    def test_sharpe_returned(self):
        candles = [
            _make_candle(
                f"c{i}",
                1,
                [
                    _make_snap(0, 0.10, 1, 0.7),
                    _make_snap(1, 0.20, 1, 0.7),
                    _make_snap(2, 0.30, 1, 0.7),
                ],
            )
            for i in range(10)
        ]
        cfg = StrategyConfig(entry_points=[(0.30, 3)])
        result = run_scaling(cfg, candles)
        assert "sharpe" in result
        assert result["sharpe"] > 0

    def test_max_bid_filter(self):
        candle = _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.7, up_ask=0.90)])
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, [candle], max_bid=0.85)
        assert result["total_bets"] == 0

    def test_history_includes_all_candles(self):
        candles = [
            _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.7)]),
            _make_candle("c2", 1, [_make_snap(0, 0.05, 1, 0.7)]),
        ]
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, candles)
        assert len(result["history"]) == 3  # initial + one per candle


# ---------------------------------------------------------------------------
# Task 3: WalkForwardEvaluator
# ---------------------------------------------------------------------------


class TestWalkForwardEvaluator:
    def test_returns_dataframe(self):
        candles = _make_test_candles(50)
        strategies = [
            StrategyConfig(entry_points=[(0.30, 3)]),
            StrategyConfig(entry_points=[(0.10, 1)]),
        ]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        df = evaluator.run()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2

    def test_required_columns(self):
        candles = _make_test_candles(50)
        strategies = [StrategyConfig(entry_points=[(0.30, 1)])]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        df = evaluator.run()
        required = [
            "strategy",
            "sharpe_mean",
            "sharpe_std",
            "return_mean",
            "return_std",
            "win_rate_mean",
            "win_rate_std",
            "max_dd_mean",
            "max_dd_std",
            "total_bets_mean",
            "candles_entered_mean",
            "_config",
        ]
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_sorted_by_sharpe_descending(self):
        candles = _make_test_candles(50)
        strategies = [
            StrategyConfig(entry_points=[(0.30, 3)]),
            StrategyConfig(entry_points=[(0.10, 1)]),
            StrategyConfig(entry_points=[(0.50, 1)], min_confidence=0.75),
        ]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        df = evaluator.run()
        sharpes = df["sharpe_mean"].tolist()
        assert sharpes == sorted(sharpes, reverse=True)

    def test_fold_split_covers_all_candles(self):
        candles = _make_test_candles(53)
        strategies = [StrategyConfig(entry_points=[(0.10, 1)])]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        folds = evaluator._split_folds()
        assert len(folds) == 5
        total = sum(len(f) for f in folds)
        assert total == 53

    def test_folds_are_non_overlapping(self):
        candles = _make_test_candles(50)
        strategies = [StrategyConfig(entry_points=[(0.10, 1)])]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        folds = evaluator._split_folds()
        all_ids = []
        for fold in folds:
            fold_ids = [c["candle_id"] for c in fold]
            all_ids.extend(fold_ids)
        assert len(all_ids) == len(set(all_ids))

    def test_config_preserved_in_results(self):
        candles = _make_test_candles(50)
        cfg = StrategyConfig(entry_points=[(0.30, 1)], min_confidence=0.6)
        evaluator = WalkForwardEvaluator([cfg], candles, n_folds=5)
        df = evaluator.run()
        assert df.iloc[0]["_config"] is cfg
