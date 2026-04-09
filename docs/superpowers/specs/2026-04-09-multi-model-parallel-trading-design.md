# Multi-Model Parallel Trading

Run LR, RF, and XGBoost in parallel on the same market data stream, each with independent portfolios and strategies, broadcasting trading events for the dashboard.

## Context

The bot currently runs a single model (configurable via env vars). Notebook evaluation shows XGBoost leads on return (+27.1%), RF on win rate (70.8%), and LR on stability. Running all three in parallel provides live comparison data and sets up the dashboard to show side-by-side performance.

## Architecture

### New: `TradingStrategy` dataclass

`polybot/domain/trading_strategy.py`

Loaded from `data/optimal_strategy_*.json`. Immutable config per model.

```python
@dataclass(frozen=True)
class TradingStrategy:
    name: str                          # "LogisticRegression", "RandomForest", "XGBoost"
    entry_points: list[tuple[float, int]]  # [(0.05, 3), (0.50, 3)]
    min_confidence: float              # 0.0, 0.6, 0.7

    @classmethod
    def from_json(cls, path: str, name: str) -> TradingStrategy: ...
```

### New: `ModelRunner`

`polybot/services/model_runner.py`

Owns one model's complete trading lifecycle. Uses the Strategy pattern — the `TradingStrategy` dataclass drives entry decisions.

**Dependencies (all injected):**
- `name: str` — display name ("LogisticRegression", "RandomForest", "XGBoost")
- `predictor: Predictor` — the loaded model (existing port)
- `portfolio: PortfolioService` — its own $1k portfolio
- `strategy: TradingStrategy` — loaded from JSON
- `bet_store: BetStore` — its own JSONL file (`data/bets/{name}/`)
- `broadcaster: MessageRelay` — shared broadcaster (existing port)

**Methods:**
- `handle_snapshot(row: dict, snapshot: IndicatorSnapshot) -> None` — predict, evaluate entry, broadcast `model_entry` if triggered
- `handle_candle_close(candle: CandleRecord) -> None` — settle portfolio, record bet, broadcast `model_settlement`
- `handle_correction(candle: CandleRecord) -> None` — reverse and re-settle if outcome changed

**Per-candle state** (same as current AgentService, moved here):
- `_predictions`, `_first_direction`, `_entries_made`, `_next_checkpoint`, `_bet_entries`, `_current_candle_id`, `_cash_before_bet`

**Entry logic:**
- Uses `strategy.entry_points` instead of hardcoded `ENTRY_CHECKPOINTS`
- Uses `strategy.min_confidence` to gate entries (if confidence < threshold, skip)
- Otherwise identical to current `AgentService._evaluate_entry()`

### Modified: `AgentService`

Becomes a thin orchestrator. No longer owns trading state or strategy logic.

**Dependencies:**
- `indicators: IndicatorService` — shared, compute once per snapshot
- `runners: list[ModelRunner]` — the 3 model runners

**Methods:**
- `process(msg: dict)` — routes messages:
  - `snapshot`: compute indicators via `IndicatorService`, pass `row` + `snapshot` to each runner's `handle_snapshot()`
  - `candle_close`: call each runner's `handle_candle_close()`, then update indicators
  - `candle_correction`: call each runner's `handle_correction()`

### Modified: `__main__.py`

Creates 3 `ModelRunner` instances, each with:

| Model | Predictor files | Strategy file | Bet dir |
|-------|----------------|---------------|---------|
| LogisticRegression | `logistic_v1.joblib`, `scaler_v1.joblib`, `feature_cols_v1.joblib` | `data/optimal_strategy_lr.json` | `data/bets/LogisticRegression/` |
| RandomForest | `rf_v1.joblib`, `rf_scaler_v1.joblib`, `rf_feature_cols_v1.joblib` | `data/optimal_strategy_rf.json` | `data/bets/RandomForest/` |
| XGBoost | `xgb_calibrator_v1.joblib`, `xgb_scaler_v1.joblib`, `xgb_feature_cols_v1.joblib` | `data/optimal_strategy_xgb.json` | `data/bets/XGBoost/` |

Each gets its own `PortfolioService(initial_cash=1000.0)` and `JsonlBetStore`.

All share: `IndicatorService`, `Broadcaster`, `PolybotServer`, `CollectorClient`.

### Broadcast Events

Two new event types from `ModelRunner`, sent via the shared `Broadcaster`:

**`model_entry`** — when a position is opened:
```json
{
    "type": "model_entry",
    "model": "XGBoost",
    "candle_id": "btc-updown-5m-1775760000",
    "direction": "UP",
    "price": 0.67,
    "amount_usd": 20.0,
    "confidence": 0.73,
    "inference_ms": 0.024,
    "checkpoint": 1,
    "elapsed_pct": 0.058,
    "timestamp": 1775760123.45
}
```

**`model_settlement`** — when candle closes and bet resolves:
```json
{
    "type": "model_settlement",
    "model": "XGBoost",
    "candle_id": "btc-updown-5m-1775760000",
    "outcome": "UP",
    "direction": "UP",
    "won": true,
    "entries": [{"price": 0.67, "amount_usd": 20.0, "elapsed_pct": 0.058, "confidence": 0.73, "checkpoint": 1}],
    "pnl": 12.50,
    "cash": 1012.50,
    "wins": 5,
    "losses": 3,
    "timestamp": 1775760300.0
}
```

Existing collector pass-through events (`snapshot`, `candle_close`, `candle_correction`) are unchanged and still broadcast as-is for the dashboard's price chart and bet timeline.

### Initial State

When a dashboard client connects, `PolybotServer` sends an `initial_state` message. Updated to include all 3 portfolios:

```json
{
    "type": "initial_state",
    "candles": [...],
    "snapshots_so_far": [...],
    "portfolios": {
        "LogisticRegression": {"wins": 5, "losses": 3, "cash": 1012.50, ...},
        "RandomForest": {"wins": 6, "losses": 2, "cash": 1050.00, ...},
        "XGBoost": {"wins": 7, "losses": 1, "cash": 1080.00, ...}
    }
}
```

### Session Summary

On shutdown, each runner's portfolio summary is saved to `data/sessions.jsonl` with the model name:

```json
{"model": "XGBoost", "wins": 170, "losses": 114, "net_pnl": 177.70, ...}
```

## Unchanged

- `IndicatorService` — shared, computes indicators once per snapshot
- `PortfolioService` — unchanged, one instance per runner
- `Predictor` port / `JoblibPredictor` adapter — unchanged
- `Broadcaster` / `PolybotServer` — unchanged (single port 8766)
- `CollectorClient` — unchanged
- Collector process — not touched

## File Changes

| File | Action |
|------|--------|
| `polybot/domain/trading_strategy.py` | **NEW** |
| `polybot/services/model_runner.py` | **NEW** |
| `polybot/services/agent_service.py` | **MODIFY** — strip trading logic, become orchestrator |
| `polybot/__main__.py` | **MODIFY** — wire 3 runners |

## Testing

- Unit test `ModelRunner` with mock predictor, portfolio, broadcaster
- Unit test `TradingStrategy.from_json()` loading
- Unit test `AgentService` fans out to multiple runners
- Integration test: 3 runners process same snapshot, each makes independent decisions
- Verify existing tests still pass (AgentService interface changes)

## Out of Scope

- Dashboard UI (next iteration)
- Live execution / real money (paper trading only)
- Model hot-swapping at runtime
- Ensemble voting across models
