"""Shared strategy engine for notebook strategy selection pipelines.

Provides:
- StrategyConfig: dataclass describing an edge-based trading strategy
- StrategyGrid: generates all valid combinations from parameter ranges
- run_scaling: back-tests a StrategyConfig on candle data
- WalkForwardEvaluator: walk-forward cross-validation across strategy grid
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# StrategyConfig
# ---------------------------------------------------------------------------


@dataclass
class StrategyConfig:
    """An edge-based trading strategy configuration.

    Edge = max(prob, 1-prob) - ask_price.  When edge >= min_edge the model
    identifies the outcome more confidently than the market price implies.

    Args:
        min_edge: Minimum edge (confidence minus ask) required to enter.
        max_entries: Maximum number of scale-in entries per candle.
        name: Display name. Auto-generated from parameters if empty.
    """

    min_edge: float
    max_entries: int = 1
    name: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"edge>={self.min_edge:.2f} x{self.max_entries}"


# ---------------------------------------------------------------------------
# StrategyGrid
# ---------------------------------------------------------------------------


class StrategyGrid:
    """Generate strategy configs to evaluate.

    min_edge is fixed at 0.05 (edge >= 0.05 is profitable across all models).
    Only max_entries varies.
    """

    def __init__(
        self,
        min_edge: float = 0.05,
        max_entries_values: list[int] | None = None,
    ) -> None:
        self.min_edge = min_edge
        if max_entries_values is None:
            max_entries_values = [1, 2]
        self.max_entries_values = max_entries_values

    def generate(self) -> list[StrategyConfig]:
        """Return one config per max_entries value, all with fixed min_edge."""
        return [StrategyConfig(min_edge=self.min_edge, max_entries=m) for m in self.max_entries_values]


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

    For each snapshot the engine computes:
        confidence = max(prob, 1-prob)
        direction  = 1 if prob >= 0.5 else 0
        ask        = up_ask if direction==1 else down_ask
        edge       = confidence - ask

    An entry fires when:
        - edge >= strategy.min_edge
        - entries_made < strategy.max_entries
        - direction agrees with the first entry (direction lock)

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

    for candle in candle_data:
        truth: int = candle["truth"]
        snapshots: list[dict] = candle["snapshots"]
        candle_pnl = 0.0
        first_direction: int | None = None  # direction locked on first entry
        entries_made = 0

        for snap in snapshots:
            prob: float = snap["prob"]
            up_ask: float = snap["up_ask"]
            down_ask: float = snap["down_ask"]

            confidence = max(prob, 1.0 - prob)
            direction = 1 if prob >= 0.5 else 0
            ask = up_ask if direction == 1 else down_ask

            # Ask price filter (before edge computation to avoid None arithmetic)
            if ask is None or not np.isfinite(ask) or ask <= 0 or ask >= max_bid:
                continue

            edge = confidence - ask

            # Edge threshold
            if edge < strategy.min_edge - 1e-9:
                continue

            # Max entries cap
            if entries_made >= strategy.max_entries:
                continue

            # Direction consistency: must agree with first entry direction
            if first_direction is not None and direction != first_direction:
                continue

            # Bankroll floor guard
            if balance < bet_per_entry:
                continue

            # Fire entry
            entries_made += 1
            total_bets += 1
            if first_direction is None:
                first_direction = direction

            # Settle bet
            if direction == truth:
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

        if entries_made > 0:
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
