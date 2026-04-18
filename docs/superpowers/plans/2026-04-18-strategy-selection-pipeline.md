# Strategy Selection Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 11-strategy search with a parametric grid (~1,700 combinations), walk-forward validation (5 folds), and Sharpe-based selection — all via a shared `notebooks/strategy_engine.py` module.

**Architecture:** New shared module `notebooks/strategy_engine.py` with `StrategyConfig` (dataclass), `StrategyGrid` (generates combinations), `run_scaling()` (simulation), and `WalkForwardEvaluator` (fold splitting + ranking). All three `03_strategy.ipynb` notebooks are rewritten to import from this module, becoming thin wrappers: load model, build predictions, call evaluator, plot, save.

**Tech Stack:** Python 3.11+, numpy, pandas, dataclasses. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-18-strategy-selection-pipeline-design.md`

---

### Task 1: Create `StrategyConfig` and `StrategyGrid`

**Files:**
- Create: `notebooks/strategy_engine.py`
- Create: `tests/notebooks/__init__.py`
- Create: `tests/notebooks/test_strategy_engine.py`

- [ ] **Step 1: Write failing tests for StrategyConfig and StrategyGrid**

Create `tests/notebooks/__init__.py` (empty file).

Create `tests/notebooks/test_strategy_engine.py`:

```python
"""Tests for the shared strategy engine module."""

from __future__ import annotations

import sys
from pathlib import Path

# notebooks/ is not a package — add it to sys.path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "notebooks"))

from strategy_engine import StrategyConfig, StrategyGrid


# ---------------------------------------------------------------------------
# StrategyConfig
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
# StrategyGrid
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
        # 3 elapsed * 2 consecutive * 2 confidence = 12
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
        # Single: 3 elapsed * 1 * 1 = 3
        assert len(single) == 3
        # Double: e2 > e1 + 0.10, so valid pairs: (0.10,0.30) only
        # (0.10,0.20) fails because 0.20 <= 0.10 + 0.10
        # (0.20,0.30) fails because 0.30 <= 0.20 + 0.10
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
        # 0.90 is excluded, so 2 strategies
        assert len(strategies) == 2
        elapsed_vals = [s.entry_points[0][0] for s in strategies]
        assert 0.90 not in elapsed_vals

    def test_default_grid_size(self):
        grid = StrategyGrid()
        strategies = grid.generate()
        # Should produce ~1700 strategies (exact count depends on filtering)
        assert len(strategies) > 1000
        assert len(strategies) < 3000

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
            assert s.name  # non-empty
            for elapsed, n_c in s.entry_points:
                assert 0 < elapsed <= 0.80
                assert n_c >= 1
            if len(s.entry_points) == 2:
                e1 = s.entry_points[0][0]
                e2 = s.entry_points[1][0]
                assert e2 > e1 + 0.10 - 1e-9  # float tolerance
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/notebooks/test_strategy_engine.py -v`

Expected: `ModuleNotFoundError: No module named 'strategy_engine'`

- [ ] **Step 3: Implement StrategyConfig and StrategyGrid**

Create `notebooks/strategy_engine.py`:

```python
"""Shared strategy engine for 03_strategy notebooks.

Provides parametric grid search over scaling-in strategies with
walk-forward validation and Sharpe-based selection.

Used by: notebooks/{lr,rf,xgb}/03_strategy.ipynb
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Strategy configuration
# ---------------------------------------------------------------------------

@dataclass
class StrategyConfig:
    """A scaling-in strategy configuration.

    Attributes:
        entry_points: List of (min_elapsed_pct, n_consecutive) tuples.
        min_confidence: Minimum max(prob, 1-prob) to place a bet.
        name: Human-readable label (auto-generated if empty).
    """

    entry_points: list[tuple[float, int]]
    min_confidence: float = 0.0
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            parts = [f"e{e:.0%}" for e, _ in self.entry_points]
            prefix = f"{len(self.entry_points)}x"
            self.name = f"{prefix} {'+'.join(parts)}"
            if self.min_confidence > 0:
                self.name += f" conf>{self.min_confidence:.2f}"


# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------

class StrategyGrid:
    """Generates all valid StrategyConfig combinations from parameter ranges."""

    def __init__(
        self,
        elapsed_values: list[float] | None = None,
        n_consecutive_values: list[int] | None = None,
        confidence_values: list[float] | None = None,
        max_entries: int = 2,
        min_elapsed_gap: float = 0.10,
        max_elapsed: float = 0.80,
    ) -> None:
        self.elapsed_values = elapsed_values or [
            round(0.05 * i, 2) for i in range(1, 17)
        ]
        self.n_consecutive_values = n_consecutive_values or [1, 2, 3, 4, 5]
        self.confidence_values = confidence_values or [
            0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75,
        ]
        self.max_entries = max_entries
        self.min_elapsed_gap = min_elapsed_gap
        self.max_elapsed = max_elapsed

    def generate(self) -> list[StrategyConfig]:
        """Return all valid strategy combinations."""
        strategies: list[StrategyConfig] = []
        valid_elapsed = [e for e in self.elapsed_values if e <= self.max_elapsed]

        # 1-entry strategies
        for elapsed, n_c, conf in product(
            valid_elapsed, self.n_consecutive_values, self.confidence_values,
        ):
            strategies.append(StrategyConfig(
                entry_points=[(elapsed, n_c)],
                min_confidence=conf,
            ))

        # 2-entry strategies
        if self.max_entries >= 2:
            for e1, nc1, e2, nc2, conf in product(
                valid_elapsed,
                self.n_consecutive_values,
                valid_elapsed,
                self.n_consecutive_values,
                self.confidence_values,
            ):
                if e2 <= e1 + self.min_elapsed_gap:
                    continue
                strategies.append(StrategyConfig(
                    entry_points=[(e1, nc1), (e2, nc2)],
                    min_confidence=conf,
                ))

        return strategies
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/notebooks/test_strategy_engine.py -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add notebooks/strategy_engine.py tests/notebooks/__init__.py tests/notebooks/test_strategy_engine.py
git commit -m "feat: add StrategyConfig and StrategyGrid to strategy_engine module

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Add `run_scaling()` to strategy engine

**Files:**
- Modify: `notebooks/strategy_engine.py`
- Modify: `tests/notebooks/test_strategy_engine.py`

- [ ] **Step 1: Write failing tests for run_scaling**

Append to `tests/notebooks/test_strategy_engine.py`:

```python
from strategy_engine import run_scaling


def _make_candle(candle_id, truth, snapshots):
    """Helper to build candle prediction data."""
    return {"candle_id": candle_id, "truth": truth, "snapshots": snapshots}


def _make_snap(tick, elapsed_pct, pred, prob, up_ask=0.55, down_ask=0.45):
    """Helper to build a snapshot dict."""
    return {
        "tick": tick,
        "elapsed_pct": elapsed_pct,
        "pred": pred,
        "prob": prob,
        "up_ask": up_ask,
        "down_ask": down_ask,
    }


# ---------------------------------------------------------------------------
# run_scaling
# ---------------------------------------------------------------------------

class TestRunScaling:
    def test_winning_bet_increases_balance(self):
        """Single candle, model predicts UP correctly at e30%."""
        candle = _make_candle("c1", truth=1, snapshots=[
            _make_snap(0, 0.10, 1, 0.7),
            _make_snap(1, 0.20, 1, 0.7),
            _make_snap(2, 0.30, 1, 0.7),  # 3 consecutive UP at e30%
            _make_snap(3, 0.40, 1, 0.7),
        ])
        cfg = StrategyConfig(entry_points=[(0.30, 3)])
        result = run_scaling(cfg, [candle])
        assert result["balance"] > 1000.0
        assert result["wins"] == 1
        assert result["total_bets"] == 1
        assert result["win_rate"] == 1.0

    def test_losing_bet_decreases_balance(self):
        """Single candle, model predicts UP but truth is DOWN."""
        candle = _make_candle("c1", truth=0, snapshots=[
            _make_snap(0, 0.10, 1, 0.7),
            _make_snap(1, 0.20, 1, 0.7),
            _make_snap(2, 0.30, 1, 0.7),
        ])
        cfg = StrategyConfig(entry_points=[(0.30, 3)])
        result = run_scaling(cfg, [candle])
        assert result["balance"] == 990.0  # lost $10
        assert result["wins"] == 0

    def test_confidence_filter_skips_low_confidence(self):
        """Confidence 0.55 < min 0.60, no bet placed."""
        candle = _make_candle("c1", truth=1, snapshots=[
            _make_snap(0, 0.10, 1, 0.55),
            _make_snap(1, 0.20, 1, 0.55),
            _make_snap(2, 0.30, 1, 0.55),
        ])
        cfg = StrategyConfig(entry_points=[(0.30, 3)], min_confidence=0.60)
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 0
        assert result["balance"] == 1000.0

    def test_no_entry_when_consecutive_broken(self):
        """Predictions flip: UP, DOWN, UP — no 3 consecutive."""
        candle = _make_candle("c1", truth=1, snapshots=[
            _make_snap(0, 0.10, 1, 0.7),
            _make_snap(1, 0.20, 0, 0.3),  # flips to DOWN
            _make_snap(2, 0.30, 1, 0.7),
        ])
        cfg = StrategyConfig(entry_points=[(0.10, 3)])
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 0

    def test_direction_consistency_blocks_second_entry(self):
        """First entry is UP, second entry flips to DOWN — second blocked."""
        candle = _make_candle("c1", truth=1, snapshots=[
            _make_snap(0, 0.05, 1, 0.7),
            _make_snap(1, 0.10, 1, 0.7),  # entry 1 triggers at e10%
            _make_snap(2, 0.50, 0, 0.3),  # flips direction
            _make_snap(3, 0.60, 0, 0.3),
        ])
        cfg = StrategyConfig(entry_points=[(0.05, 2), (0.50, 2)])
        result = run_scaling(cfg, [candle])
        assert result["total_bets"] == 1  # only first entry

    def test_per_candle_pnl_length(self):
        """per_candle_pnl has one entry per candle, including no-entry candles."""
        candles = [
            _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.7)]),  # < 5 snaps, but works with n_c=1
            _make_candle("c2", 1, [_make_snap(0, 0.05, 1, 0.7)]),  # no match for e30%
        ]
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, candles)
        assert len(result["per_candle_pnl"]) == 2

    def test_per_candle_pnl_zero_for_skipped(self):
        """Candles with no entry get PnL=0."""
        candle = _make_candle("c1", 1, [
            _make_snap(0, 0.05, 1, 0.7),  # only at 5%, strategy needs 30%
        ])
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, [candle])
        assert result["per_candle_pnl"] == [0.0]

    def test_sharpe_returned(self):
        """Result includes a sharpe field."""
        candles = [
            _make_candle(f"c{i}", 1, [
                _make_snap(0, 0.10, 1, 0.7),
                _make_snap(1, 0.20, 1, 0.7),
                _make_snap(2, 0.30, 1, 0.7),
            ])
            for i in range(10)
        ]
        cfg = StrategyConfig(entry_points=[(0.30, 3)])
        result = run_scaling(cfg, candles)
        assert "sharpe" in result
        assert result["sharpe"] > 0  # all wins → positive sharpe

    def test_max_bid_filter(self):
        """Ask price >= MAX_BID is rejected."""
        candle = _make_candle("c1", 1, [
            _make_snap(0, 0.30, 1, 0.7, up_ask=0.90),  # above max_bid=0.85
        ])
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, [candle], max_bid=0.85)
        assert result["total_bets"] == 0

    def test_history_includes_all_candles(self):
        """History has starting_balance + one entry per candle."""
        candles = [
            _make_candle("c1", 1, [_make_snap(0, 0.30, 1, 0.7)]),
            _make_candle("c2", 1, [_make_snap(0, 0.05, 1, 0.7)]),  # no match for e30%
        ]
        cfg = StrategyConfig(entry_points=[(0.30, 1)])
        result = run_scaling(cfg, candles)
        # initial balance + one entry per candle
        assert len(result["history"]) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/notebooks/test_strategy_engine.py::TestRunScaling -v`

Expected: `ImportError: cannot import name 'run_scaling'`

- [ ] **Step 3: Implement run_scaling**

Append to `notebooks/strategy_engine.py` (after the `StrategyGrid` class):

```python
# ---------------------------------------------------------------------------
# Strategy simulation
# ---------------------------------------------------------------------------

def run_scaling(
    strategy: StrategyConfig,
    candle_data: list[dict],
    bet_per_entry: float = 10.0,
    max_bid: float = 0.85,
    starting_balance: float = 1000.0,
) -> dict:
    """Run a scaling-in strategy simulation on candle prediction data.

    Args:
        strategy: The strategy configuration to test.
        candle_data: List of candle dicts, each with keys:
            - candle_id: str
            - truth: int (1=UP, 0=DOWN)
            - snapshots: list of snapshot dicts with keys:
                tick, elapsed_pct, pred, prob, up_ask, down_ask
        bet_per_entry: Fixed dollar amount per bet.
        max_bid: Maximum ask price to accept (skip if ask >= max_bid).
        starting_balance: Initial balance in dollars.

    Returns:
        Dict with keys: name, balance, history, per_candle_pnl, total_bets,
        candles_entered, wins, win_rate, return_pct, max_dd, sharpe.
    """
    bal = starting_balance
    history = [bal]
    per_candle_pnl: list[float] = []
    total_bets, total_wins, candles_entered = 0, 0, 0

    for cd in candle_data:
        sd = cd["snapshots"]
        truth = cd["truth"]
        entries: list[tuple[int, int, float]] = []
        first_direction: int | None = None
        candle_pnl = 0.0

        for min_e, n_c in strategy.entry_points:
            for i in range(max(n_c - 1, 0), len(sd)):
                if sd[i]["elapsed_pct"] < min_e:
                    continue
                if any(i <= prev_tick for prev_tick, _, _ in entries):
                    continue
                if n_c > 1 and not all(
                    sd[i - j]["pred"] == sd[i]["pred"] for j in range(n_c)
                ):
                    continue
                confidence = max(sd[i]["prob"], 1.0 - sd[i]["prob"])
                if confidence < strategy.min_confidence:
                    continue
                direction = sd[i]["pred"]
                if first_direction is None:
                    first_direction = direction
                elif direction != first_direction:
                    break
                ask = (
                    sd[i]["up_ask"] if direction == 1 else sd[i]["down_ask"]
                )
                if (
                    ask is None
                    or not np.isfinite(ask)
                    or ask <= 0
                    or ask >= max_bid
                ):
                    continue
                entries.append((i, direction, ask))
                break

        if not entries:
            per_candle_pnl.append(0.0)
            history.append(bal)
            continue

        candles_entered += 1
        for _, direction, ask in entries:
            if bal < bet_per_entry:
                break
            total_bets += 1
            if direction == truth:
                pnl = (bet_per_entry / ask) * (1.0 - ask)
                bal += pnl
                candle_pnl += pnl
                total_wins += 1
            else:
                bal -= bet_per_entry
                candle_pnl -= bet_per_entry

        per_candle_pnl.append(candle_pnl)
        history.append(bal)

    wr = total_wins / total_bets if total_bets > 0 else 0.0
    max_dd = 0.0
    if len(history) > 1:
        peak = history[0]
        for h in history[1:]:
            if h > peak:
                peak = h
            dd = (peak - h) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

    pnl_arr = np.array(per_candle_pnl)
    sharpe = (
        float(pnl_arr.mean() / pnl_arr.std())
        if len(pnl_arr) > 1 and pnl_arr.std() > 0
        else 0.0
    )

    return {
        "name": strategy.name,
        "balance": bal,
        "history": history,
        "per_candle_pnl": per_candle_pnl,
        "total_bets": total_bets,
        "candles_entered": candles_entered,
        "wins": total_wins,
        "win_rate": wr,
        "return_pct": (bal - starting_balance) / starting_balance * 100,
        "max_dd": max_dd,
        "sharpe": sharpe,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/notebooks/test_strategy_engine.py -v`

Expected: All 18 tests PASS (8 from Task 1 + 10 new).

- [ ] **Step 5: Commit**

```bash
git add notebooks/strategy_engine.py tests/notebooks/test_strategy_engine.py
git commit -m "feat: add run_scaling() with per-candle PnL and Sharpe to strategy engine

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Add `WalkForwardEvaluator` to strategy engine

**Files:**
- Modify: `notebooks/strategy_engine.py`
- Modify: `tests/notebooks/test_strategy_engine.py`

- [ ] **Step 1: Write failing tests for WalkForwardEvaluator**

Append to `tests/notebooks/test_strategy_engine.py`:

```python
from strategy_engine import WalkForwardEvaluator


def _make_test_candles(n=50):
    """Generate n deterministic candles for evaluator tests.

    Odd-indexed candles are UP (truth=1), even are DOWN (truth=0).
    All snapshots predict UP (pred=1, prob=0.7), so odd candles win.
    """
    candles = []
    for i in range(n):
        truth = i % 2  # alternating DOWN, UP
        candles.append(_make_candle(
            f"c{i}", truth,
            [
                _make_snap(0, 0.10, 1, 0.7),
                _make_snap(1, 0.20, 1, 0.7),
                _make_snap(2, 0.30, 1, 0.7),
                _make_snap(3, 0.50, 1, 0.7),
                _make_snap(4, 0.70, 1, 0.7),
            ],
        ))
    return candles


# ---------------------------------------------------------------------------
# WalkForwardEvaluator
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
            "strategy", "sharpe_mean", "sharpe_std",
            "return_mean", "return_std",
            "win_rate_mean", "win_rate_std",
            "max_dd_mean", "max_dd_std",
            "total_bets_mean", "candles_entered_mean",
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
        candles = _make_test_candles(53)  # not evenly divisible by 5
        strategies = [StrategyConfig(entry_points=[(0.10, 1)])]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        folds = evaluator._split_folds()
        assert len(folds) == 5
        total = sum(len(f) for f in folds)
        assert total == 53  # all candles covered

    def test_folds_are_non_overlapping(self):
        candles = _make_test_candles(50)
        strategies = [StrategyConfig(entry_points=[(0.10, 1)])]
        evaluator = WalkForwardEvaluator(strategies, candles, n_folds=5)
        folds = evaluator._split_folds()
        all_ids = []
        for fold in folds:
            fold_ids = [c["candle_id"] for c in fold]
            all_ids.extend(fold_ids)
        assert len(all_ids) == len(set(all_ids))  # no duplicates

    def test_config_preserved_in_results(self):
        candles = _make_test_candles(50)
        cfg = StrategyConfig(entry_points=[(0.30, 1)], min_confidence=0.6)
        evaluator = WalkForwardEvaluator([cfg], candles, n_folds=5)
        df = evaluator.run()
        assert df.iloc[0]["_config"] is cfg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/notebooks/test_strategy_engine.py::TestWalkForwardEvaluator -v`

Expected: `ImportError: cannot import name 'WalkForwardEvaluator'`

- [ ] **Step 3: Implement WalkForwardEvaluator**

Append to `notebooks/strategy_engine.py` (after `run_scaling`):

```python
# ---------------------------------------------------------------------------
# Walk-forward evaluator
# ---------------------------------------------------------------------------

class WalkForwardEvaluator:
    """Walk-forward validation for strategy selection.

    Splits candle prediction data into non-overlapping time-ordered folds,
    runs every strategy on each fold, and ranks by mean Sharpe ratio.

    Splits are always on candle boundaries — all snapshots for a given
    candle_id stay in the same fold.

    Args:
        strategies: List of StrategyConfig to evaluate.
        candle_data: List of candle prediction dicts (the all_cd list).
        n_folds: Number of evaluation folds.
        bet_per_entry: Fixed dollar amount per bet.
        max_bid: Maximum ask price to accept.
    """

    def __init__(
        self,
        strategies: list[StrategyConfig],
        candle_data: list[dict],
        n_folds: int = 5,
        bet_per_entry: float = 10.0,
        max_bid: float = 0.85,
    ) -> None:
        self.strategies = strategies
        self.candle_data = candle_data
        self.n_folds = n_folds
        self.bet_per_entry = bet_per_entry
        self.max_bid = max_bid

    def _split_folds(self) -> list[list[dict]]:
        """Split candle data into n_folds non-overlapping time-ordered folds."""
        n = len(self.candle_data)
        fold_size = n // self.n_folds
        folds: list[list[dict]] = []
        for i in range(self.n_folds):
            start = i * fold_size
            end = start + fold_size if i < self.n_folds - 1 else n
            folds.append(self.candle_data[start:end])
        return folds

    def run(self) -> pd.DataFrame:
        """Run all strategies across all folds, return results DataFrame.

        Returns:
            DataFrame sorted by sharpe_mean descending, with columns:
            strategy, sharpe_mean, sharpe_std, return_mean, return_std,
            win_rate_mean, win_rate_std, max_dd_mean, max_dd_std,
            total_bets_mean, candles_entered_mean, _config.
        """
        folds = self._split_folds()

        records: list[dict] = []
        for strategy in self.strategies:
            fold_sharpes: list[float] = []
            fold_returns: list[float] = []
            fold_wrs: list[float] = []
            fold_dds: list[float] = []
            fold_bets: list[int] = []
            fold_entered: list[int] = []

            for fold_data in folds:
                result = run_scaling(
                    strategy,
                    fold_data,
                    bet_per_entry=self.bet_per_entry,
                    max_bid=self.max_bid,
                )
                fold_sharpes.append(result["sharpe"])
                fold_returns.append(result["return_pct"])
                fold_wrs.append(result["win_rate"])
                fold_dds.append(result["max_dd"])
                fold_bets.append(result["total_bets"])
                fold_entered.append(result["candles_entered"])

            records.append({
                "strategy": strategy.name,
                "sharpe_mean": float(np.mean(fold_sharpes)),
                "sharpe_std": float(np.std(fold_sharpes)),
                "return_mean": float(np.mean(fold_returns)),
                "return_std": float(np.std(fold_returns)),
                "win_rate_mean": float(np.mean(fold_wrs)),
                "win_rate_std": float(np.std(fold_wrs)),
                "max_dd_mean": float(np.mean(fold_dds)),
                "max_dd_std": float(np.std(fold_dds)),
                "total_bets_mean": float(np.mean(fold_bets)),
                "candles_entered_mean": float(np.mean(fold_entered)),
                "_config": strategy,
            })

        df = pd.DataFrame(records)
        return df.sort_values("sharpe_mean", ascending=False).reset_index(drop=True)
```

- [ ] **Step 4: Run full test suite to verify everything passes**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/notebooks/test_strategy_engine.py -v`

Expected: All 24 tests PASS (8 + 10 + 6).

- [ ] **Step 5: Commit**

```bash
git add notebooks/strategy_engine.py tests/notebooks/test_strategy_engine.py
git commit -m "feat: add WalkForwardEvaluator with fold splitting and Sharpe ranking

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Rewrite LR `03_strategy.ipynb`

**Files:**
- Modify: `notebooks/lr/03_strategy.ipynb`

The notebook keeps cells 1-8 (title, imports, data loading, model training, prediction building) mostly intact. Cells for the strategy engine, grid, comparison, plots, save, and forward-test are rewritten.

- [ ] **Step 1: Update imports cell (cell 2)**

Replace the imports cell content with:

```python
import sys

sys.path.insert(0, str(__import__("pathlib").Path.cwd().parent))

import json
import random
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from strategy_engine import StrategyConfig, StrategyGrid, WalkForwardEvaluator, run_scaling
from technicals import CandleRecord, IndicatorSnapshot, compute_all
from tqdm import tqdm

random.seed(42)
np.random.seed(42)

FEATURES_PATH = Path("../../data/latest_features.jsonl")
DB_PATH = Path("../../data/collection.db")
MAX_BID = 0.85
WARM_UP = 21
```

- [ ] **Step 2: Replace Section 4 (strategy engine) with grid setup**

Replace the markdown cell for Section 4 with:

```markdown
## 4. Grid search + walk-forward evaluation
```

Replace the `run_scaling()` code cell with:

```python
grid = StrategyGrid()
strategies = grid.generate()
print(f"Generated {len(strategies)} strategy combinations")

evaluator = WalkForwardEvaluator(strategies, all_cd, n_folds=5, max_bid=MAX_BID)
results_df = evaluator.run()
print(f"Walk-forward complete: {len(results_df)} strategies evaluated across 5 folds")
```

- [ ] **Step 3: Replace Section 5 (strategy test) with comparison table**

Replace the markdown cell for Section 5 with:

```markdown
## 5. Comparison table (top 15 by mean Sharpe)
```

Replace the strategies list + loop code cell with:

```python
top15 = results_df.head(15)

print(f"{'Strategy':<32} {'Sharpe (μ±σ)':>16} {'Return (μ)':>11} {'WR (μ)':>8} {'MaxDD (μ)':>10} {'Bets (μ)':>9}")
print("-" * 92)
for _, row in top15.iterrows():
    print(
        f"{row['strategy']:<32} "
        f"{row['sharpe_mean']:>6.3f} ± {row['sharpe_std']:<5.3f} "
        f"{row['return_mean']:>+9.1f}% "
        f"{row['win_rate_mean'] * 100:>6.1f}% "
        f"{row['max_dd_mean'] * 100:>8.1f}% "
        f"{row['total_bets_mean']:>8.0f}"
    )
```

- [ ] **Step 4: Update Section 6 (equity curves)**

Keep the markdown cell as-is. Replace the plotting code cell with:

```python
# Run top 3 strategies on full validation set for equity curves
top3_configs = [results_df.iloc[i]["_config"] for i in range(min(3, len(results_df)))]
top3_full = [run_scaling(cfg, all_cd, max_bid=MAX_BID) for cfg in top3_configs]

# Also run all top-15 for the overview plot
top15_configs = [results_df.iloc[i]["_config"] for i in range(min(15, len(results_df)))]
top15_full = [run_scaling(cfg, all_cd, max_bid=MAX_BID) for cfg in top15_configs]

fig, axes = plt.subplots(2, 1, figsize=(16, 10))

for r in top15_full:
    axes[0].plot(r["history"], alpha=0.4, linewidth=1)
axes[0].axhline(1000, color="gray", linestyle="--", alpha=0.3)
axes[0].set_xlabel("Candle #")
axes[0].set_ylabel("Balance ($)")
axes[0].set_title("LogisticRegression — Top 15 Strategies (Full Validation Set)")
axes[0].grid(alpha=0.3)

colors = ["#2ecc71", "#3498db", "#e67e22"]
for r, c in zip(top3_full, colors, strict=False):
    sharpe_row = results_df[results_df["strategy"] == r["name"]].iloc[0]
    axes[1].plot(
        r["history"],
        color=c,
        linewidth=2.5,
        label=f"{r['name']} -> ${r['balance']:,.0f} (Sharpe={sharpe_row['sharpe_mean']:.3f}, WR={r['win_rate'] * 100:.0f}%)",
    )
axes[1].axhline(1000, color="gray", linestyle="--", alpha=0.3)
axes[1].set_xlabel("Candle #")
axes[1].set_ylabel("Balance ($)")
axes[1].set_title("Top 3 by Mean Sharpe")
axes[1].legend(fontsize=10)
axes[1].grid(alpha=0.3)

plt.tight_layout()
plt.show()
```

- [ ] **Step 5: Update Section 7 (save best)**

Keep the markdown cell as-is. Replace the save code cell with:

```python
best_row = results_df.iloc[0]
best_cfg = best_row["_config"]

config = {
    "model": "lr",
    "strategy": best_cfg.name,
    "entry_points": best_cfg.entry_points,
    "min_confidence": best_cfg.min_confidence,
    "sharpe_mean": round(best_row["sharpe_mean"], 4),
    "sharpe_std": round(best_row["sharpe_std"], 4),
    "win_rate": round(best_row["win_rate_mean"], 4),
    "return_pct": round(best_row["return_mean"], 2),
    "max_drawdown": round(best_row["max_dd_mean"], 4),
    "n_folds": 5,
    "grid_size": len(results_df),
    "eval_candles": len(all_cd),
    "eval_method": "walk_forward_5_folds",
    "total_bets": int(best_row["total_bets_mean"]),
    "created_at": datetime.now(UTC).isoformat(),
}

out_path = Path("../../data/optimal_strategy_lr.json")
with open(out_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"Best strategy: {best_cfg.name}")
print(f"  Sharpe: {best_row['sharpe_mean']:.3f} ± {best_row['sharpe_std']:.3f}")
print(f"  Win rate: {best_row['win_rate_mean'] * 100:.1f}%")
print(f"  Return: {best_row['return_mean']:+.1f}%")
print(f"  Max drawdown: {best_row['max_dd_mean'] * 100:.1f}%")
print(f"  Eval method: walk-forward (5 folds, {len(results_df)} strategies)")
print(f"\nSaved to {out_path}")
```

- [ ] **Step 6: Update Section 8 (forward-test)**

Keep the markdown cell as-is. In the forward-test code cell, replace the lines that use the old `run_scaling` at the end of the cell. Find:

```python
    # Run the chosen strategy on forward-test
    old_cd = all_cd
    all_cd = fwd_cd
    fwd_result = run_scaling(best["name"], best_eps, min_confidence=best_conf)
    all_cd = old_cd
```

Replace with:

```python
    # Run the chosen strategy on forward-test
    fwd_result = run_scaling(best_cfg, fwd_cd, max_bid=MAX_BID)
```

And replace the print block at the end:

```python
    print(f"\nForward-test confirmation ({len(fwd_cd)} unseen candles):")
    print(f"  Strategy: {best_cfg.name}")
    print(f"  Bets: {fwd_result['total_bets']}")
    print(f"  Win rate: {fwd_result['win_rate'] * 100:.1f}%")
    print(f"  Return: {fwd_result['return_pct']:+.1f}%")
    print(f"  Max DD: {fwd_result['max_dd'] * 100:.1f}%")
    print(f"  Sharpe: {fwd_result['sharpe']:.3f}")
    print(f"  Balance: ${fwd_result['balance']:,.2f}")
```

- [ ] **Step 7: Update conclusion cell**

Replace the conclusion markdown cell with:

```markdown
## Conclusion

Best LogisticRegression strategy discovered via **parametric grid search** over ~1,700 combinations
with **walk-forward validation** (5 folds). Strategy selected by highest **mean Sharpe ratio**
across folds.

Model was trained on the **first 80%** of candles — no data leakage.

Saved to `data/optimal_strategy_lr.json`.

**Note:** The exported model in `models/` (from `02_export`) is trained on ALL data
for maximum live performance. The strategy was evaluated on held-out data to prevent overfitting.
```

- [ ] **Step 8: Commit**

```bash
git add notebooks/lr/03_strategy.ipynb
git commit -m "feat(lr): rewrite strategy notebook with grid search + walk-forward

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Rewrite RF `03_strategy.ipynb`

**Files:**
- Modify: `notebooks/rf/03_strategy.ipynb`

Identical changes to Task 4 except for model-specific cells. Below lists only the differences from LR.

- [ ] **Step 1: Update imports cell (cell 2)**

Same as LR Task 4 Step 1 — identical content.

- [ ] **Step 2: Replace Section 4-5 (grid + comparison table)**

Same as LR Task 4 Steps 2-3 — identical content.

- [ ] **Step 3: Update Section 6 (equity curves)**

Same as LR Task 4 Step 4, but change the chart title:

```python
axes[0].set_title("RandomForest — Top 15 Strategies (Full Validation Set)")
```

All other plot code is identical.

- [ ] **Step 4: Update Section 7 (save best)**

Same as LR Task 4 Step 5, but change model name:

```python
config = {
    "model": "rf",
    ...
```

And output path:

```python
out_path = Path("../../data/optimal_strategy_rf.json")
```

- [ ] **Step 5: Update Section 8 (forward-test) and conclusion**

Same as LR Task 4 Steps 6-7.

Conclusion title changes to: `Best RandomForest strategy discovered...`

- [ ] **Step 6: Commit**

```bash
git add notebooks/rf/03_strategy.ipynb
git commit -m "feat(rf): rewrite strategy notebook with grid search + walk-forward

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Rewrite XGB `03_strategy.ipynb`

**Files:**
- Modify: `notebooks/xgb/03_strategy.ipynb`

Identical changes to Task 4 except for model-specific cells. Below lists only the differences from LR.

- [ ] **Step 1: Update imports cell (cell 2)**

Same as LR Task 4 Step 1 — identical content.

- [ ] **Step 2: Replace Section 4-5 (grid + comparison table)**

Same as LR Task 4 Steps 2-3 — identical content.

- [ ] **Step 3: Update Section 6 (equity curves)**

Same as LR Task 4 Step 4, but change the chart title:

```python
axes[0].set_title("XGBoost — Top 15 Strategies (Full Validation Set)")
```

All other plot code is identical.

- [ ] **Step 4: Update Section 7 (save best)**

Same as LR Task 4 Step 5, but change model name:

```python
config = {
    "model": "xgb",
    ...
```

And output path:

```python
out_path = Path("../../data/optimal_strategy_xgb.json")
```

- [ ] **Step 5: Update Section 8 (forward-test) and conclusion**

Same as LR Task 4 Steps 6-7.

Conclusion title changes to: `Best XGBoost strategy discovered...`

- [ ] **Step 6: Commit**

```bash
git add notebooks/xgb/03_strategy.ipynb
git commit -m "feat(xgb): rewrite strategy notebook with grid search + walk-forward

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Run full test suite and verify

**Files:** None (verification only)

- [ ] **Step 1: Run all strategy engine tests**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/notebooks/test_strategy_engine.py -v`

Expected: All 24 tests PASS.

- [ ] **Step 2: Run full project test suite**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run pytest tests/ -v`

Expected: All existing tests still PASS (no regressions).

- [ ] **Step 3: Lint check**

Run: `cd /Users/lfuryk/Documents/polymarket-bot && uv run ruff check notebooks/strategy_engine.py tests/notebooks/`

Expected: No errors.
