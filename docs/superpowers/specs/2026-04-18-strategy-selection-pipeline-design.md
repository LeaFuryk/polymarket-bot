# Strategy Selection Pipeline Redesign

**Date:** 2026-04-18
**Branch:** `feat/feature-selection-pipeline`
**Scope:** `notebooks/strategy_engine.py` (new), `notebooks/{lr,rf,xgb}/03_strategy.ipynb` (rewrite)

## Problem

The current `03_strategy` notebooks have three weaknesses:

1. **Tiny search space** — 11 hardcoded strategies with coarse parameters
2. **Naive selection** — picks strategy with highest final balance, ignoring risk
3. **Single eval window** — one 80/20 split; strategy may overfit to that regime

Additionally, `run_scaling()` and the strategy grid are copy-pasted identically across all 3 notebooks.

## Solution

Extract a shared strategy engine module. Replace the manual list with a parametric grid search (~1,700 combinations). Add walk-forward validation (5 folds). Select by mean Sharpe ratio across folds. Display a full comparison table with all metrics.

## Architecture

### New File: `notebooks/strategy_engine.py`

Three components:

#### 1. `StrategyConfig` (dataclass)

```python
@dataclass
class StrategyConfig:
    entry_points: list[tuple[float, int]]  # [(min_elapsed, n_consecutive), ...]
    min_confidence: float
    name: str  # auto-generated from params
```

#### 2. `StrategyGrid`

Generates all valid `StrategyConfig` combinations from parameter ranges.

**Constructor parameters:**
- `elapsed_values: list[float]` — default `[0.05, 0.10, ..., 0.80]` (16 values)
- `n_consecutive_values: list[int]` — default `[1, 2, 3, 4, 5]`
- `confidence_values: list[float]` — default `[0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]` (7 values)
- `max_entries: int` — 1 or 2 (default 2, generates both 1-entry and 2-entry strategies)

**Filtering rules:**
- For 2-entry strategies: `elapsed_2 > elapsed_1 + 0.10` (minimum 10% gap)
- No entry with `elapsed > 0.80` (too close to candle end)

**Expected output:** ~1,700 strategies (480 single-entry + ~1,200 two-entry).

#### 3. `WalkForwardEvaluator`

Runs all strategies across multiple walk-forward folds and ranks by Sharpe.

**Constructor parameters:**
- `strategies: list[StrategyConfig]`
- `candle_data: list[dict]` — the `all_cd` prediction data
- `n_folds: int` — default 5
- `bet_per_entry: float` — default 10.0
- `max_bid: float` — default 0.85

**Walk-forward folds (expanding window on candle_id boundaries):**

```
Fold 1: Eval candles [40%-52%]   (~485 candles)
Fold 2: Eval candles [52%-64%]   (~485 candles)
Fold 3: Eval candles [64%-76%]   (~485 candles)
Fold 4: Eval candles [76%-88%]   (~485 candles)
Fold 5: Eval candles [88%-100%]  (~485 candles)
```

Splits are always on candle_id boundaries — all snapshots for a given candle_id stay in the same fold.

Walk-forward applies to the **strategy simulation only**, not model retraining. The model is trained once on 80% of data (same as current). Walk-forward tests whether strategy parameters generalize across different evaluation windows.

**`run()` returns:** `pd.DataFrame` with columns:
- `strategy` (name)
- `sharpe_mean`, `sharpe_std`
- `return_mean`, `return_std`
- `win_rate_mean`, `win_rate_std`
- `max_dd_mean`, `max_dd_std`
- `total_bets_mean`
- `candles_entered_mean`
- Per-fold detail columns for drill-down

**Selection:** Best strategy = highest `sharpe_mean`.

#### 4. `run_scaling()` (updated)

Stays mostly as-is but returns additional data:
- `per_candle_pnl: list[float]` — PnL for each candle (0.0 if no entry). Feeds into Sharpe calculation.
- All existing fields remain (`balance`, `history`, `total_bets`, `wins`, `win_rate`, `return_pct`, `max_dd`).

### Sharpe Ratio Calculation

```python
sharpe = mean(per_candle_pnl) / std(per_candle_pnl)
```

Computed over all candles in the eval fold (including 0.0 for candles with no entry — sitting out is a decision with zero return).

## Notebook Changes

### What Each `03_strategy.ipynb` Becomes

1. **Imports + config** — load `strategy_engine`, model config, features
2. **Train model on 80%** — same as now (model-specific)
3. **Build per-snapshot predictions** — same as now, produces `all_cd` list
4. **Define grid** — `StrategyGrid(...)` with default ranges (overridable per-model)
5. **Run walk-forward** — `WalkForwardEvaluator(grid, all_cd, n_folds=5).run()` returns DataFrame
6. **Comparison table** — top 15 by mean Sharpe, all metrics shown
7. **Equity curves** — two-panel chart: all strategies overlay + top 3 by Sharpe (same style as current)
8. **Save best** — same JSON format + new fields
9. **Forward-test** — same as now, reporting only

### Removed From Notebooks
- `run_scaling()` function (in `strategy_engine.py`)
- Hardcoded `strategies` list (replaced by `StrategyGrid`)
- Manual iteration + print loop (replaced by evaluator)

### Stays In Notebooks
- Model training (model-specific)
- Prediction building (model-specific `feat_cols`, `predict_proba`)
- Charts
- Forward-test section
- Save to JSON

## JSON Output Format

Existing fields preserved for backwards compatibility. New fields added:

```json
{
  "model": "lr",
  "strategy": "2x e30%+e55% conf>0.55",
  "entry_points": [[0.30, 3], [0.55, 3]],
  "min_confidence": 0.55,
  "sharpe_mean": 1.23,
  "sharpe_std": 0.18,
  "win_rate": 0.69,
  "return_pct": 18.2,
  "max_drawdown": 0.22,
  "n_folds": 5,
  "grid_size": 1700,
  "eval_method": "walk_forward_5_folds",
  "eval_candles": 809,
  "total_bets": 1140,
  "created_at": "2026-04-18T..."
}
```

`eval_method` changes from `"validation_split_20pct"` to `"walk_forward_5_folds"`.

All numeric fields (`win_rate`, `return_pct`, `max_drawdown`, `total_bets`) are **means across folds**, consistent with `sharpe_mean`. The `eval_method` field signals this.

## Comparison Table Format

```
Strategy                | Sharpe (u +/- s) | Return (u) | WR (u) | MaxDD (u) | Bets (u)
2x e30%+e55% conf>0.55 |      1.23 +/- 0.18 |    +18.2%  | 69.1%  |    22.3%  |   1,140
1x e25%                 |      1.10 +/- 0.22 |    +14.7%  | 67.8%  |    18.1%  |     760
...top 15 shown...
```

## Constants

- `MAX_BID = 0.85` — ask price ceiling (unchanged)
- `BET_PER_ENTRY = 10.0` — flat bet size (unchanged)
- `STARTING_BALANCE = 1000.0` (unchanged)
- `N_FOLDS = 5` (new)
- `MIN_ELAPSED_GAP = 0.10` — minimum gap between entry points in 2-entry strategies (new)
- `MAX_ELAPSED = 0.80` — no entries after 80% elapsed (new)

## What This Does NOT Change

- Model training pipeline (`01_feature_selection`, `02_export`)
- Feature engineering (`data/01_build_features`)
- Production code (`polybot/`, `collector/`)
- Bet sizing (stays flat $10)
- `MAX_BID` threshold
- Forward-test section (stays as reporting-only confirmation)
