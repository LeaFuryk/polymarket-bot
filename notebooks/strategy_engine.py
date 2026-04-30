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


TAKER_FEE_RATE = 0.072
BET_PCT = 0.02


def run_scaling(
    strategy: StrategyConfig,
    candle_data: list[dict],
    max_bid: float = 0.85,
    starting_balance: float = 1000.0,
) -> dict:
    """Back-test a StrategyConfig on a list of candles.

    Matches live bot logic exactly:
    - Bet size: 2% of current cash (compounding)
    - Fee: 7.2% taker fee on shares (same as Polymarket)
    - PnL: winning shares pay $1 each minus fees; losing bets lose full wager

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

    for candle in candle_data:
        truth: int = candle["truth"]
        snapshots: list[dict] = candle["snapshots"]
        candle_pnl = 0.0
        first_direction: int | None = None
        entries_made = 0
        # Track entries for fee-aware settlement (same as ModelRunner._bet_entries)
        candle_entries: list[tuple[float, float]] = []  # (ask, amount_usd)

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

            # Direction consistency
            if first_direction is not None and direction != first_direction:
                continue

            # Bet size: 2% of current cash (matches ModelRunner.BET_PCT)
            bet_amount = balance * BET_PCT
            if bet_amount < 0.01:
                continue

            # Fire entry
            entries_made += 1
            total_bets += 1
            if first_direction is None:
                first_direction = direction

            balance -= bet_amount
            candle_entries.append((ask, bet_amount))

        # Settle all entries at candle close (matches ModelRunner.handle_candle_close)
        if candle_entries:
            candles_entered += 1
            won = first_direction == truth
            total_cost = sum(amt for _, amt in candle_entries)

            if won:
                wins += 1
                total_net_shares = 0.0
                for ask, amt in candle_entries:
                    gross_shares = amt / ask
                    fee_shares = gross_shares * TAKER_FEE_RATE * ask * (1.0 - ask)
                    total_net_shares += gross_shares - fee_shares
                pnl = total_net_shares - total_cost  # shares pay $1 each
            else:
                pnl = -total_cost

            balance += total_cost + pnl  # restore cost then apply PnL
            candle_pnl = pnl

            # Update drawdown
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

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
        max_bid: Maximum allowed ask price.
    """

    def __init__(
        self,
        strategies: list[StrategyConfig],
        candle_data: list[dict],
        n_folds: int = 5,
        max_bid: float = 0.85,
    ) -> None:
        self.strategies = strategies
        self.candle_data = candle_data
        self.n_folds = n_folds
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
