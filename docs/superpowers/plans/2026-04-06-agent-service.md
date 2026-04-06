# AgentService Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentService maintains live bot state (prior candles + current snapshots), computes 56 technical indicators every second, and prints the model input row.

**Architecture:** Hexagonal. `CandleRepository` port abstracts SQLite reads (read-only). `indicator_engine` is the canonical module for all 56 indicators (moved from notebook). `AgentService` orchestrates state + computation. `CollectorClient` dispatches messages via async callback.

**Tech Stack:** Python 3.11, aiosqlite, websockets, pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `polybot_data/services/indicator_engine.py` | Create (copy from `notebooks/technicals.py`) | 56 pure indicator functions + `compute_all()` |
| `polybot/ports/candle_repository.py` | Create | Protocol: `get_recent_candles(limit)` |
| `polybot/adapters/sqlite_candle_repo.py` | Create | Read-only SQLite adapter for candle history |
| `polybot/services/agent_service.py` | Create | State management + indicator computation + row output |
| `polybot/adapters/collector_client.py` | Modify | Replace `relay: MessageRelay` with `on_message` async callback |
| `polybot/__main__.py` | Modify | Wire AgentService + Broadcaster via on_message dispatcher |
| `tests/polybot/test_sqlite_candle_repo.py` | Create | Test repo with in-memory SQLite |
| `tests/polybot/test_agent_service.py` | Create | Test lifecycle, sync, row output |
| `tests/polybot/test_collector_client.py` | Modify | Update for on_message callback |

---

### Task 1: Move indicator_engine from notebook

**Files:**
- Create: `polybot_data/services/indicator_engine.py`

- [ ] **Step 1: Copy the module**

```bash
cp notebooks/technicals.py polybot_data/services/indicator_engine.py
```

- [ ] **Step 2: Verify import works**

```bash
uv run python -c "from polybot_data.services.indicator_engine import compute_all; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run lint**

Run: `uv run ruff check polybot_data/services/indicator_engine.py`
Fix any issues.

- [ ] **Step 4: Commit**

```bash
git add polybot_data/services/indicator_engine.py
git commit -m "feat: move indicator_engine from notebook (56 indicators)"
```

---

### Task 2: Create CandleRepository port

**Files:**
- Create: `polybot/ports/candle_repository.py`

- [ ] **Step 1: Create the port**

```python
"""Port: read-only access to completed candle history."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CandleRepository(Protocol):
    """Reads completed candles for indicator computation."""

    async def get_recent_candles(self, limit: int) -> list[dict]:
        """Return last `limit` candles, oldest first.

        Each dict has: open, high, low, close, volume, outcome, final_ret.
        """
        ...
```

- [ ] **Step 2: Commit**

```bash
git add polybot/ports/candle_repository.py
git commit -m "feat(polybot): add CandleRepository port"
```

---

### Task 3: Create SqliteCandleRepository adapter

**Files:**
- Create: `polybot/adapters/sqlite_candle_repo.py`
- Create: `tests/polybot/test_sqlite_candle_repo.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for SqliteCandleRepository."""

import aiosqlite
import pytest

from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.ports.candle_repository import CandleRepository


class TestSqliteCandleRepository:
    def test_implements_protocol(self):
        repo = SqliteCandleRepository(":memory:")
        assert isinstance(repo, CandleRepository)

    async def test_get_recent_candles_returns_oldest_first(self):
        repo = SqliteCandleRepository(":memory:")
        await repo.init()
        try:
            db = repo._db
            await db.execute(
                "CREATE TABLE candles ("
                "candle_id TEXT PRIMARY KEY, start_time REAL, end_time REAL, "
                "open REAL, high REAL, low REAL, close REAL, volume REAL, "
                "outcome TEXT, final_ret REAL)"
            )
            for i in range(5):
                await db.execute(
                    "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"c-{i}", i * 300.0, (i + 1) * 300.0, 100.0 + i, 110.0 + i,
                     90.0 + i, 105.0 + i, 10.0, "UP", 0.001),
                )
            await db.commit()

            candles = await repo.get_recent_candles(3)
            assert len(candles) == 3
            assert candles[0]["open"] == 102.0  # 3rd oldest of 5
            assert candles[2]["open"] == 104.0  # most recent
        finally:
            await repo.close()

    async def test_get_recent_candles_empty_db(self):
        repo = SqliteCandleRepository(":memory:")
        await repo.init()
        try:
            db = repo._db
            await db.execute(
                "CREATE TABLE candles ("
                "candle_id TEXT PRIMARY KEY, start_time REAL, end_time REAL, "
                "open REAL, high REAL, low REAL, close REAL, volume REAL, "
                "outcome TEXT, final_ret REAL)"
            )
            await db.commit()
            candles = await repo.get_recent_candles(10)
            assert candles == []
        finally:
            await repo.close()

    async def test_returns_correct_dict_keys(self):
        repo = SqliteCandleRepository(":memory:")
        await repo.init()
        try:
            db = repo._db
            await db.execute(
                "CREATE TABLE candles ("
                "candle_id TEXT PRIMARY KEY, start_time REAL, end_time REAL, "
                "open REAL, high REAL, low REAL, close REAL, volume REAL, "
                "outcome TEXT, final_ret REAL)"
            )
            await db.execute(
                "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("c-0", 0.0, 300.0, 100.0, 110.0, 90.0, 105.0, 10.0, "UP", 0.001),
            )
            await db.commit()
            candles = await repo.get_recent_candles(1)
            assert set(candles[0].keys()) == {
                "open", "high", "low", "close", "volume", "outcome", "final_ret",
            }
        finally:
            await repo.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_sqlite_candle_repo.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement SqliteCandleRepository**

```python
"""Adapter: read-only SQLite access to completed candle history."""

from __future__ import annotations

import logging

import aiosqlite


class SqliteCandleRepository:
    """Reads candles from SQLite in read-only mode."""

    def __init__(self, db_path: str, logger: logging.Logger | None = None) -> None:
        self._db_path = db_path
        self._log = logger or logging.getLogger(__name__)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        uri = f"file:{self._db_path}?mode=ro"
        if self._db_path == ":memory:":
            uri = self._db_path
        self._db = await aiosqlite.connect(uri, uri=self._db_path != ":memory:")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def get_recent_candles(self, limit: int) -> list[dict]:
        """Return last `limit` candles, oldest first."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT open, high, low, close, volume, outcome, final_ret "
            "FROM candles ORDER BY start_time DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "open": r[0],
                "high": r[1],
                "low": r[2],
                "close": r[3],
                "volume": r[4],
                "outcome": r[5],
                "final_ret": r[6],
            }
            for r in reversed(rows)
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_sqlite_candle_repo.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/adapters/sqlite_candle_repo.py polybot/ports/candle_repository.py tests/polybot/test_sqlite_candle_repo.py
git commit -m "feat(polybot): add SqliteCandleRepository (read-only)"
```

---

### Task 4: Create AgentService

**Files:**
- Create: `polybot/services/agent_service.py`
- Create: `tests/polybot/test_agent_service.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for AgentService."""

import pytest
from unittest.mock import AsyncMock

from polybot.services.agent_service import AgentService

MINIMUM_CANDLES = 21


def _make_candle(i: int) -> dict:
    return {
        "open": 100.0 + i,
        "high": 110.0 + i,
        "low": 90.0 + i,
        "close": 105.0 + i,
        "volume": 10.0,
        "outcome": "UP" if i % 2 == 0 else "DOWN",
        "final_ret": 0.001 if i % 2 == 0 else -0.001,
    }


def _make_snapshot(candle_id: str = "test-100", elapsed: float = 0.5, price: float = 69000.0) -> dict:
    return {
        "type": "snapshot",
        "candle_id": candle_id,
        "timestamp": 1000.0,
        "elapsed_pct": elapsed,
        "btc_price": price,
        "btc_bid": price - 2,
        "btc_ask": price + 2,
        "up_bids": [[0.55, 100]],
        "up_asks": [[0.57, 150]],
        "down_bids": [[0.43, 120]],
        "down_asks": [[0.45, 80]],
        "up_last_trade": 0.56,
        "down_last_trade": 0.44,
        "market_volume": 5000.0,
    }


def _make_candle_close(candle_id: str = "test-100") -> dict:
    return {
        "type": "candle_close",
        "candle_id": candle_id,
        "open": 69000.0,
        "high": 69100.0,
        "low": 68900.0,
        "close": 69050.0,
        "volume": 15.0,
        "outcome": "UP",
        "final_ret": 0.0007,
    }


class TestAgentServiceSync:
    async def test_not_synced_on_init(self):
        repo = AsyncMock()
        agent = AgentService(candle_repo=repo)
        assert agent.synced is False

    async def test_snapshot_ignored_before_sync(self):
        repo = AsyncMock()
        agent = AgentService(candle_repo=repo)
        row = agent.on_snapshot(_make_snapshot())
        assert row is None

    async def test_sync_on_first_candle_close(self):
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(
            return_value=[_make_candle(i) for i in range(MINIMUM_CANDLES)]
        )
        agent = AgentService(candle_repo=repo)
        await agent.on_candle_close(_make_candle_close())
        assert agent.synced is True
        repo.get_recent_candles.assert_awaited_once_with(MINIMUM_CANDLES)

    async def test_prior_candles_loaded_on_sync(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        agent = AgentService(candle_repo=repo)
        await agent.on_candle_close(_make_candle_close())
        # Prior candles = fetched + the candle_close itself
        assert len(agent._prior_candles) == MINIMUM_CANDLES + 1


class TestAgentServiceRow:
    async def test_snapshot_returns_row_after_sync(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        agent = AgentService(candle_repo=repo)
        await agent.on_candle_close(_make_candle_close("candle-1"))
        row = agent.on_snapshot(_make_snapshot("candle-2"))
        assert row is not None
        assert row["candle_id"] == "candle-2"
        assert row["btc_price"] == 69000.0
        assert "rsi" in row
        assert "prior_return" in row
        assert "outcome" not in row

    async def test_candle_close_appends_and_trims(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        agent = AgentService(candle_repo=repo)
        await agent.on_candle_close(_make_candle_close("candle-1"))
        initial_count = len(agent._prior_candles)

        await agent.on_candle_close(_make_candle_close("candle-2"))
        assert len(agent._prior_candles) == initial_count + 1

    async def test_snapshots_reset_on_new_candle(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        agent = AgentService(candle_repo=repo)
        await agent.on_candle_close(_make_candle_close("candle-1"))
        agent.on_snapshot(_make_snapshot("candle-2", elapsed=0.1, price=69000.0))
        agent.on_snapshot(_make_snapshot("candle-2", elapsed=0.2, price=69010.0))
        assert len(agent._snapshots_so_far) == 2

        # New candle boundary
        agent.on_snapshot(_make_snapshot("candle-3", elapsed=0.01, price=69020.0))
        assert len(agent._snapshots_so_far) == 1
        assert agent._current_candle_id == "candle-3"

    async def test_row_has_all_56_indicators(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        agent = AgentService(candle_repo=repo)
        await agent.on_candle_close(_make_candle_close("candle-1"))
        row = agent.on_snapshot(_make_snapshot("candle-2"))
        # 13 market state fields + 56 indicators = 69 total
        assert len(row) >= 69
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_agent_service.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement AgentService**

```python
"""Service: maintains bot state and computes technical indicators."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.services.indicator_engine import compute_all

if TYPE_CHECKING:
    from polybot.ports.candle_repository import CandleRepository

MINIMUM_CANDLES = 21  # max lookback across all indicators


class AgentService:
    """Maintains prior candles + current snapshots, computes 56 indicators per tick."""

    def __init__(
        self,
        candle_repo: CandleRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = candle_repo
        self._log = logger or logging.getLogger(__name__)
        self._prior_candles: list[dict] = []
        self._snapshots_so_far: list[dict] = []
        self._candle_open: float | None = None
        self._current_candle_id: str | None = None
        self._synced = False

    @property
    def synced(self) -> bool:
        return self._synced

    def on_snapshot(self, msg: dict) -> dict | None:
        """Process a snapshot message. Returns the model row, or None if not synced."""
        if not self._synced:
            return None

        candle_id = msg.get("candle_id")
        if candle_id != self._current_candle_id:
            self._snapshots_so_far = []
            self._candle_open = msg["btc_price"]
            self._current_candle_id = candle_id

        self._snapshots_so_far.append(msg)

        indicators = compute_all(
            self._prior_candles,
            self._candle_open,
            self._snapshots_so_far,
        )

        return {
            "candle_id": msg.get("candle_id"),
            "timestamp": msg.get("timestamp"),
            "elapsed_pct": msg.get("elapsed_pct"),
            "btc_price": msg.get("btc_price"),
            "up_best_bid": msg["up_bids"][0][0] if msg.get("up_bids") else None,
            "up_best_ask": msg["up_asks"][0][0] if msg.get("up_asks") else None,
            "up_bid_depth": msg["up_bids"][0][1] if msg.get("up_bids") else None,
            "up_ask_depth": msg["up_asks"][0][1] if msg.get("up_asks") else None,
            "down_best_bid": msg["down_bids"][0][0] if msg.get("down_bids") else None,
            "down_best_ask": msg["down_asks"][0][0] if msg.get("down_asks") else None,
            "down_bid_depth": msg["down_bids"][0][1] if msg.get("down_bids") else None,
            "down_ask_depth": msg["down_asks"][0][1] if msg.get("down_asks") else None,
            "market_volume": msg.get("market_volume"),
            **indicators,
        }

    async def on_candle_close(self, msg: dict) -> None:
        """Process a candle_close message. Syncs on first call."""
        if not self._synced:
            self._prior_candles = await self._repo.get_recent_candles(MINIMUM_CANDLES)
            self._synced = True
            self._log.info(
                "🔄 Synced — loaded %d prior candles from DB",
                len(self._prior_candles),
            )

        candle = {
            "open": msg["open"],
            "high": msg["high"],
            "low": msg["low"],
            "close": msg["close"],
            "volume": msg["volume"],
            "outcome": msg["outcome"],
            "final_ret": msg["final_ret"],
        }
        self._prior_candles.append(candle)

        self._snapshots_so_far = []
        self._candle_open = None
        self._current_candle_id = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_agent_service.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/services/agent_service.py tests/polybot/test_agent_service.py
git commit -m "feat(polybot): add AgentService with 56 indicators per tick"
```

---

### Task 5: Refactor CollectorClient to use on_message callback

**Files:**
- Modify: `polybot/adapters/collector_client.py`
- Modify: `tests/polybot/test_collector_client.py`

- [ ] **Step 1: Update CollectorClient**

Replace `relay: MessageRelay` with `on_message` async callback:

```python
"""Adapter: connects to collector's local WebSocket for live market data."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import websockets

WS_URL = "ws://localhost:8765"
RECONNECT_DELAY = 3

OnMessage = Callable[[dict], Coroutine[Any, Any, None]]


class CollectorClient:
    """Receives snapshots and candle_close events from the collector server."""

    def __init__(
        self,
        ws_url: str = WS_URL,
        on_message: OnMessage | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._log = logger or logging.getLogger(__name__)
        self._on_message = on_message
        self._latest_snapshot: dict | None = None
        self._latest_candle_close: dict | None = None
        self._running = False

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._log.info("Connected to collector at %s", self._ws_url)
                    async for raw in ws:
                        await self._handle_message(raw)
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError):
                self._log.warning("Collector connection lost, retrying in %ds...", RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)

    async def _handle_message(self, raw: str) -> None:
        msg = json.loads(raw)
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            self._latest_snapshot = msg
        elif msg_type == "candle_close":
            self._latest_candle_close = msg
        if self._on_message is not None:
            try:
                await self._on_message(msg)
            except Exception:
                self._log.exception("on_message handler failed")

    async def stop(self) -> None:
        self._running = False

    @property
    def snapshot(self) -> dict | None:
        return self._latest_snapshot

    @property
    def candle_close(self) -> dict | None:
        return self._latest_candle_close
```

- [ ] **Step 2: Update tests**

```python
"""Tests for CollectorClient."""

import json
from unittest.mock import AsyncMock

import pytest

from polybot.adapters.collector_client import CollectorClient


class TestCollectorClientCallback:
    async def test_snapshot_invokes_on_message(self):
        received = []

        async def handler(msg):
            received.append(msg)

        client = CollectorClient(on_message=handler)
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert len(received) == 1
        assert received[0] == msg

    async def test_candle_close_invokes_on_message(self):
        received = []

        async def handler(msg):
            received.append(msg)

        client = CollectorClient(on_message=handler)
        msg = {"type": "candle_close", "candle_id": "test-123", "outcome": "UP"}
        await client._handle_message(json.dumps(msg))
        assert len(received) == 1

    async def test_no_callback_still_works(self):
        client = CollectorClient()
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert client.snapshot == msg

    async def test_properties_updated(self):
        async def noop(msg):
            pass

        client = CollectorClient(on_message=noop)
        snap = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(snap))
        assert client.snapshot == snap

        candle = {"type": "candle_close", "candle_id": "x", "outcome": "DOWN"}
        await client._handle_message(json.dumps(candle))
        assert client.candle_close == candle

    async def test_callback_error_does_not_crash(self):
        async def bad_handler(msg):
            raise RuntimeError("boom")

        client = CollectorClient(on_message=bad_handler)
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert client.snapshot == msg

    async def test_malformed_json_raises(self):
        client = CollectorClient()
        with pytest.raises(json.JSONDecodeError):
            await client._handle_message("not json")
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/polybot/test_collector_client.py -v`
Expected: 6 PASS

- [ ] **Step 4: Commit**

```bash
git add polybot/adapters/collector_client.py tests/polybot/test_collector_client.py
git commit -m "refactor(polybot): CollectorClient uses on_message async callback"
```

---

### Task 6: Wire everything in __main__.py

**Files:**
- Modify: `polybot/__main__.py`

- [ ] **Step 1: Rewrite __main__.py**

```python
"""Bot entry point — connects to collector WS, computes indicators, re-broadcasts on 8766."""

import asyncio
import logging

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.services.agent_service import AgentService
from polybot.ws import Broadcaster, PolybotServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("polybot")


async def main() -> None:
    broadcaster = Broadcaster()
    server = PolybotServer(broadcaster)
    await server.start()

    repo = SqliteCandleRepository("data/collection.db")
    await repo.init()

    agent = AgentService(candle_repo=repo)

    async def on_message(msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            row = agent.on_snapshot(msg)
            if row is not None:
                log.info(
                    "📊 %s | elapsed=%.0f%% | BTC $%.2f | rsi=%s | streak=%s",
                    row["candle_id"],
                    (row["elapsed_pct"] or 0) * 100,
                    row["btc_price"] or 0,
                    row.get("rsi"),
                    row.get("consecutive_streak"),
                )
        elif msg_type == "candle_close":
            await agent.on_candle_close(msg)
        await broadcaster.broadcast_json(msg)

    client = CollectorClient(on_message=on_message)

    try:
        await client.run()
    finally:
        await client.stop()
        await repo.close()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 3: Lint**

Run: `uv run ruff check .`
Expected: No errors

- [ ] **Step 4: Manual smoke test**

With the collector running:
```bash
uv run python -m polybot
```

Expected:
- `📡 Polybot WS server listening on ws://localhost:8766`
- `Connected to collector at ws://localhost:8765`
- Waits silently until first candle_close
- `🔄 Synced — loaded 21 prior candles from DB`
- `📊 ... | rsi=XX.X | streak=X` every second

- [ ] **Step 5: Commit**

```bash
git add polybot/__main__.py
git commit -m "feat(polybot): wire AgentService + Broadcaster via on_message dispatcher"
```
