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
    """Create test candles with edge-friendly probabilities.

    prob=0.7 and up_ask=0.55 gives edge = max(0.7, 0.3) - 0.55 = 0.15.
    """
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
# StrategyConfig
# ---------------------------------------------------------------------------


class TestStrategyConfig:
    def test_auto_name_single_entry(self):
        cfg = StrategyConfig(min_edge=0.05, max_entries=1)
        assert cfg.name == "edge>=0.05 x1"

    def test_auto_name_multi_entry(self):
        cfg = StrategyConfig(min_edge=0.10, max_entries=2)
        assert cfg.name == "edge>=0.10 x2"

    def test_auto_name_zero_edge(self):
        cfg = StrategyConfig(min_edge=0.0, max_entries=1)
        assert cfg.name == "edge>=0.00 x1"

    def test_custom_name_preserved(self):
        cfg = StrategyConfig(min_edge=0.05, max_entries=1, name="custom")
        assert cfg.name == "custom"


# ---------------------------------------------------------------------------
# StrategyGrid
# ---------------------------------------------------------------------------


class TestStrategyGrid:
    def test_default_grid_count(self):
        """Default: 7 edge values x 2 max_entries = 14 configs."""
        grid = StrategyGrid()
        strategies = grid.generate()
        assert len(strategies) == 14

    def test_custom_grid_count(self):
        grid = StrategyGrid(
            edge_values=[0.0, 0.05, 0.10],
            max_entries_values=[1, 2, 3],
        )
        strategies = grid.generate()
        assert len(strategies) == 9

    def test_single_max_entries(self):
        grid = StrategyGrid(
            edge_values=[0.0, 0.05],
            max_entries_values=[1],
        )
        strategies = grid.generate()
        assert len(strategies) == 2
        for s in strategies:
            assert s.max_entries == 1

    def test_all_configs_have_names(self):
        grid = StrategyGrid()
        for s in grid.generate():
            assert s.name
            assert "edge>=" in s.name
            assert s.min_edge >= 0.0

    def test_generates_cartesian_product(self):
        grid = StrategyGrid(
            edge_values=[0.05, 0.10],
            max_entries_values=[1, 2],
        )
        strategies = grid.generate()
        pairs = [(s.min_edge, s.max_entries) for s in strategies]
        assert (0.05, 1) in pairs
        assert (0.05, 2) in pairs
        assert (0.10, 1) in pairs
        assert (0.10, 2) in pairs


# ---------------------------------------------------------------------------
# run_scaling
# ---------------------------------------------------------------------------


class TestRunScaling:
    def test_winning_bet_increases_balance(self):
        """prob=0.7 up_ask=0.55 → edge=0.15, direction=1, truth=1 → win."""
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[_make_snap(0, 0.10, 1, 0.7, up_ask=0.55)],
        )
        cfg = StrategyConfig(min_edge=0.10, max_entries=1)
        result = run_scaling(cfg, [candle])
        assert result["balance"] > 1000.0
        assert result["wins"] == 1
        assert result["total_bets"] == 1
        assert result["win_rate"] == 1.0

    def test_losing_bet_decreases_balance(self):
        """prob=0.7 up_ask=0.55 → edge=0.15, direction=1, truth=0 → loss."""
        candle = _make_candle(
            "c1",
            truth=0,
            snapshots=[_make_snap(0, 0.10, 1, 0.7, up_ask=0.55)],
        )
        cfg = StrategyConfig(min_edge=0.10, max_entries=1)
        result = run_scaling(cfg, [candle])
        assert result["balance"] == 990.0
        assert result["wins"] == 0

    def test_edge_filter_skips_low_edge(self):
        """prob=0.55 up_ask=0.55 → edge=max(0.55,0.45)-0.55=0.0 < 0.05 → skip."""
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[_make_snap(0, 0.10, 1, 0.55, up_ask=0.55)],
        )
        cfg = StrategyConfig(min_edge=0.05, max_entries=1)
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 0
        assert result["balance"] == 1000.0

    def test_zero_edge_always_enters(self):
        """min_edge=0.0 should enter on any snapshot with valid ask."""
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[_make_snap(0, 0.10, 1, 0.51, up_ask=0.55)],
        )
        cfg = StrategyConfig(min_edge=0.0, max_entries=1)
        result = run_scaling(cfg, [candle])
        # edge = max(0.51, 0.49) - 0.55 = -0.04 < 0 → no entry
        assert result["total_bets"] == 0

    def test_zero_edge_enters_when_confidence_exceeds_ask(self):
        """min_edge=0.0 enters when confidence >= ask."""
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[_make_snap(0, 0.10, 1, 0.7, up_ask=0.55)],
        )
        cfg = StrategyConfig(min_edge=0.0, max_entries=1)
        result = run_scaling(cfg, [candle])
        # edge = max(0.7, 0.3) - 0.55 = 0.15 >= 0.0 → enters
        assert result["total_bets"] == 1

    def test_direction_lock_blocks_inconsistent_entry(self):
        """First snap predicts UP (direction=1), second predicts DOWN (direction=0).

        Second entry should be blocked by direction lock.
        """
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[
                _make_snap(0, 0.10, 1, 0.8, up_ask=0.55),  # edge=0.25, direction=1
                _make_snap(1, 0.20, 0, 0.2, down_ask=0.45),  # edge=0.35, direction=0
            ],
        )
        cfg = StrategyConfig(min_edge=0.10, max_entries=2)
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 1  # only first entry fires

    def test_direction_lock_allows_consistent_entry(self):
        """Both snaps predict UP with sufficient edge → 2 entries."""
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[
                _make_snap(0, 0.10, 1, 0.8, up_ask=0.55),  # edge=0.25
                _make_snap(1, 0.20, 1, 0.75, up_ask=0.55),  # edge=0.20
            ],
        )
        cfg = StrategyConfig(min_edge=0.10, max_entries=2)
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 2

    def test_max_entries_cap(self):
        """Only max_entries bets placed even with many qualifying snapshots."""
        candle = _make_candle(
            "c1",
            truth=1,
            snapshots=[
                _make_snap(i, i * 0.1, 1, 0.8, up_ask=0.55)  # edge=0.25 each
                for i in range(5)
            ],
        )
        cfg = StrategyConfig(min_edge=0.05, max_entries=2)
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 2

    def test_per_candle_pnl_length(self):
        candles = [
            _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.7)]),
            _make_candle("c2", 1, [_make_snap(0, 0.05, 1, 0.7)]),
        ]
        cfg = StrategyConfig(min_edge=0.10, max_entries=1)
        result = run_scaling(cfg, candles)
        assert len(result["per_candle_pnl"]) == 2

    def test_per_candle_pnl_zero_for_skipped(self):
        """Candle with no qualifying snapshot → 0 PnL."""
        candle = _make_candle("c1", 1, [_make_snap(0, 0.05, 1, 0.51, up_ask=0.55)])
        cfg = StrategyConfig(min_edge=0.10, max_entries=1)
        result = run_scaling(cfg, [candle])
        # edge = max(0.51, 0.49) - 0.55 = -0.04 < 0.10 → no entry
        assert result["per_candle_pnl"] == [0.0]

    def test_sharpe_returned(self):
        """Mix of wins and losses produces a finite nonzero Sharpe."""
        candles = [
            _make_candle(
                f"c{i}",
                1 if i % 3 != 0 else 0,  # 2/3 wins, 1/3 losses for variance
                [_make_snap(0, 0.10, 1, 0.7, up_ask=0.55)],
            )
            for i in range(12)
        ]
        cfg = StrategyConfig(min_edge=0.05, max_entries=1)
        result = run_scaling(cfg, candles)
        assert "sharpe" in result
        assert result["sharpe"] > 0

    def test_max_bid_filter(self):
        candle = _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.95, up_ask=0.90)])
        cfg = StrategyConfig(min_edge=0.01, max_entries=1)
        result = run_scaling(cfg, [candle], max_bid=0.85)
        assert result["total_bets"] == 0

    def test_history_includes_all_candles(self):
        candles = [
            _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.7)]),
            _make_candle("c2", 1, [_make_snap(0, 0.05, 1, 0.7)]),
        ]
        cfg = StrategyConfig(min_edge=0.05, max_entries=1)
        result = run_scaling(cfg, candles)
        assert len(result["history"]) == 3  # initial + one per candle

    def test_down_direction_uses_down_ask(self):
        """prob=0.2 → direction=0, confidence=0.8, ask=down_ask=0.45, edge=0.35."""
        candle = _make_candle(
            "c1",
            truth=0,
            snapshots=[_make_snap(0, 0.10, 0, 0.2, up_ask=0.55, down_ask=0.45)],
        )
        cfg = StrategyConfig(min_edge=0.10, max_entries=1)
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 1
        assert result["wins"] == 1
        # profit = 10 * (1/0.45 - 1) ≈ 12.22
        assert result["balance"] > 1000.0


# ---------------------------------------------------------------------------
# WalkForwardEvaluator
# ---------------------------------------------------------------------------


class TestWalkForwardEvaluator:
    def test_returns_dataframe(self):
        candles = _make_test_candles(50)
        strategies = [
            StrategyConfig(min_edge=0.10, max_entries=1),
            StrategyConfig(min_edge=0.05, max_entries=2),
        ]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        df = evaluator.run()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2

    def test_required_columns(self):
        candles = _make_test_candles(50)
        strategies = [StrategyConfig(min_edge=0.05, max_entries=1)]
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
            StrategyConfig(min_edge=0.05, max_entries=1),
            StrategyConfig(min_edge=0.10, max_entries=2),
            StrategyConfig(min_edge=0.20, max_entries=1),
        ]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        df = evaluator.run()
        sharpes = df["sharpe_mean"].tolist()
        assert sharpes == sorted(sharpes, reverse=True)

    def test_fold_split_covers_all_candles(self):
        candles = _make_test_candles(53)
        strategies = [StrategyConfig(min_edge=0.05, max_entries=1)]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        folds = evaluator._split_folds()
        assert len(folds) == 5
        total = sum(len(f) for f in folds)
        assert total == 53

    def test_folds_are_non_overlapping(self):
        candles = _make_test_candles(50)
        strategies = [StrategyConfig(min_edge=0.05, max_entries=1)]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        folds = evaluator._split_folds()
        all_ids = []
        for fold in folds:
            fold_ids = [c["candle_id"] for c in fold]
            all_ids.extend(fold_ids)
        assert len(all_ids) == len(set(all_ids))

    def test_config_preserved_in_results(self):
        candles = _make_test_candles(50)
        cfg = StrategyConfig(min_edge=0.10, max_entries=1)
        evaluator = WalkForwardEvaluator([cfg], candles, n_folds=5)
        df = evaluator.run()
        assert df.iloc[0]["_config"] is cfg
