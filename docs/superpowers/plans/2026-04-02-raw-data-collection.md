# Raw Data Collection Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect raw market snapshots every 5 seconds and write completed candle records with outcomes to SQLite for offline analysis. No indicators computed at collection time.

**Architecture:** `DataCollector` is a passive recorder — it samples market data on a 5s loop and writes `Snapshot` rows to SQLite. It does NOT maintain its own candle lifecycle. Instead, `CandleAggregator` notifies it when a candle closes (via callback), providing the authoritative OHLCV + volume. `DataCollector` then writes the `CandleRecord` with outcome. Single source of truth for candle boundaries = `CandleAggregator`.

**Tech Stack:** Python, `aiosqlite` (already in pyproject.toml), existing hexagonal architecture.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Candle close comes from CandleAggregator callback | Single authority for candle lifecycle — no duplicate OHLC tracking |
| Snapshots written once in the 5s loop | `write_candle` does NOT re-insert snapshots — avoids duplicates |
| Key fields are real SQLite columns | `btc_price`, `up_last_trade`, `down_last_trade`, `market_volume` queryable via SQL |
| Orderbook levels stored as JSON | Top 10 levels per side — too structured for flat columns, fine as JSON |
| Chainlink tick timestamp stored separately | `tick_timestamp` (source time) vs `timestamp` (collection wall-clock) |
| Candle write is awaited, not fire-and-forget | Prevents data loss on shutdown |
| Snapshot state captured before awaits | Same consistency pattern as MarketStateService |

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `polybot/domain/collection.py` | Create | `Snapshot` and `CandleRecord` dataclasses |
| `polybot/ports/data_store.py` | Create | `DataStore` protocol |
| `polybot/adapters/sqlite_store.py` | Create | SQLite implementation |
| `polybot/services/data_collector.py` | Create | 5s snapshot loop + candle close handler |
| `polybot/services/candle_aggregator.py` | Modify | Add `on_candle_close` callback |
| `polybot/__main__.py` | Modify | Wire everything together |
| `tests/domain/test_collection.py` | Create | Model tests |
| `tests/adapters/test_sqlite_store.py` | Create | SQLite round-trip tests |
| `tests/services/test_data_collector.py` | Create | Collector logic tests |

---

### Task 1: Domain models for raw data collection

**Files:**
- Create: `polybot/domain/collection.py`
- Create: `tests/domain/test_collection.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/domain/test_collection.py
"""Tests for collection domain models."""

import time
import pytest
from polybot.domain.collection import Snapshot, CandleRecord


class TestSnapshot:
    def test_creation(self):
        s = Snapshot(
            timestamp=time.time(),
            tick_timestamp=time.time() - 0.5,
            candle_id="btc-updown-5m-1775000000",
            elapsed_pct=0.42,
            btc_price=66869.0,
            btc_bid=66867.0,
            btc_ask=66871.0,
            up_bids=((0.50, 100.0), (0.49, 200.0)),
            up_asks=((0.51, 150.0), (0.52, 300.0)),
            down_bids=((0.49, 120.0), (0.48, 250.0)),
            down_asks=((0.52, 180.0), (0.53, 350.0)),
            up_last_trade=0.50,
            down_last_trade=0.50,
            market_volume=5000.0,
        )
        assert s.btc_price == 66869.0
        assert s.tick_timestamp < s.timestamp

    def test_frozen(self):
        s = Snapshot(
            timestamp=0, tick_timestamp=0, candle_id="x", elapsed_pct=0,
            btc_price=0, btc_bid=0, btc_ask=0,
            up_bids=(), up_asks=(), down_bids=(), down_asks=(),
            up_last_trade=None, down_last_trade=None, market_volume=0,
        )
        with pytest.raises(AttributeError):
            s.btc_price = 1.0


class TestCandleRecord:
    def test_creation_up(self):
        rec = CandleRecord(
            candle_id="c1", start_time=1000.0, end_time=1300.0,
            open=66800.0, high=66850.0, low=66780.0, close=66830.0,
            volume=15.0, outcome="UP", final_ret=0.00045,
        )
        assert rec.outcome == "UP"

    def test_creation_down(self):
        rec = CandleRecord(
            candle_id="c1", start_time=1000.0, end_time=1300.0,
            open=66800.0, high=66850.0, low=66780.0, close=66750.0,
            volume=15.0, outcome="DOWN", final_ret=-0.00075,
        )
        assert rec.outcome == "DOWN"
```

- [ ] **Step 2: Run tests — FAIL**

- [ ] **Step 3: Implement models**

```python
# polybot/domain/collection.py
"""Domain models for raw data collection. No indicators — pure market state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    """Single point-in-time market observation. Collected every ~5 seconds."""

    # Timing
    timestamp: float           # wall-clock collection time
    tick_timestamp: float      # Chainlink source observation time
    candle_id: str
    elapsed_pct: float

    # Chainlink BTC
    btc_price: float
    btc_bid: float
    btc_ask: float

    # Polymarket orderbook (top levels as (price, size) tuples)
    up_bids: tuple[tuple[float, float], ...]
    up_asks: tuple[tuple[float, float], ...]
    down_bids: tuple[tuple[float, float], ...]
    down_asks: tuple[tuple[float, float], ...]

    # Polymarket prices
    up_last_trade: float | None
    down_last_trade: float | None
    market_volume: float


@dataclass(frozen=True)
class CandleRecord:
    """One completed candle with outcome. Snapshots linked by candle_id in DB."""

    candle_id: str
    start_time: float
    end_time: float

    # OHLCV (from CandleAggregator — authoritative)
    open: float
    high: float
    low: float
    close: float
    volume: float

    # Outcome
    outcome: str       # "UP" | "DOWN"
    final_ret: float   # ln(close / open)
```

Note: `CandleRecord` does NOT contain `snapshots` tuple. Snapshots are linked by `candle_id` in the database — no duplication.

- [ ] **Step 4: Run tests — PASS**
- [ ] **Step 5: Commit**

---

### Task 2: DataStore port and SQLite adapter

**Files:**
- Create: `polybot/ports/data_store.py`
- Create: `polybot/adapters/sqlite_store.py`
- Create: `tests/adapters/test_sqlite_store.py`

- [ ] **Step 1: Write DataStore port**

```python
# polybot/ports/data_store.py
"""Port: data persistence interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from polybot.domain.collection import CandleRecord, Snapshot


@runtime_checkable
class DataStore(Protocol):

    async def init(self) -> None: ...
    async def write_snapshot(self, snapshot: Snapshot) -> None: ...
    async def write_candle(self, record: CandleRecord) -> None: ...
    async def get_candle(self, candle_id: str) -> CandleRecord | None: ...
    async def get_snapshots(self, candle_id: str) -> list[Snapshot]: ...
    async def close(self) -> None: ...
```

- [ ] **Step 2: Write failing SQLite tests**

```python
# tests/adapters/test_sqlite_store.py

import time
import pytest
from polybot.adapters.sqlite_store import SqliteStore
from polybot.domain.collection import CandleRecord, Snapshot
from polybot.ports.data_store import DataStore


def _snap(candle_id="c1", elapsed=0.5, price=66800.0):
    return Snapshot(
        timestamp=time.time(), tick_timestamp=time.time() - 0.5,
        candle_id=candle_id, elapsed_pct=elapsed,
        btc_price=price, btc_bid=price - 2, btc_ask=price + 2,
        up_bids=((0.50, 100),), up_asks=((0.51, 150),),
        down_bids=((0.49, 120),), down_asks=((0.52, 180),),
        up_last_trade=0.50, down_last_trade=0.50, market_volume=5000,
    )


def _candle(candle_id="c1"):
    return CandleRecord(
        candle_id=candle_id, start_time=1000, end_time=1300,
        open=66800, high=66850, low=66780, close=66830,
        volume=15.0, outcome="UP", final_ret=0.00045,
    )


class TestSqliteStore:
    async def test_protocol_conformance(self, tmp_path):
        store = SqliteStore(str(tmp_path / "test.db"))
        assert isinstance(store, DataStore)
        await store.close()

    async def test_write_and_read_candle(self, tmp_path):
        store = SqliteStore(str(tmp_path / "test.db"))
        await store.init()
        await store.write_candle(_candle())
        loaded = await store.get_candle("c1")
        assert loaded is not None
        assert loaded.outcome == "UP"
        assert loaded.close == pytest.approx(66830)
        await store.close()

    async def test_get_nonexistent_candle(self, tmp_path):
        store = SqliteStore(str(tmp_path / "test.db"))
        await store.init()
        assert await store.get_candle("nope") is None
        await store.close()

    async def test_write_and_read_snapshots(self, tmp_path):
        store = SqliteStore(str(tmp_path / "test.db"))
        await store.init()
        await store.write_snapshot(_snap(candle_id="c1", elapsed=0.1))
        await store.write_snapshot(_snap(candle_id="c1", elapsed=0.2))
        await store.write_snapshot(_snap(candle_id="c2", elapsed=0.1))

        snaps = await store.get_snapshots("c1")
        assert len(snaps) == 2
        assert snaps[0].elapsed_pct < snaps[1].elapsed_pct
        await store.close()

    async def test_snapshot_preserves_orderbook(self, tmp_path):
        store = SqliteStore(str(tmp_path / "test.db"))
        await store.init()
        await store.write_snapshot(_snap())
        snaps = await store.get_snapshots("c1")
        assert snaps[0].up_bids == ((0.50, 100.0),)
        assert snaps[0].btc_price == pytest.approx(66800.0)
        await store.close()
```

- [ ] **Step 3: Implement SqliteStore**

SQLite schema with key fields as real columns + orderbook as JSON:

```sql
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candle_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    tick_timestamp REAL NOT NULL,
    elapsed_pct REAL NOT NULL,
    btc_price REAL NOT NULL,
    btc_bid REAL NOT NULL,
    btc_ask REAL NOT NULL,
    up_last_trade REAL,
    down_last_trade REAL,
    market_volume REAL NOT NULL,
    orderbook_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_candle ON snapshots(candle_id);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(timestamp);

CREATE TABLE IF NOT EXISTS candles (
    candle_id TEXT PRIMARY KEY,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    outcome TEXT NOT NULL,
    final_ret REAL NOT NULL
);
```

`orderbook_json` contains: `{"up_bids": [...], "up_asks": [...], "down_bids": [...], "down_asks": [...]}`

Full implementation in `polybot/adapters/sqlite_store.py`:

```python
class SqliteStore:
    def __init__(self, db_path: str, logger=None): ...
    async def init(self) -> None: ...          # CREATE tables
    async def write_snapshot(self, s) -> None:  # INSERT into snapshots
    async def write_candle(self, r) -> None:    # INSERT OR REPLACE into candles
    async def get_candle(self, id) -> ...:      # SELECT from candles
    async def get_snapshots(self, id) -> ...:   # SELECT from snapshots WHERE candle_id=? ORDER BY timestamp
    async def close(self) -> None: ...          # aclose()
```

- [ ] **Step 4: Run tests — PASS**
- [ ] **Step 5: Commit**

---

### Task 3: Add candle close callback to CandleAggregator

**Files:**
- Modify: `polybot/services/candle_aggregator.py`
- Modify: `tests/services/test_candle_aggregator.py`

The aggregator is the single authority for candle closes. Add a callback so DataCollector gets notified with the authoritative Candle data.

- [ ] **Step 1: Add callback parameter to `__init__`**

```python
from collections.abc import Callable, Awaitable

# In __init__:
self._on_candle_close: Callable[[Candle], Awaitable[None]] | None = on_candle_close
```

New param: `on_candle_close: Callable[[Candle], Awaitable[None]] | None = None`

- [ ] **Step 2: Call it in `_close_current_candle` after appending to history**

After `self._history.append(candle)` and the log line:

```python
if self._on_candle_close is not None:
    try:
        await self._on_candle_close(candle)
    except Exception:
        self._log.exception("on_candle_close callback failed")
```

- [ ] **Step 3: Add test**

```python
async def test_on_candle_close_callback(self):
    closed_candles = []

    async def on_close(candle):
        closed_candles.append(candle)

    agg = _make_aggregator(interval=10)
    agg._on_candle_close = on_close
    agg._first_candle_complete = True
    _feed_ticks(agg, [_make_tick(price=100.0, timestamp=10.0)])
    await agg._close_current_candle()
    assert len(closed_candles) == 1
    assert closed_candles[0].close == 100.0
```

- [ ] **Step 4: Run all tests — PASS**
- [ ] **Step 5: Commit**

---

### Task 4: DataCollector service

**Files:**
- Create: `polybot/services/data_collector.py`
- Create: `tests/services/test_data_collector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/services/test_data_collector.py

import math
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock
import pytest
from polybot.domain.collection import Snapshot, CandleRecord
from polybot.domain.models import (
    BtcTick, Candle, Market, MarketSnapshot, OrderBook, OrderBookLevel, PartialCandle,
)
from polybot.services.data_collector import DataCollector


def _tick(price=66800.0):
    return BtcTick(price=price, bid=price-2, ask=price+2, timestamp=time.time())

def _market():
    return Market(
        condition_id="0xabc", up_token_id="up", down_token_id="down",
        slug="btc-updown-5m-1000", question="?", end_time=time.time()+200,
    )

def _book():
    return OrderBook(
        bids=(OrderBookLevel(0.50, 100), OrderBookLevel(0.49, 200)),
        asks=(OrderBookLevel(0.51, 150), OrderBookLevel(0.52, 300)),
        timestamp=time.time(),
    )

def _msnapshot():
    return MarketSnapshot(
        market=_market(), up_book=_book(), down_book=_book(),
        last_trade_price=0.50, down_last_trade_price=0.50, volume=5000,
    )

def _collector():
    candles = MagicMock()
    type(candles).latest_tick = PropertyMock(return_value=_tick())
    type(candles).partial = PropertyMock(return_value=PartialCandle(
        open=66800, high=66850, low=66780, last_price=66830,
        start_time=time.time()-100, end_time=time.time()+200,
        tick_count=5, last_tick_time=time.time(),
    ))
    feed = AsyncMock()
    feed.discover_market = AsyncMock(return_value=_market())
    feed.get_snapshot = AsyncMock(return_value=_msnapshot())
    store = AsyncMock()
    return DataCollector(candles, feed, store)


class TestCollectOnce:
    async def test_writes_snapshot(self):
        c = _collector()
        await c.collect_once()
        c._store.write_snapshot.assert_awaited_once()

    async def test_snapshot_has_prices(self):
        c = _collector()
        await c.collect_once()
        snap = c._store.write_snapshot.call_args[0][0]
        assert isinstance(snap, Snapshot)
        assert snap.btc_price == pytest.approx(66800)
        assert snap.up_last_trade == pytest.approx(0.50)

    async def test_snapshot_has_tick_timestamp(self):
        c = _collector()
        await c.collect_once()
        snap = c._store.write_snapshot.call_args[0][0]
        assert snap.tick_timestamp > 0
        assert snap.tick_timestamp <= snap.timestamp

    async def test_no_write_without_tick(self):
        c = _collector()
        type(c._candles).latest_tick = PropertyMock(return_value=None)
        await c.collect_once()
        c._store.write_snapshot.assert_not_awaited()

    async def test_no_write_without_market(self):
        c = _collector()
        c._market_feed.discover_market = AsyncMock(return_value=None)
        await c.collect_once()
        c._store.write_snapshot.assert_not_awaited()


class TestOnCandleClose:
    async def test_writes_candle_record(self):
        c = _collector()
        candle = Candle(open=66800, high=66850, low=66780, close=66830,
                        volume=15.0, start_time=1000, end_time=1300)
        await c.on_candle_close(candle)
        c._store.write_candle.assert_awaited_once()

    async def test_candle_outcome_up(self):
        c = _collector()
        candle = Candle(open=66800, high=66850, low=66780, close=66830,
                        volume=15.0, start_time=1000, end_time=1300)
        await c.on_candle_close(candle)
        rec = c._store.write_candle.call_args[0][0]
        assert rec.outcome == "UP"
        assert rec.final_ret == pytest.approx(math.log(66830/66800), rel=1e-4)

    async def test_candle_outcome_down(self):
        c = _collector()
        candle = Candle(open=66800, high=66850, low=66780, close=66750,
                        volume=15.0, start_time=1000, end_time=1300)
        await c.on_candle_close(candle)
        rec = c._store.write_candle.call_args[0][0]
        assert rec.outcome == "DOWN"
```

- [ ] **Step 2: Run tests — FAIL**

- [ ] **Step 3: Implement DataCollector**

```python
# polybot/services/data_collector.py
"""Service: collects raw market snapshots, writes candle records on close."""

from __future__ import annotations

import asyncio
import logging
import math
import time

from polybot.domain.collection import CandleRecord, Snapshot
from polybot.domain.models import Candle
from polybot.ports.candle_source import CandleSource
from polybot.ports.data_store import DataStore
from polybot.ports.market_feed import MarketFeed

CANDLE_INTERVAL = 300
COLLECT_INTERVAL = 5
MAX_OB_LEVELS = 10


class DataCollector:
    """Passive recorder: samples market data every 5s, writes candles on close.

    Does NOT maintain candle lifecycle — that's CandleAggregator's job.
    Candle close events come via on_candle_close callback.
    """

    def __init__(
        self,
        candle_source: CandleSource,
        market_feed: MarketFeed,
        store: DataStore,
        series_slug: str = "btc-updown-5m",
        logger: logging.Logger | None = None,
    ) -> None:
        self._candles = candle_source
        self._market_feed = market_feed
        self._store = store
        self._series_slug = series_slug
        self._log = logger or logging.getLogger(__name__)

    async def run(self) -> None:
        while True:
            try:
                await self.collect_once()
            except Exception:
                self._log.exception("Collection error")
            await asyncio.sleep(COLLECT_INTERVAL)

    async def collect_once(self) -> None:
        # Snapshot state before awaits
        tick = self._candles.latest_tick
        if tick is None:
            return

        partial = self._candles.partial
        now = time.time()

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            return

        snapshot = await self._market_feed.get_snapshot(market)

        # Compute elapsed
        candle_start = partial.start_time if partial else now - (now % CANDLE_INTERVAL)
        elapsed_pct = max(0.0, min((now - candle_start) / CANDLE_INTERVAL, 1.0))

        snap = Snapshot(
            timestamp=now,
            tick_timestamp=tick.timestamp,
            candle_id=market.slug,
            elapsed_pct=elapsed_pct,
            btc_price=tick.price,
            btc_bid=tick.bid,
            btc_ask=tick.ask,
            up_bids=self._levels(snapshot.up_book.bids),
            up_asks=self._levels(snapshot.up_book.asks),
            down_bids=self._levels(snapshot.down_book.bids),
            down_asks=self._levels(snapshot.down_book.asks),
            up_last_trade=snapshot.last_trade_price,
            down_last_trade=snapshot.down_last_trade_price,
            market_volume=snapshot.volume,
        )
        await self._store.write_snapshot(snap)

    async def on_candle_close(self, candle: Candle) -> None:
        """Called by CandleAggregator when a candle closes."""
        outcome = "UP" if candle.close >= candle.open else "DOWN"
        final_ret = math.log(candle.close / candle.open) if candle.open > 0 else 0.0

        # Use market slug as candle_id — derive from candle start_time
        boundary = int(candle.start_time - (candle.start_time % CANDLE_INTERVAL))
        candle_id = f"btc-updown-5m-{boundary}"

        record = CandleRecord(
            candle_id=candle_id,
            start_time=candle.start_time,
            end_time=candle.end_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            outcome=outcome,
            final_ret=final_ret,
        )
        await self._store.write_candle(record)
        self._log.info("Candle recorded: %s outcome=%s ret=%.4f", candle_id, outcome, final_ret)

    @staticmethod
    def _levels(book_levels: tuple, max_n: int = MAX_OB_LEVELS) -> tuple[tuple[float, float], ...]:
        return tuple((lvl.price, lvl.size) for lvl in book_levels[:max_n])
```

- [ ] **Step 4: Run tests — PASS**
- [ ] **Step 5: Commit**

---

### Task 5: Wire into __main__.py

**Files:**
- Modify: `polybot/__main__.py`

- [ ] **Step 1: Add imports and wiring**

```python
from polybot.adapters.sqlite_store import SqliteStore
from polybot.services.data_collector import DataCollector
```

In `main()`:
```python
store = SqliteStore("data/collection.db")
await store.init()
collector = DataCollector(aggregator, market_feed, store)

# Pass collector's candle close handler to the aggregator
aggregator = CandleAggregator(price_stream, volume_feed, on_candle_close=collector.on_candle_close)
```

Note: aggregator must be created AFTER collector since it needs the callback. Reorder construction.

Add `collector.run()` to gather:
```python
await asyncio.gather(aggregator.run(), poll_state(service), collector.run())
```

Add cleanup:
```python
finally:
    ...
    await store.close()
```

- [ ] **Step 2: Create data directory**

```bash
mkdir -p data
```

Add `data/*.db` to `.gitignore` if not already covered.

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`

- [ ] **Step 4: Smoke test**

Run: `uv run python -m polybot`

After 30s+, verify:
```bash
sqlite3 data/collection.db "SELECT COUNT(*) FROM snapshots;"
sqlite3 data/collection.db "SELECT candle_id, btc_price, up_last_trade, elapsed_pct FROM snapshots ORDER BY timestamp DESC LIMIT 5;"
```

After a candle closes (~5 min):
```bash
sqlite3 data/collection.db "SELECT * FROM candles;"
```

- [ ] **Step 5: Commit**

---

### Task 6: Codex review

- [ ] **Step 1:** Run `/codex:rescue --model gpt-5.4` on all new/changed files
- [ ] **Step 2:** Fix any issues found
- [ ] **Step 3:** `uv run pytest tests/ -v` — ALL PASS
