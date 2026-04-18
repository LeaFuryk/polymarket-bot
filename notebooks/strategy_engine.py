"""Shared strategy engine for notebook strategy selection pipelines.

Provides:
- StrategyConfig: dataclass describing a scaling-in strategy
- StrategyGrid: generates all valid combinations from parameter ranges
- run_scaling: back-tests a StrategyConfig on candle data
- WalkForwardEvaluator: walk-forward cross-validation across strategy grid
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# StrategyConfig
# ---------------------------------------------------------------------------


@dataclass
class StrategyConfig:
    """A scaling-in trading strategy configuration.

    Args:
        entry_points: List of (min_elapsed_pct, n_consecutive) tuples.
            Each entry point triggers when the model predicts consistently
            for n_consecutive ticks at or after min_elapsed_pct of candle time.
        min_confidence: Minimum prediction probability required to enter.
        name: Display name. Auto-generated from entry_points if empty.
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
# StrategyGrid
# ---------------------------------------------------------------------------


class StrategyGrid:
    """Generate all valid StrategyConfig combinations from parameter ranges.

    Args:
        elapsed_values: Candidate elapsed-pct thresholds for entries.
            Defaults to [0.05, 0.10, ..., 0.80] (16 values).
        n_consecutive_values: Candidate consecutive-tick counts.
            Defaults to [1, 2, 3, 4, 5].
        confidence_values: Candidate min_confidence thresholds.
            Defaults to [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75].
        max_entries: Maximum number of scale-in entries (1 or 2).
        min_elapsed_gap: Minimum gap between two entry elapsed values.
        max_elapsed: Maximum allowed elapsed value for any entry.
    """

    def __init__(
        self,
        elapsed_values: list[float] | None = None,
        n_consecutive_values: list[int] | None = None,
        confidence_values: list[float] | None = None,
        max_entries: int = 2,
        min_elapsed_gap: float = 0.10,
        max_elapsed: float = 0.80,
    ) -> None:
        if elapsed_values is None:
            elapsed_values = [round(v, 2) for v in np.arange(0.05, 0.85, 0.05)]
        if n_consecutive_values is None:
            n_consecutive_values = [1, 2, 3, 4, 5]
        if confidence_values is None:
            confidence_values = [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]

        self.elapsed_values = elapsed_values
        self.n_consecutive_values = n_consecutive_values
        self.confidence_values = confidence_values
        self.max_entries = max_entries
        self.min_elapsed_gap = min_elapsed_gap
        self.max_elapsed = max_elapsed

    def generate(self) -> list[StrategyConfig]:
        """Return all valid StrategyConfig combinations.

        For two-entry strategies, n_consecutive is shared across both entry
        points (one value applied uniformly), keeping the grid size manageable.
        """
        configs: list[StrategyConfig] = []
        valid_elapsed = [e for e in self.elapsed_values if e <= self.max_elapsed + 1e-9]

        # Single-entry strategies: vary elapsed, n_consecutive, and confidence independently
        for e1, n1, conf in itertools.product(valid_elapsed, self.n_consecutive_values, self.confidence_values):
            configs.append(StrategyConfig(entry_points=[(e1, n1)], min_confidence=conf))

        # Two-entry strategies: vary elapsed pairs, shared n_consecutive, and confidence
        if self.max_entries >= 2:
            for e1, e2, n_c, conf in itertools.product(
                valid_elapsed,
                valid_elapsed,
                self.n_consecutive_values,
                self.confidence_values,
            ):
                if e2 > e1 + self.min_elapsed_gap:
                    configs.append(StrategyConfig(entry_points=[(e1, n_c), (e2, n_c)], min_confidence=conf))

        return configs


# ---------------------------------------------------------------------------
# run_scaling
# ---------------------------------------------------------------------------


def run_scaling(
    strategy: StrategyConfig,
    candle_data: list[dict],
    bet_per_entry: float = 10.0,
    max_bid: float = 0.85,
    starting_balance: float = 1000.0,
) -> dict:
    """Back-test a StrategyConfig on a list of candles.

    Each candle dict must have:
        candle_id (str), truth (int: 1=UP/0=DOWN),
        snapshots (list of dicts with tick, elapsed_pct, pred, prob, up_ask, down_ask)

    Returns a dict with:
        balance, wins, total_bets, win_rate, max_drawdown, candles_entered,
        history (list of balance checkpoints), per_candle_pnl (one float per candle),
        sharpe (float)
    """
    balance = starting_balance
    wins = 0
    total_bets = 0
    candles_entered = 0
    peak = starting_balance

    history: list[float] = [balance]
    per_candle_pnl: list[float] = []
    max_drawdown = 0.0

    entry_points = strategy.entry_points  # [(elapsed, n_consec), ...]

    for candle in candle_data:
        truth: int = candle["truth"]
        snapshots: list[dict] = candle["snapshots"]
        candle_pnl = 0.0
        first_direction: int | None = None  # direction locked on first entry
        triggered = [False] * len(entry_points)

        for i, snap in enumerate(snapshots):
            elapsed: float = snap["elapsed_pct"]

            for idx, (min_elapsed, n_consecutive) in enumerate(entry_points):
                if triggered[idx]:
                    continue

                # Must have reached the elapsed threshold
                if elapsed < min_elapsed - 1e-9:
                    continue

                # Need at least n_consecutive ticks available (look back)
                if i < n_consecutive - 1:
                    continue

                # Check last n_consecutive ticks all predict the same direction
                recent = snapshots[i - n_consecutive + 1 : i + 1]
                preds = [s["pred"] for s in recent]
                if len(set(preds)) != 1:
                    continue  # not all the same direction

                pred: int = preds[-1]
                up_ask: float = snap["up_ask"]
                down_ask: float = snap["down_ask"]

                # Confidence filter (check all recent ticks)
                if any(max(s["prob"], 1.0 - s["prob"]) < strategy.min_confidence for s in recent):
                    continue

                # Direction consistency: must agree with first entry direction
                if first_direction is not None and pred != first_direction:
                    continue

                # Ask price filter
                ask = up_ask if pred == 1 else down_ask
                if ask is None or not np.isfinite(ask) or ask <= 0 or ask >= max_bid:
                    continue

                # Fire entry
                triggered[idx] = True
                total_bets += 1
                if first_direction is None:
                    first_direction = pred

                # Settle bet
                if pred == truth:
                    profit = bet_per_entry * (1.0 / ask - 1.0)
                    balance += profit
                    candle_pnl += profit
                    wins += 1
                else:
                    balance -= bet_per_entry
                    candle_pnl -= bet_per_entry

                # Update drawdown incrementally
                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak if peak > 0 else 0.0
                if dd > max_drawdown:
                    max_drawdown = dd

        if any(triggered):
            candles_entered += 1

        per_candle_pnl.append(candle_pnl)
        history.append(balance)

    win_rate = wins / total_bets if total_bets > 0 else 0.0

    # Sharpe: mean / std of per_candle_pnl (0 if std==0 or <2 candles)
    pnl_arr = np.array(per_candle_pnl, dtype=float)
    if len(pnl_arr) >= 2 and pnl_arr.std() > 0:
        sharpe = float(pnl_arr.mean() / pnl_arr.std())
    else:
        sharpe = 0.0

    return {
        "name": strategy.name,
        "balance": balance,
        "wins": wins,
        "total_bets": total_bets,
        "win_rate": win_rate,
        "return_pct": (balance - starting_balance) / starting_balance * 100,
        "max_dd": max_drawdown,
        "candles_entered": candles_entered,
        "history": history,
        "per_candle_pnl": per_candle_pnl,
        "sharpe": sharpe,
    }


# ---------------------------------------------------------------------------
# WalkForwardEvaluator
# ---------------------------------------------------------------------------


class WalkForwardEvaluator:
    """Walk-forward cross-validation evaluator for strategy grid search.

    Splits candle_data into n_folds non-overlapping time-ordered folds,
    evaluates all strategies on each fold, and aggregates per-fold metrics.

    Args:
        strategies: List of StrategyConfig objects to evaluate.
        candle_data: List of candle dicts in chronological order.
        n_folds: Number of folds to split data into.
        bet_per_entry: Fixed bet amount per entry.
        max_bid: Maximum allowed ask price.
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
        """Split candle_data into n_folds non-overlapping time-ordered folds.

        The last fold gets any remainder candles so all candles are covered.
        """
        n = len(self.candle_data)
        fold_size = n // self.n_folds
        folds: list[list[dict]] = []
        for i in range(self.n_folds):
            start = i * fold_size
            if i < self.n_folds - 1:
                end = start + fold_size
            else:
                end = n  # last fold gets remainder
            folds.append(self.candle_data[start:end])
        return folds

    def run(self) -> pd.DataFrame:
        """Run all strategies across all folds and return aggregated results.

        Returns:
            DataFrame sorted by sharpe_mean descending with columns:
            strategy, sharpe_mean, sharpe_std, return_mean, return_std,
            win_rate_mean, win_rate_std, max_dd_mean, max_dd_std,
            total_bets_mean, candles_entered_mean, _config
        """
        folds = self._split_folds()
        rows: list[dict[str, Any]] = []

        for cfg in self.strategies:
            fold_sharpes: list[float] = []
            fold_returns: list[float] = []
            fold_win_rates: list[float] = []
            fold_max_dds: list[float] = []
            fold_total_bets: list[float] = []
            fold_candles_entered: list[float] = []

            for fold in folds:
                result = run_scaling(
                    cfg,
                    fold,
                    bet_per_entry=self.bet_per_entry,
                    max_bid=self.max_bid,
                )
                fold_sharpes.append(result["sharpe"])
                fold_returns.append(result["return_pct"])
                fold_win_rates.append(result["win_rate"])
                fold_max_dds.append(result["max_dd"])
                fold_total_bets.append(result["total_bets"])
                fold_candles_entered.append(result["candles_entered"])

            rows.append(
                {
                    "strategy": cfg.name,
                    "sharpe_mean": float(np.mean(fold_sharpes)),
                    "sharpe_std": float(np.std(fold_sharpes)),
                    "return_mean": float(np.mean(fold_returns)),
                    "return_std": float(np.std(fold_returns)),
                    "win_rate_mean": float(np.mean(fold_win_rates)),
                    "win_rate_std": float(np.std(fold_win_rates)),
                    "max_dd_mean": float(np.mean(fold_max_dds)),
                    "max_dd_std": float(np.std(fold_max_dds)),
                    "total_bets_mean": float(np.mean(fold_total_bets)),
                    "candles_entered_mean": float(np.mean(fold_candles_entered)),
                    "_config": cfg,
                }
            )

        df = pd.DataFrame(rows)
        df = df.sort_values("sharpe_mean", ascending=False).reset_index(drop=True)
        return df
