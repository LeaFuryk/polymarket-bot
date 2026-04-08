# Polymarket Resolution + Log Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Polymarket's Gamma API `eventMetadata`) as the authoritative source for candle open/close/outcome. Fix records asynchronously without blocking the collector loop. Suppress verbose HTTP logs.

**Architecture:** Add `get_resolution()` to PolymarketAdapter. Add `update_candle()` to DataStore. DataCollector writes the candle immediately with Chainlink values, then fires an async background task that waits a few seconds, fetches Polymarket resolution, and if open/close/outcome differ → updates the DB record and re-broadcasts the corrected candle.

**Tech Stack:** Python 3.11, httpx, aiosqlite, pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `polybot_data/adapters/polymarket.py` | Modify | Add `get_resolution(slug)` method |
| `polybot_data/ports/data_store.py` | Modify | Add `update_candle()` to protocol |
| `polybot_data/adapters/sqlite_store.py` | Modify | Implement `update_candle()` |
| `polybot_data/services/data_collector.py` | Modify | Fire-and-forget resolution check after candle write |
| `collector/__main__.py` | Modify | Suppress httpx log level |

---

### Task 1: Add get_resolution to PolymarketAdapter

**Files:**
- Modify: `polybot_data/adapters/polymarket.py`

- [ ] **Step 1: Add the method**

Add to `PolymarketAdapter`:

```python
async def get_resolution(self, slug: str) -> dict | None:
    """Fetch Polymarket resolution from Gamma API eventMetadata.

    Returns dict with:
        open: float (priceToBeat)
        close: float (finalPrice)
        outcome: str ("UP" or "DOWN")
    Or None if resolution not available yet.
    """
    try:
        resp = await self._gamma_client.get("/events", params={"slug": slug})
        resp.raise_for_status()
        events = resp.json()
        if not events:
            return None

        event = events[0]
        meta = event.get("eventMetadata", {})
        if isinstance(meta, str):
            meta = json.loads(meta)

        price_to_beat = meta.get("priceToBeat")
        final_price = meta.get("finalPrice")
        if price_to_beat is None or final_price is None:
            return None

        mkt = event.get("markets", [{}])[0]
        outcome_prices = mkt.get("outcomePrices", "[]")
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        if len(outcome_prices) < 2:
            return None

        up_price = float(outcome_prices[0])
        outcome = "UP" if up_price > 0.5 else "DOWN"

        return {
            "open": float(price_to_beat),
            "close": float(final_price),
            "outcome": outcome,
        }
    except Exception:
        self._log.exception("Failed to fetch resolution for %s", slug)
        return None
```

- [ ] **Step 2: Run tests, commit**

---

### Task 2: Add update_candle to DataStore port + SqliteStore

**Files:**
- Modify: `polybot_data/ports/data_store.py`
- Modify: `polybot_data/adapters/sqlite_store.py`

- [ ] **Step 1: Add to port**

Add to `DataStore` protocol:

```python
async def update_candle(self, candle_id: str, open: float, close: float, outcome: str, final_ret: float) -> None: ...
```

- [ ] **Step 2: Implement in SqliteStore**

```python
async def update_candle(self, candle_id: str, open: float, close: float, outcome: str, final_ret: float) -> None:
    """Update open, close, outcome, final_ret for an existing candle."""
    assert self._db is not None
    await self._db.execute(
        "UPDATE candles SET open = ?, close = ?, outcome = ?, final_ret = ? WHERE candle_id = ?",
        (open, close, outcome, final_ret, candle_id),
    )
    await self._db.commit()
```

- [ ] **Step 3: Run tests, commit**

---

### Task 3: Async resolution check in DataCollector

**Files:**
- Modify: `polybot_data/services/data_collector.py`

- [ ] **Step 1: Update _on_candle_close**

Keep the current flow intact — write CandleRecord and broadcast immediately with Chainlink values. Then fire a background task to check and correct:

```python
async def _on_candle_close(self, candle: Candle) -> None:
    """Handle candle_close event from CandleAggregator."""
    if not self._recording:
        self._recording = True
        self._log.info("🟢 First candle closed — recording active")

    outcome = "UP" if candle.close >= candle.open else "DOWN"
    final_ret = math.log(candle.close / candle.open) if candle.open > 0 else 0.0

    boundary = int(candle.start_time - (candle.start_time % CANDLE_INTERVAL))
    candle_id = f"{self._series_slug}-{boundary}"

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
    self._log.info(
        "🕯️ Candle closed | %s | O=$%.2f C=$%.2f | outcome=%s ret=%+.4f",
        candle_id,
        record.open,
        record.close,
        outcome,
        final_ret,
    )

    # Broadcast immediately with Chainlink values
    if self._broadcast_fn is not None:
        msg = asdict(record)
        msg["type"] = "candle_close"
        await self._broadcast_fn(msg)

    # Fire-and-forget: check Polymarket resolution and correct if needed
    asyncio.create_task(self._verify_resolution(candle_id, record))
```

- [ ] **Step 2: Add _verify_resolution method**

```python
async def _verify_resolution(self, candle_id: str, original: CandleRecord) -> None:
    """Background task: fetch Polymarket resolution and update DB if prices differ."""
    await asyncio.sleep(5)  # wait for Polymarket to resolve

    resolution = await self._market_feed.get_resolution(candle_id)
    if resolution is None:
        self._log.warning("⚠️ No Polymarket resolution for %s — keeping Chainlink values", candle_id)
        return

    pm_open = resolution["open"]
    pm_close = resolution["close"]
    pm_outcome = resolution["outcome"]

    chainlink_outcome = "UP" if original.close >= original.open else "DOWN"

    if pm_outcome == chainlink_outcome and abs(pm_open - original.open) < 0.01:
        return  # no correction needed

    final_ret = math.log(pm_close / pm_open) if pm_open > 0 else 0.0

    await self._store.update_candle(
        candle_id=candle_id,
        open=pm_open,
        close=pm_close,
        outcome=pm_outcome,
        final_ret=final_ret,
    )

    self._log.warning(
        "🔄 Polymarket correction | %s | %s→%s | open: $%.2f→$%.2f | close: $%.2f→$%.2f",
        candle_id,
        chainlink_outcome,
        pm_outcome,
        original.open,
        pm_open,
        original.close,
        pm_close,
    )

    # Re-broadcast corrected candle
    if self._broadcast_fn is not None:
        corrected = CandleRecord(
            candle_id=candle_id,
            start_time=original.start_time,
            end_time=original.end_time,
            open=pm_open,
            high=original.high,
            low=original.low,
            close=pm_close,
            volume=original.volume,
            outcome=pm_outcome,
            final_ret=final_ret,
        )
        msg = asdict(corrected)
        msg["type"] = "candle_correction"
        await self._broadcast_fn(msg)
```

- [ ] **Step 3: Run tests, commit**

---

### Task 4: Suppress httpx verbose logging

**Files:**
- Modify: `collector/__main__.py`

- [ ] **Step 1: Add after line 18 (logging.basicConfig)**

```python
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
```

- [ ] **Step 2: Verify manually — only `📸 Snapshot saved` and `🕯️ Candle closed` lines in console**

- [ ] **Step 3: Commit**
