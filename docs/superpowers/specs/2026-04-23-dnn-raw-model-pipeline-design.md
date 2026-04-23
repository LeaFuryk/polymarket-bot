# DNN-Raw Model Pipeline Design

**Date:** 2026-04-23
**Status:** Draft
**Notion task:** [Add DNN-raw model to trading pipeline](https://www.notion.so/34b7e505e99b8172a3f0e45bed04820d)

## Problem

The trading bot runs three sklearn-based models (LR, RF, XGB) that consume 60 pre-computed technical indicators. Learning curve experiments show a custom Deep Neural Network trained on 11 raw market columns achieves the best Brier score (0.164) of all models, meaning its probability calibration is superior for confidence-gated strategies. Adding DNN-raw as a 4th model diversifies the ensemble and exploits a fundamentally different feature space.

## Success Criteria

- DNN model achieves Brier score <= 0.17 on held-out data (matching learning curve evidence)
- All 260+ existing tests still pass
- DNN inference latency < 10ms per snapshot (CPU)
- New code coverage > 80%
- DNN participates in live trading alongside LR/RF/XGB with independent portfolio

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture discovery | R&D in notebook, then export | Task requires exploring temporal conv, attention, residual — notebook is the right venue |
| Temporal vs. single-snapshot | Support both, R&D decides | DnnPredictor supports optional internal snapshot buffer; toggled by `temporal` flag |
| libomp/XGBoost conflict | In-process with OMP_NUM_THREADS=1 | Small model (~15k params), CPU-only, single-threaded BLAS eliminates OpenMP contention |
| Indicator pipeline | No changes — DNN picks raw cols from existing row dict | IndicatorService already runs for LR/RF/XGB; raw columns (btc_price, orderbook, etc.) are present in the same row |
| Integration approach | Minimal adapter (Approach A) | Zero changes to AgentService, ModelRunner, IndicatorService, Predictor protocol |
| PyTorch dependency | Optional (`[dnn]` extra) with CPU-only wheels | Keeps base install lean; DNN silently skipped if torch unavailable |

## Architecture

### Overview

```
snapshot -> IndicatorService -> row dict (60+ fields)
                                    |
                  ModelRunner[DNN].handle_snapshot(row, snapshot)
                                    |
                  DnnPredictor.predict(row) -> picks 11 raw cols -> P(UP)
```

No changes to the existing pipeline. The DNN plugs in as a 4th ModelRunner via MODEL_CONFIGS, using a new `DnnPredictor` adapter that implements the existing `Predictor` protocol.

### Raw Input Columns (11)

`btc_price`, `elapsed_pct`, `market_volume`, `up_best_bid`, `up_best_ask`, `up_bid_depth`, `up_ask_depth`, `down_best_bid`, `down_best_ask`, `down_bid_depth`, `down_ask_depth`

### DnnPredictor Adapter

**File:** `polybot/adapters/dnn_predictor.py`

```python
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import torch

class DnnPredictor(Predictor):
    def __init__(
        self,
        model_path: str,
        feature_cols_path: str,
        scaler_path: str | None = None,
        temporal: bool = False,
        logger: logging.Logger | None = None,
    ) -> None: ...

    def predict(self, row: dict) -> float: ...
```

**Constructor:**
- Loads PyTorch model via `torch.load(model_path, weights_only=False)`, sets to `eval()` mode
- Loads feature column names from joblib (consistent with JoblibPredictor pattern)
- Optionally loads a fitted scaler (R&D decides if normalization helps)
- `temporal` flag controls inference mode

**Single-snapshot mode (`temporal=False`):**
- Extract 11 features from `row` dict (default 0.0 for missing)
- Optional scaling
- Forward pass on `(1, 11)` tensor
- Sigmoid output -> P(UP)

**Temporal mode (`temporal=True`):**
- Maintains `_buffer: list[list[float]]` of snapshots within current candle
- Tracks `_current_candle_id` from `row["candle_id"]`
- On candle_id change: reset buffer
- Append current 11 features to buffer
- Pad/truncate to fixed sequence length (e.g., 50 snapshots)
- Forward pass on `(1, seq_len, 11)` tensor -> P(UP)

**Output:** Always `float` in `[0, 1]`.

### Startup Wiring

**File:** `polybot/__main__.py`

```python
try:
    from polybot.adapters.dnn_predictor import DnnPredictor
    _HAS_DNN = True
except ImportError:
    _HAS_DNN = False

DNN_CONFIG = {
    "name": "DNN",
    "model_path": "models/dnn_v1.pt",
    "scaler_path": "models/dnn_scaler_v1.joblib",
    "features_path": "models/dnn_feature_cols_v1.joblib",
    "strategy_path": "data/optimal_strategy_dnn.json",
    "bets_dir": "data/bets/DNN",
    "temporal": False,  # set True if R&D picks a temporal architecture
}
```

**Logic:**
- After the existing LR/RF/XGB loop, check `_HAS_DNN` and whether model files exist on disk
- If available: create `DnnPredictor`, wrap in `ModelRunner` with its own `PortfolioService` + `TradingStrategy`, append to `runners`
- If unavailable: silently skip, other 3 models run as before
- `AgentService` receives the full `runners` list and fans out to all

### Dependency Management

**`pyproject.toml`:**
```toml
[project.optional-dependencies]
dnn = ["torch>=2.0,<3.0"]
```

**Install:**
```bash
uv pip install -e ".[dnn]" --extra-index-url https://download.pytorch.org/whl/cpu
```

**Module guard:** `DnnPredictor` sets `OMP_NUM_THREADS=1` and `MKL_NUM_THREADS=1` via `os.environ.setdefault()` before importing torch, so user overrides are respected.

## Notebook Pipeline

### `notebooks/dnn/01_architecture.ipynb` — R&D Exploration

- Loads `data/latest_features.jsonl`, extracts 11 raw columns
- Experiments with architectures:
  - **Residual MLP** (baseline): Input(11) -> hidden layers with skip connections
  - **Temporal Conv1D**: Input(seq_len, 11) -> causal convolutions -> pooling -> P(UP)
  - **Attention-based**: Input(seq_len, 11) -> self-attention -> classification head
- Compares accuracy, Brier score, training time, inference latency
- Documents winning architecture with rationale
- Exploratory — no exported artifacts

### `notebooks/dnn/02_export.ipynb` — Final Training + Export

- Trains chosen architecture on full dataset (80/20 split, same as LR/RF/XGB)
- Exports to `models/`:
  - `dnn_v1.pt` — PyTorch model state dict
  - `dnn_scaler_v1.joblib` — optional fitted scaler
  - `dnn_feature_cols_v1.joblib` — list of 11 raw column names
- Logs final metrics: accuracy, Brier, F1, calibration curve

### `notebooks/dnn/03_strategy.ipynb` — Strategy Optimization

- Uses shared `strategy_engine.py` (grid search + walk-forward, same as RF/XGB)
- Feeds DNN predictions into strategy evaluator
- Exports to `data/optimal_strategy_dnn.json` (same format as other models)
- Selects best strategy by Sharpe ratio

### `data/optimal_features_dnn.json`

All 11 raw columns — no feature selection needed. File maintains consistent format:
```json
{
  "model": "dnn_raw",
  "features": ["btc_price", "elapsed_pct", "market_volume", ...],
  "n_features": 11,
  "selection_method": "raw_inputs"
}
```

## Testing Strategy

### `tests/polybot/test_dnn_predictor.py`

- **Skip guard:** `torch = pytest.importorskip("torch")` at module level
- Single-snapshot mode: mock torch model, verify predict(row) returns float in [0,1], picks only 11 raw columns
- Temporal mode: verify buffer accumulates, resets on candle_id change, pads/truncates to fixed length
- Scaler integration: test with and without optional scaler
- Missing columns: verify defaults to 0.0

### `tests/polybot/test_dnn_integration.py`

- Full pipeline: DnnPredictor -> ModelRunner -> entry/settlement flow
- Uses tiny torch model (e.g., `nn.Linear(11, 1)` with fixed weights)
- Verifies DNN participates in AgentService fan-out alongside mocked LR/RF/XGB
- Confirms entries and settlements broadcast correctly

### `tests/notebooks/test_dnn_export.py`

- Exported model loads and produces valid output shape
- Feature cols file contains exactly 11 expected columns
- Strategy JSON has required fields (entry_points, min_confidence, etc.)

### CI

- Add matrix entry or separate job installing `.[dnn]` with CPU-only wheels
- DNN tests skipped via `pytest.importorskip("torch")` in base CI job
- Existing CI jobs unchanged

## File Inventory

### New files

| File | Purpose | Est. LOC |
|------|---------|----------|
| `polybot/adapters/dnn_predictor.py` | DnnPredictor adapter | ~80 |
| `notebooks/dnn/01_architecture.ipynb` | R&D: architecture exploration | — |
| `notebooks/dnn/02_export.ipynb` | Train + export to models/ | — |
| `notebooks/dnn/03_strategy.ipynb` | Grid search + walk-forward | — |
| `data/optimal_features_dnn.json` | 11 raw feature columns | ~10 |
| `data/optimal_strategy_dnn.json` | Best strategy config | ~15 |
| `models/dnn_v1.pt` | Trained model state dict | — |
| `models/dnn_scaler_v1.joblib` | Optional scaler | — |
| `models/dnn_feature_cols_v1.joblib` | Feature column names | — |
| `tests/polybot/test_dnn_predictor.py` | Unit tests | ~120 |
| `tests/polybot/test_dnn_integration.py` | Integration tests | ~80 |
| `tests/notebooks/test_dnn_export.py` | Export validation | ~40 |

### Modified files

| File | Change | Est. LOC delta |
|------|--------|----------------|
| `polybot/__main__.py` | Conditional DNN runner | ~25 |
| `pyproject.toml` | Optional `[dnn]` dependency | ~3 |
| `.github/workflows/ci.yml` | DNN test matrix entry | ~10 |
| `CHANGELOG.md` | Document under [Unreleased] | ~5 |

### Unchanged files

`AgentService`, `ModelRunner`, `IndicatorService`, `PortfolioService`, `Predictor` protocol, `TradingStrategy`, `JoblibPredictor`, all existing tests.
