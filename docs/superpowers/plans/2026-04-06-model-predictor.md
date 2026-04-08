# Model Predictor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load a pre-trained sklearn model from disk and expose a `predict(row) -> float` interface for AgentService to call after computing indicators.

**Architecture:** Hexagonal. `Predictor` port defines the contract. `JoblibPredictor` adapter loads model + scaler + feature columns from disk. AgentService receives a `Predictor` and calls it after each snapshot row is computed.

**Tech Stack:** Python 3.11, joblib, sklearn, pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `polybot/ports/predictor.py` | Create | `Predictor` protocol: `predict(row: dict) -> float` |
| `polybot/adapters/joblib_predictor.py` | Create | Load model/scaler/feature_cols from joblib files, predict |
| `polybot/services/agent_service.py` | Modify | Accept `Predictor`, call after indicator computation, log prediction |
| `polybot/__main__.py` | Modify | Wire JoblibPredictor on startup |
| `tests/polybot/test_joblib_predictor.py` | Create | Test adapter with mock model files |

---

### Task 1: Predictor port

**Files:**
- Create: `polybot/ports/predictor.py`

- [ ] **Step 1: Create the port**

```python
"""Port: model prediction interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Predictor(Protocol):
    """Predicts probability of UP outcome from an indicator row."""

    def predict(self, row: dict) -> float:
        """Return P(UP) in [0, 1]."""
        ...
```

- [ ] **Step 2: Commit**

```bash
git add polybot/ports/predictor.py
git commit -m "feat(polybot): add Predictor port"
```

---

### Task 2: JoblibPredictor adapter

**Files:**
- Create: `polybot/adapters/joblib_predictor.py`
- Create: `tests/polybot/test_joblib_predictor.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for JoblibPredictor."""

import tempfile
from pathlib import Path

import joblib
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from polybot.adapters.joblib_predictor import JoblibPredictor
from polybot.ports.predictor import Predictor


class TestJoblibPredictor:
    def _create_model_files(self, tmpdir: str) -> tuple[str, str, str]:
        """Create minimal model files for testing."""
        feat_cols = ["feat_a", "feat_b", "feat_c"]
        X = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0], [10.0, 11.0, 12.0]])
        y = np.array([0, 1, 0, 1])

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = LogisticRegression(random_state=42)
        model.fit(X_scaled, y)

        model_path = str(Path(tmpdir) / "model.joblib")
        scaler_path = str(Path(tmpdir) / "scaler.joblib")
        cols_path = str(Path(tmpdir) / "cols.joblib")

        joblib.dump(model, model_path)
        joblib.dump(scaler, scaler_path)
        joblib.dump(feat_cols, cols_path)

        return model_path, scaler_path, cols_path

    def test_implements_protocol(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            assert isinstance(pred, Predictor)

    def test_predict_returns_float_between_0_and_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            row = {"feat_a": 5.0, "feat_b": 6.0, "feat_c": 7.0, "extra_field": 999}
            prob = pred.predict(row)
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_predict_missing_feature_defaults_to_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            row = {"feat_a": 5.0}  # feat_b, feat_c missing
            prob = pred.predict(row)
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_predict_none_values_treated_as_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            row = {"feat_a": 5.0, "feat_b": None, "feat_c": 7.0}
            prob = pred.predict(row)
            assert isinstance(prob, float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_joblib_predictor.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement JoblibPredictor**

```python
"""Adapter: load sklearn model from joblib files and predict."""

from __future__ import annotations

import logging

import joblib
import numpy as np


class JoblibPredictor:
    """Loads a pre-trained sklearn model + scaler + feature columns from disk."""

    def __init__(
        self,
        model_path: str,
        scaler_path: str,
        feature_cols_path: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._model = joblib.load(model_path)
        self._scaler = joblib.load(scaler_path)
        self._feature_cols: list[str] = joblib.load(feature_cols_path)
        self._log.info(
            "Loaded model from %s (%d features)",
            model_path,
            len(self._feature_cols),
        )

    def predict(self, row: dict) -> float:
        """Return P(UP) from the indicator row."""
        features = np.array(
            [float(row.get(col) or 0.0) for col in self._feature_cols]
        ).reshape(1, -1)
        scaled = self._scaler.transform(features)
        return float(self._model.predict_proba(scaled)[0, 1])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_joblib_predictor.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/adapters/joblib_predictor.py tests/polybot/test_joblib_predictor.py
git commit -m "feat(polybot): add JoblibPredictor adapter"
```

---

### Task 3: Integrate Predictor into AgentService

**Files:**
- Modify: `polybot/services/agent_service.py`

- [ ] **Step 1: Add Predictor to AgentService**

Update `__init__` to accept an optional `Predictor`, call it in `_on_snapshot` after computing the row, add the prediction to the log line:

```python
"""Service: orchestrates message processing — indicators, portfolio, logging."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot

if TYPE_CHECKING:
    from polybot.ports.predictor import Predictor
    from polybot.services.indicator_service import IndicatorService
    from polybot.services.portfolio_service import PortfolioService


class AgentService:
    """Single entry point for all collector messages. Orchestrates indicator
    computation, portfolio updates, and logging."""

    def __init__(
        self,
        indicators: IndicatorService,
        portfolio: PortfolioService,
        predictor: Predictor | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._indicators = indicators
        self._portfolio = portfolio
        self._predictor = predictor
        self._log = logger or logging.getLogger(__name__)

    async def process(self, msg: dict) -> dict | None:
        """Decode raw WS message into a model and route to the appropriate handler.
        Returns indicator row for snapshots, None otherwise."""
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            snapshot = IndicatorSnapshot.from_dict(msg)
            return self._on_snapshot(snapshot)
        if msg_type == "candle_close":
            candle = CandleRecord.from_ws(msg)
            await self._on_candle_close(candle)
            return None
        return None

    def _on_snapshot(self, snapshot: IndicatorSnapshot) -> dict | None:
        """Compute indicators, run prediction, update portfolio prices."""
        row = self._indicators.on_snapshot(snapshot)
        if row is None:
            return None

        if snapshot.up_bids and snapshot.up_asks and snapshot.down_bids and snapshot.down_asks:
            up_mid = (snapshot.up_bids[0][0] + snapshot.up_asks[0][0]) / 2
            down_mid = (snapshot.down_bids[0][0] + snapshot.down_asks[0][0]) / 2
            self._portfolio.update_prices(up_mid, down_mid)

        prediction = None
        if self._predictor is not None:
            prediction = self._predictor.predict(row)

        self._log.info(
            "📊 %s | elapsed=%.0f%% | BTC $%.2f | P(UP)=%s | cash=$%.2f",
            snapshot.candle_id,
            snapshot.elapsed_pct * 100,
            snapshot.btc_price,
            f"{prediction:.2f}" if prediction is not None else "n/a",
            self._portfolio.state.cash,
        )
        return row

    async def _on_candle_close(self, candle: CandleRecord) -> None:
        """Settle portfolio, then update indicator history."""
        self._portfolio.settle(candle.outcome)
        await self._indicators.on_candle_close(candle)
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass (predictor is optional, existing tests don't set it)

- [ ] **Step 3: Commit**

```bash
git add polybot/services/agent_service.py
git commit -m "feat(polybot): AgentService accepts optional Predictor"
```

---

### Task 4: Wire in __main__.py

**Files:**
- Modify: `polybot/__main__.py`

- [ ] **Step 1: Add JoblibPredictor to startup**

Add after `agent = AgentService(...)`:

```python
from polybot.adapters.joblib_predictor import JoblibPredictor

# ... in main():

    predictor = None
    model_path = os.environ.get("POLYBOT_MODEL_PATH", "models/logistic_v1.joblib")
    if Path(model_path).exists():
        predictor = JoblibPredictor(
            model_path=model_path,
            scaler_path=os.environ.get("POLYBOT_SCALER_PATH", "models/scaler_v1.joblib"),
            feature_cols_path=os.environ.get("POLYBOT_FEATURES_PATH", "models/feature_cols_v1.joblib"),
        )

    agent = AgentService(indicators=indicators, portfolio=portfolio, predictor=predictor)
```

- [ ] **Step 2: Run full test suite + lint**

Run: `uv run pytest tests/ -v && uv run ruff check .`
Expected: All pass, lint clean

- [ ] **Step 3: Commit**

```bash
git add polybot/__main__.py
git commit -m "feat(polybot): wire JoblibPredictor on startup"
```
