# Multi-Model Parallel Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run LR, RF, and XGBoost in parallel on the same market data, each with independent portfolios and strategies, broadcasting trading events for the dashboard.

**Architecture:** A new `ModelRunner` class encapsulates one model's trading lifecycle (predictor + portfolio + strategy + bet store + broadcaster). `AgentService` becomes a thin orchestrator that computes indicators once and fans out to 3 runners. A `TradingStrategy` dataclass loads entry config from JSON.

**Tech Stack:** Python 3.11+, asyncio, joblib, websockets, pytest

**Spec:** `docs/superpowers/specs/2026-04-09-multi-model-parallel-trading-design.md`

---

### Task 1: Create `TradingStrategy` domain model

**Files:**
- Create: `polybot/domain/trading_strategy.py`
- Test: `tests/polybot/test_trading_strategy.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for TradingStrategy domain model."""

import json
import tempfile
from pathlib import Path

import pytest

from polybot.domain.trading_strategy import TradingStrategy


class TestTradingStrategy:
    def test_from_json_loads_fields(self, tmp_path):
        config = {
            "model": "xgb",
            "strategy": "2x e5%+e50%",
            "entry_points": [[0.05, 3], [0.50, 3]],
            "min_confidence": 0.6,
            "win_rate": 0.70,
            "return_pct": 27.1,
        }
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="XGBoost")
        assert s.name == "XGBoost"
        assert s.entry_points == [(0.05, 3), (0.50, 3)]
        assert s.min_confidence == 0.6

    def test_from_json_defaults_min_confidence(self, tmp_path):
        config = {"entry_points": [[0.05, 3]], "strategy": "1x e5%"}
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="LR")
        assert s.min_confidence == 0.0

    def test_frozen(self, tmp_path):
        config = {"entry_points": [[0.05, 3]], "min_confidence": 0.0, "strategy": "1x"}
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="LR")
        with pytest.raises(AttributeError):
            s.name = "changed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_trading_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'polybot.domain.trading_strategy'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Domain model for trading strategy configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TradingStrategy:
    """Immutable strategy config loaded from optimal_strategy_*.json."""

    name: str
    entry_points: tuple[tuple[float, int], ...]
    min_confidence: float

    @classmethod
    def from_json(cls, path: str, name: str) -> TradingStrategy:
        with open(path) as f:
            config = json.load(f)
        return cls(
            name=name,
            entry_points=tuple(
                (float(ep[0]), int(ep[1])) for ep in config["entry_points"]
            ),
            min_confidence=float(config.get("min_confidence", 0.0)),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_trading_strategy.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add polybot/domain/trading_strategy.py tests/polybot/test_trading_strategy.py
git commit -m "feat: add TradingStrategy domain model"
```

---

### Task 2: Create `ModelRunner`

**Files:**
- Create: `polybot/services/model_runner.py`
- Test: `tests/polybot/test_model_runner.py`

- [ ] **Step 1: Write the failing test for handle_snapshot entry**

```python
"""Tests for ModelRunner."""

import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.domain.bet_record import BetEntry
from polybot.domain.trading_strategy import TradingStrategy
from polybot.services.model_runner import ModelRunner
from polybot.services.portfolio_service import PortfolioService
from polybot_data.services.indicator_engine import IndicatorSnapshot


def _make_strategy(entry_points=((0.05, 3),), min_confidence=0.0):
    return TradingStrategy(
        name="TestModel",
        entry_points=tuple(entry_points),
        min_confidence=min_confidence,
    )


def _make_snapshot(candle_id="c1", elapsed=0.06, up_ask=0.60, down_ask=0.40):
    return IndicatorSnapshot(
        candle_id=candle_id,
        timestamp=time.time(),
        elapsed_pct=elapsed,
        btc_price=70000.0,
        btc_bid=69999.0,
        btc_ask=70001.0,
        up_bids=[(0.58, 100)],
        up_asks=[(up_ask, 100)],
        down_bids=[(0.38, 100)],
        down_asks=[(down_ask, 100)],
        market_volume=50.0,
    )


def _make_runner(strategy=None, predictor=None):
    if strategy is None:
        strategy = _make_strategy()
    if predictor is None:
        predictor = MagicMock()
        predictor.predict.return_value = 0.7  # predict UP
    portfolio = PortfolioService(initial_cash=1000.0)
    bet_store = AsyncMock()
    broadcaster = AsyncMock()
    return ModelRunner(
        name="TestModel",
        predictor=predictor,
        portfolio=portfolio,
        strategy=strategy,
        bet_store=bet_store,
        broadcaster=broadcaster,
    )


class TestHandleSnapshot:
    def test_no_entry_before_checkpoint_elapsed(self):
        runner = _make_runner()
        row = {"feat1": 1.0}
        snapshot = _make_snapshot(elapsed=0.01)  # before 5%
        runner.handle_snapshot(row, snapshot)
        assert runner._entries_made == 0

    def test_entry_after_3_consecutive_predictions(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        # Need 3 consecutive
        runner.handle_snapshot(row, snap)
        runner.handle_snapshot(row, snap)
        runner.handle_snapshot(row, snap)
        assert runner._entries_made == 1

    def test_entry_broadcasts_model_entry(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(3):
            runner.handle_snapshot(row, snap)
        runner._broadcaster.broadcast_json.assert_called_once()
        msg = runner._broadcaster.broadcast_json.call_args[0][0]
        assert msg["type"] == "model_entry"
        assert msg["model"] == "TestModel"
        assert msg["direction"] == "UP"
        assert "inference_ms" in msg

    def test_min_confidence_filters_entry(self):
        predictor = MagicMock()
        predictor.predict.return_value = 0.52  # confidence = 0.52, below 0.6
        strategy = _make_strategy(min_confidence=0.6)
        runner = _make_runner(strategy=strategy, predictor=predictor)
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(10):
            runner.handle_snapshot(row, snap)
        assert runner._entries_made == 0

    def test_max_bid_filters_entry(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06, up_ask=0.90)  # above MAX_BID
        row = {"feat1": 1.0}
        for _ in range(3):
            runner.handle_snapshot(row, snap)
        assert runner._entries_made == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_model_runner.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the ModelRunner implementation**

```python
"""Service: per-model trading lifecycle — predict, enter, settle, broadcast."""

from __future__ import annotations

import logging
import time as _time
from dataclasses import asdict
from typing import TYPE_CHECKING

from polybot.domain.bet_record import BetEntry, BetRecord

if TYPE_CHECKING:
    from polybot.domain.trading_strategy import TradingStrategy
    from polybot.ports.bet_store import BetStore
    from polybot.ports.message_relay import MessageRelay
    from polybot.ports.predictor import Predictor
    from polybot.services.portfolio_service import PortfolioService
    from polybot_data.domain.collection import CandleRecord
    from polybot_data.services.indicator_engine import IndicatorSnapshot

MAX_BID = 0.85
BET_PCT = 0.02


class ModelRunner:
    """Owns one model's complete trading lifecycle.

    Uses the Strategy pattern: the TradingStrategy dataclass drives entry
    decisions (checkpoints, confidence thresholds).
    """

    def __init__(
        self,
        name: str,
        predictor: Predictor,
        portfolio: PortfolioService,
        strategy: TradingStrategy,
        bet_store: BetStore,
        broadcaster: MessageRelay,
        logger: logging.Logger | None = None,
    ) -> None:
        self._name = name
        self._predictor = predictor
        self._portfolio = portfolio
        self._strategy = strategy
        self._bet_store = bet_store
        self._broadcaster = broadcaster
        self._log = logger or logging.getLogger(f"{__name__}.{name}")

        # Per-candle state
        self._predictions: list[int] = []
        self._first_direction: str | None = None
        self._entries_made: int = 0
        self._next_checkpoint: int = 0
        self._bet_entries: list[BetEntry] = []
        self._current_candle_id: str | None = None
        self._cash_before_bet: float = 0.0

    @property
    def name(self) -> str:
        return self._name

    @property
    def portfolio(self) -> PortfolioService:
        return self._portfolio

    def handle_snapshot(self, row: dict, snapshot: IndicatorSnapshot) -> None:
        """Predict, evaluate entry, broadcast if triggered."""
        # Update portfolio prices
        if snapshot.up_bids and snapshot.up_asks and snapshot.down_bids and snapshot.down_asks:
            up_mid = (snapshot.up_bids[0][0] + snapshot.up_asks[0][0]) / 2
            down_mid = (snapshot.down_bids[0][0] + snapshot.down_asks[0][0]) / 2
            self._portfolio.update_prices(up_mid, down_mid)

        self._evaluate_entry(snapshot, row)

    def _evaluate_entry(self, snapshot: IndicatorSnapshot, row: dict) -> None:
        """Check if the current snapshot triggers a scaling-in entry."""
        if self._next_checkpoint >= len(self._strategy.entry_points):
            return

        min_elapsed, n_consecutive = self._strategy.entry_points[self._next_checkpoint]

        if snapshot.elapsed_pct < min_elapsed:
            return

        t0 = _time.perf_counter()
        p_up = self._predictor.predict(row)
        inference_ms = (_time.perf_counter() - t0) * 1000

        pred = 1 if p_up >= 0.5 else 0
        self._predictions.append(pred)

        if len(self._predictions) < n_consecutive:
            return

        recent = self._predictions[-n_consecutive:]
        if not all(p == recent[0] for p in recent):
            return

        confidence = max(p_up, 1.0 - p_up)
        if confidence < self._strategy.min_confidence:
            return

        direction = "UP" if pred == 1 else "DOWN"

        if self._first_direction is None:
            self._first_direction = direction
        elif direction != self._first_direction:
            return

        if direction == "UP" and snapshot.up_asks:
            ask = snapshot.up_asks[0][0]
        elif direction == "DOWN" and snapshot.down_asks:
            ask = snapshot.down_asks[0][0]
        else:
            return

        if ask <= 0 or ask >= MAX_BID:
            return

        bet_amount = self._portfolio.state.cash * BET_PCT
        if bet_amount < 0.01:
            return

        if self._entries_made == 0:
            self._cash_before_bet = self._portfolio.state.cash
            self._current_candle_id = snapshot.candle_id

        self._portfolio.buy(direction, amount_usd=bet_amount, price=ask)
        self._entries_made += 1
        self._next_checkpoint += 1

        entry = BetEntry(
            price=ask,
            amount_usd=bet_amount,
            elapsed_pct=snapshot.elapsed_pct,
            confidence=confidence,
            checkpoint=self._entries_made,
        )
        self._bet_entries.append(entry)

        self._log.info(
            "🎯 ENTRY %d/%d | %s @ $%.4f | candle %s | elapsed %.0f%% | conf=%.2f",
            self._entries_made,
            len(self._strategy.entry_points),
            direction,
            ask,
            snapshot.candle_id,
            snapshot.elapsed_pct * 100,
            confidence,
        )

        self._broadcaster.broadcast_json({
            "type": "model_entry",
            "model": self._name,
            "candle_id": snapshot.candle_id,
            "direction": direction,
            "price": ask,
            "amount_usd": round(bet_amount, 4),
            "confidence": round(confidence, 4),
            "inference_ms": round(inference_ms, 3),
            "checkpoint": self._entries_made,
            "elapsed_pct": round(snapshot.elapsed_pct, 4),
            "timestamp": snapshot.timestamp,
        })

    async def handle_candle_close(self, candle: CandleRecord) -> None:
        """Settle portfolio, record bet, broadcast settlement, reset state."""
        had_position = self._entries_made > 0

        self._portfolio.settle(candle.outcome, candle_id=candle.candle_id)

        if had_position:
            state = self._portfolio.state
            pnl = state.cash - self._cash_before_bet

            record = BetRecord(
                candle_id=self._current_candle_id or candle.candle_id,
                direction=self._first_direction or "",
                outcome=candle.outcome,
                won=self._first_direction == candle.outcome,
                entries=self._bet_entries,
                pnl=round(pnl, 4),
                timestamp=_time.time(),
            )
            await self._bet_store.save_bet(record)

            self._log.info(
                "🕯️ RESOLVED %s | %s | entries=%d | pnl=$%+.2f | W=%d L=%d | cash=$%.2f",
                candle.candle_id,
                candle.outcome,
                self._entries_made,
                pnl,
                state.wins,
                state.losses,
                state.cash,
            )

            await self._broadcaster.broadcast_json({
                "type": "model_settlement",
                "model": self._name,
                "candle_id": candle.candle_id,
                "outcome": candle.outcome,
                "direction": self._first_direction or "",
                "won": self._first_direction == candle.outcome,
                "entries": [asdict(e) for e in self._bet_entries],
                "pnl": round(pnl, 4),
                "cash": round(state.cash, 4),
                "wins": state.wins,
                "losses": state.losses,
                "timestamp": _time.time(),
            })

        self._reset_candle_state()

    def handle_correction(self, corrected: CandleRecord) -> None:
        """Reverse and re-settle if outcome changed."""
        self._portfolio.reverse_and_resettle(corrected.candle_id, corrected.outcome)

    def _reset_candle_state(self) -> None:
        self._predictions = []
        self._first_direction = None
        self._entries_made = 0
        self._next_checkpoint = 0
        self._bet_entries = []
        self._current_candle_id = None
        self._cash_before_bet = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_model_runner.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add polybot/services/model_runner.py tests/polybot/test_model_runner.py
git commit -m "feat: add ModelRunner with Strategy pattern"
```

---

### Task 3: Add settlement and correction tests for ModelRunner

**Files:**
- Modify: `tests/polybot/test_model_runner.py`

- [ ] **Step 1: Add settlement tests**

Append to `tests/polybot/test_model_runner.py`:

```python
class TestHandleCandleClose:
    @pytest.mark.asyncio
    async def test_settlement_saves_bet_and_broadcasts(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        # Trigger entry
        for _ in range(3):
            runner.handle_snapshot(row, snap)
        assert runner._entries_made == 1

        candle = CandleRecord(
            candle_id="c1", start_time=0, end_time=300,
            open=70000, high=70100, low=69900, close=70050,
            volume=50, outcome="UP", final_ret=0.0007,
        )
        await runner.handle_candle_close(candle)

        # Bet saved
        runner._bet_store.save_bet.assert_awaited_once()
        saved = runner._bet_store.save_bet.call_args[0][0]
        assert saved.won is True
        assert saved.direction == "UP"

        # Settlement broadcast
        calls = runner._broadcaster.broadcast_json.call_args_list
        settlement = calls[-1][0][0]
        assert settlement["type"] == "model_settlement"
        assert settlement["model"] == "TestModel"
        assert settlement["won"] is True

    @pytest.mark.asyncio
    async def test_settlement_resets_candle_state(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(3):
            runner.handle_snapshot(row, snap)

        candle = CandleRecord(
            candle_id="c1", start_time=0, end_time=300,
            open=70000, high=70100, low=69900, close=70050,
            volume=50, outcome="UP", final_ret=0.0007,
        )
        await runner.handle_candle_close(candle)

        assert runner._entries_made == 0
        assert runner._predictions == []
        assert runner._first_direction is None

    @pytest.mark.asyncio
    async def test_no_position_skips_bet_save(self):
        runner = _make_runner()
        candle = CandleRecord(
            candle_id="c1", start_time=0, end_time=300,
            open=70000, high=70100, low=69900, close=70050,
            volume=50, outcome="UP", final_ret=0.0007,
        )
        await runner.handle_candle_close(candle)
        runner._bet_store.save_bet.assert_not_awaited()


class TestHandleCorrection:
    def test_correction_calls_reverse_and_resettle(self):
        runner = _make_runner()
        # First do a trade and settle
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(3):
            runner.handle_snapshot(row, snap)

        # Manually settle to create a settlement record
        runner._portfolio.settle("UP", candle_id="c1")
        runner._reset_candle_state()

        corrected = CandleRecord(
            candle_id="c1", start_time=0, end_time=300,
            open=70000, high=70100, low=69900, close=69950,
            volume=50, outcome="DOWN", final_ret=-0.0007,
        )
        # Should not raise
        runner.handle_correction(corrected)
```

Add import at the top of the file:

```python
from polybot_data.domain.collection import CandleRecord
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/polybot/test_model_runner.py -v`
Expected: 8 passed

- [ ] **Step 3: Commit**

```bash
git add tests/polybot/test_model_runner.py
git commit -m "test: add settlement and correction tests for ModelRunner"
```

---

### Task 4: Refactor AgentService to orchestrator

**Files:**
- Modify: `polybot/services/agent_service.py`
- Test: `tests/polybot/test_agent_service.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""Tests for AgentService orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polybot.services.agent_service import AgentService
from polybot_data.domain.collection import CandleRecord


def _make_agent(n_runners=2):
    indicators = MagicMock()
    indicators.on_snapshot.return_value = {"feat1": 1.0}
    indicators.prior_candles = []
    indicators.snapshots_so_far = []

    runners = []
    for i in range(n_runners):
        r = MagicMock()
        r.name = f"Model{i}"
        r.handle_snapshot = MagicMock()
        r.handle_candle_close = AsyncMock()
        r.handle_correction = MagicMock()
        runners.append(r)

    agent = AgentService(indicators=indicators, runners=runners)
    return agent, indicators, runners


class TestProcessSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_fans_out_to_all_runners(self):
        agent, indicators, runners = _make_agent(n_runners=3)
        msg = {"type": "snapshot", "candle_id": "c1", "timestamp": 1.0,
               "elapsed_pct": 0.5, "btc_price": 70000, "btc_bid": 69999,
               "btc_ask": 70001, "up_bids": [], "up_asks": [], "down_bids": [],
               "down_asks": [], "market_volume": 50}
        await agent.process(msg)
        for r in runners:
            r.handle_snapshot.assert_called_once()


class TestProcessCandleClose:
    @pytest.mark.asyncio
    async def test_candle_close_fans_out_to_all_runners(self):
        agent, indicators, runners = _make_agent(n_runners=3)
        msg = {"type": "candle_close", "candle_id": "c1", "start_time": 0,
               "end_time": 300, "open": 70000, "high": 70100, "low": 69900,
               "close": 70050, "volume": 50, "outcome": "UP", "final_ret": 0.001}
        await agent.process(msg)
        for r in runners:
            r.handle_candle_close.assert_awaited_once()


class TestProcessCorrection:
    @pytest.mark.asyncio
    async def test_correction_fans_out_to_all_runners(self):
        agent, indicators, runners = _make_agent(n_runners=3)
        # Need prior candle in indicators for correction to find
        candle = CandleRecord(
            candle_id="c1", start_time=0, end_time=300,
            open=70000, high=70100, low=69900, close=70050,
            volume=50, outcome="UP", final_ret=0.001,
        )
        indicators.prior_candles = [candle]
        msg = {"type": "candle_correction", "candle_id": "c1", "start_time": 0,
               "end_time": 300, "open": 70000, "high": 70100, "low": 69900,
               "close": 69950, "volume": 50, "outcome": "DOWN", "final_ret": -0.001}
        await agent.process(msg)
        for r in runners:
            r.handle_correction.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_agent_service.py -v`
Expected: FAIL (AgentService constructor doesn't accept `runners`)

- [ ] **Step 3: Rewrite AgentService**

Replace `polybot/services/agent_service.py`:

```python
"""Service: orchestrates message processing — fans out to model runners."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot

if TYPE_CHECKING:
    from polybot.services.indicator_service import IndicatorService
    from polybot.services.model_runner import ModelRunner


class AgentService:
    """Thin orchestrator: computes indicators once, fans out to all model runners."""

    def __init__(
        self,
        indicators: IndicatorService,
        runners: list[ModelRunner],
        logger: logging.Logger | None = None,
    ) -> None:
        self._indicators = indicators
        self._runners = runners
        self._log = logger or logging.getLogger(__name__)

    async def process(self, msg: dict) -> dict | None:
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            snapshot = IndicatorSnapshot.from_dict(msg)
            return self._on_snapshot(snapshot)
        if msg_type == "candle_close":
            candle = CandleRecord.from_ws(msg)
            await self._on_candle_close(candle)
            return None
        if msg_type == "candle_correction":
            candle = CandleRecord.from_ws(msg)
            self._on_candle_correction(candle)
            return None
        return None

    def _on_snapshot(self, snapshot: IndicatorSnapshot) -> dict | None:
        row = self._indicators.on_snapshot(snapshot)
        if row is None:
            return None
        for runner in self._runners:
            runner.handle_snapshot(row, snapshot)
        return row

    async def _on_candle_close(self, candle: CandleRecord) -> None:
        for runner in self._runners:
            await runner.handle_candle_close(candle)
        await self._indicators.on_candle_close(candle)

    def _on_candle_correction(self, corrected: CandleRecord) -> None:
        for i, c in enumerate(self._indicators.prior_candles):
            if c.candle_id == corrected.candle_id:
                old_outcome = c.outcome
                self._indicators.prior_candles[i] = corrected
                if old_outcome != corrected.outcome:
                    for runner in self._runners:
                        runner.handle_correction(corrected)
                    self._log.warning(
                        "🔄 Correction applied | %s | %s→%s",
                        corrected.candle_id,
                        old_outcome,
                        corrected.outcome,
                    )
                break
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/polybot/test_agent_service.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add polybot/services/agent_service.py tests/polybot/test_agent_service.py
git commit -m "refactor: AgentService becomes thin orchestrator over ModelRunners"
```

---

### Task 5: Wire up `__main__.py` with 3 runners

**Files:**
- Modify: `polybot/__main__.py`

- [ ] **Step 1: Rewrite __main__.py**

```python
"""Bot entry point — runs LR, RF, XGBoost in parallel on collector WS stream."""

import asyncio
import logging
import os
from dataclasses import asdict

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.joblib_predictor import JoblibPredictor
from polybot.adapters.jsonl_bet_store import JsonlBetStore
from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.domain.trading_strategy import TradingStrategy
from polybot.services.agent_service import AgentService
from polybot.services.indicator_service import IndicatorService
from polybot.services.model_runner import ModelRunner
from polybot.services.portfolio_service import PortfolioService
from polybot.ws import Broadcaster, PolybotServer

DB_PATH = os.environ.get("POLYBOT_DB_PATH", "data/collection.db")
SESSION_PATH = os.environ.get("POLYBOT_SESSION_PATH", "data/sessions.jsonl")
INITIAL_CASH = float(os.environ.get("POLYBOT_TRADING_INITIAL_CASH", "1000.0"))

MODEL_CONFIGS = [
    {
        "name": "LogisticRegression",
        "model_path": "models/logistic_v1.joblib",
        "scaler_path": "models/scaler_v1.joblib",
        "features_path": "models/feature_cols_v1.joblib",
        "strategy_path": "data/optimal_strategy_lr.json",
        "bets_dir": "data/bets/LogisticRegression",
    },
    {
        "name": "RandomForest",
        "model_path": "models/rf_v1.joblib",
        "scaler_path": "models/rf_scaler_v1.joblib",
        "features_path": "models/rf_feature_cols_v1.joblib",
        "strategy_path": "data/optimal_strategy_rf.json",
        "bets_dir": "data/bets/RandomForest",
    },
    {
        "name": "XGBoost",
        "model_path": "models/xgb_calibrator_v1.joblib",
        "scaler_path": "models/xgb_scaler_v1.joblib",
        "features_path": "models/xgb_feature_cols_v1.joblib",
        "strategy_path": "data/optimal_strategy_xgb.json",
        "bets_dir": "data/bets/XGBoost",
    },
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("polybot")


async def main() -> None:
    repo = SqliteCandleRepository(DB_PATH)
    await repo.init()

    indicators = IndicatorService(candle_repo=repo)
    broadcaster = Broadcaster()
    session_store = JsonlSessionStore(SESSION_PATH)

    runners: list[ModelRunner] = []
    for cfg in MODEL_CONFIGS:
        predictor = JoblibPredictor(
            model_path=cfg["model_path"],
            scaler_path=cfg["scaler_path"],
            feature_cols_path=cfg["features_path"],
        )
        portfolio = PortfolioService(initial_cash=INITIAL_CASH)
        strategy = TradingStrategy.from_json(cfg["strategy_path"], name=cfg["name"])
        bet_store = JsonlBetStore(directory=cfg["bets_dir"])

        runner = ModelRunner(
            name=cfg["name"],
            predictor=predictor,
            portfolio=portfolio,
            strategy=strategy,
            bet_store=bet_store,
            broadcaster=broadcaster,
        )
        runners.append(runner)
        log.info(
            "🤖 %s: %d features, strategy=%s, conf>%.1f",
            cfg["name"],
            len(predictor._feature_cols),
            strategy.entry_points,
            strategy.min_confidence,
        )

    agent = AgentService(indicators=indicators, runners=runners)

    def build_initial_state() -> dict:
        return {
            "type": "initial_state",
            "candles": [asdict(c) for c in indicators.prior_candles],
            "snapshots_so_far": [asdict(s) for s in indicators.snapshots_so_far],
            "portfolios": {
                r.name: r.portfolio.session_summary() for r in runners
            },
        }

    server = PolybotServer(broadcaster, initial_state_fn=build_initial_state)
    await server.start()

    async def on_message(msg: dict) -> None:
        await agent.process(msg)
        await broadcaster.broadcast_json(msg)

    client = CollectorClient(on_message=on_message)

    try:
        await client.run()
    finally:
        for runner in runners:
            summary = runner.portfolio.session_summary()
            summary["model"] = runner.name
            log.info(
                "📋 %s: W=%d L=%d | PnL=$%.2f | Balance=$%.2f | Return=%+.1f%%",
                runner.name,
                summary["wins"],
                summary["losses"],
                summary["net_pnl"],
                summary["final_balance"],
                summary["total_return_pct"],
            )
            await session_store.save_session(summary)
        await client.stop()
        await repo.close()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run all tests to verify nothing is broken**

Run: `uv run pytest tests/ -v`
Expected: All existing tests pass (some may need updates if they tested the old AgentService constructor)

- [ ] **Step 3: Fix any broken tests**

The old `AgentService` constructor took `indicators`, `portfolio`, `predictor`, `bet_store`. Any test that constructs `AgentService` directly needs updating to pass `runners` instead. Check `tests/polybot/` for any files testing the old interface.

- [ ] **Step 4: Commit**

```bash
git add polybot/__main__.py
git commit -m "feat: wire 3 model runners in parallel (LR, RF, XGBoost)"
```

---

### Task 6: Make broadcaster.broadcast_json async-safe from sync context

**Files:**
- Modify: `polybot/services/model_runner.py` (handle_snapshot calls broadcast_json which is async)
- Test: verify existing tests pass

`handle_snapshot` is sync but `broadcaster.broadcast_json` is async. Two options: make `handle_snapshot` async, or fire-and-forget the broadcast. The cleanest approach is to make `handle_snapshot` async.

- [ ] **Step 1: Change handle_snapshot to async**

In `polybot/services/model_runner.py`, change:
- `def handle_snapshot(` → `async def handle_snapshot(`
- `self._broadcaster.broadcast_json({` → `await self._broadcaster.broadcast_json({`

In `polybot/services/agent_service.py`, change `_on_snapshot`:
```python
async def _on_snapshot(self, snapshot: IndicatorSnapshot) -> dict | None:
    row = self._indicators.on_snapshot(snapshot)
    if row is None:
        return None
    for runner in self._runners:
        await runner.handle_snapshot(row, snapshot)
    return row
```

And `process` must await `_on_snapshot`:
```python
if msg_type == "snapshot":
    snapshot = IndicatorSnapshot.from_dict(msg)
    return await self._on_snapshot(snapshot)
```

- [ ] **Step 2: Update tests**

In `tests/polybot/test_model_runner.py`, change all `runner.handle_snapshot(row, snap)` calls to `await runner.handle_snapshot(row, snap)` and make the test methods `async def` with `@pytest.mark.asyncio`.

In `tests/polybot/test_agent_service.py`, change the mock runner's `handle_snapshot` to `AsyncMock()`.

- [ ] **Step 3: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add polybot/services/model_runner.py polybot/services/agent_service.py tests/
git commit -m "refactor: make handle_snapshot async for broadcast support"
```

---

### Task 7: Integration smoke test

**Files:**
- Create: `tests/polybot/test_multi_model_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test: 3 model runners process the same snapshot independently."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.domain.trading_strategy import TradingStrategy
from polybot.services.agent_service import AgentService
from polybot.services.model_runner import ModelRunner
from polybot.services.portfolio_service import PortfolioService


def _make_predictor(p_up: float):
    p = MagicMock()
    p.predict.return_value = p_up
    return p


@pytest.mark.asyncio
async def test_three_runners_independent_portfolios():
    """3 runners with different predictions produce independent results."""
    broadcaster = AsyncMock()

    runners = []
    for name, p_up in [("LR", 0.7), ("RF", 0.3), ("XGB", 0.8)]:
        strategy = TradingStrategy(
            name=name,
            entry_points=((0.05, 1),),  # 1 consecutive for simplicity
            min_confidence=0.0,
        )
        runner = ModelRunner(
            name=name,
            predictor=_make_predictor(p_up),
            portfolio=PortfolioService(initial_cash=1000.0),
            strategy=strategy,
            bet_store=AsyncMock(),
            broadcaster=broadcaster,
        )
        runners.append(runner)

    indicators = MagicMock()
    indicators.prior_candles = []
    indicators.snapshots_so_far = []
    row = {"feat1": 1.0}
    indicators.on_snapshot.return_value = row

    agent = AgentService(indicators=indicators, runners=runners)

    msg = {
        "type": "snapshot",
        "candle_id": "c1",
        "timestamp": 1.0,
        "elapsed_pct": 0.06,
        "btc_price": 70000,
        "btc_bid": 69999,
        "btc_ask": 70001,
        "up_bids": [[0.58, 100]],
        "up_asks": [[0.60, 100]],
        "down_bids": [[0.38, 100]],
        "down_asks": [[0.40, 100]],
        "market_volume": 50,
    }

    await agent.process(msg)

    # LR predicts UP (0.7), RF predicts DOWN (0.3), XGB predicts UP (0.8)
    # With 1-consecutive, LR and XGB should enter, RF should enter DOWN
    assert runners[0]._entries_made == 1  # LR: UP
    assert runners[0]._first_direction == "UP"
    assert runners[1]._entries_made == 1  # RF: DOWN
    assert runners[1]._first_direction == "DOWN"
    assert runners[2]._entries_made == 1  # XGB: UP
    assert runners[2]._first_direction == "UP"

    # Each has its own portfolio
    assert runners[0].portfolio.state.cash < 1000.0
    assert runners[1].portfolio.state.cash < 1000.0
    assert runners[2].portfolio.state.cash < 1000.0

    # 3 model_entry broadcasts
    entry_calls = [
        c[0][0] for c in broadcaster.broadcast_json.call_args_list
        if c[0][0].get("type") == "model_entry"
    ]
    assert len(entry_calls) == 3
    models = {c["model"] for c in entry_calls}
    assert models == {"LR", "RF", "XGB"}
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/polybot/test_multi_model_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/polybot/test_multi_model_integration.py
git commit -m "test: integration test for 3-model parallel trading"
```
