# Codex Review Fixes — Implementation Plan

> **Goal:** Address all findings from the Codex code review (3 High, 4 Medium, 2 Low).

---

## High Priority

### 1. Candles only close on next tick (feed stall = frozen candles)
**File:** `candle_aggregator.py`
Add `check_expired()` — if partial candle's `end_time` has passed, close it.
Called from `__main__` polling loop every 30s.

### 2. get_state() reads aggregator before and after awaits (race condition)
**File:** `market_state.py`
Snapshot `tick`, `candles`, `partial`, `closed` from aggregator BEFORE any await.
Use that consistent snapshot throughout the build.

### 3. Timing uses wall-clock instead of tick/partial timestamps
**File:** `market_state.py`
Use `partial.start_time` for candle boundary, `tick.timestamp` for elapsed.
Keep `time.time()` only for `chainlink_heartbeat_age_sec` (that's wall-clock by definition).

---

## Medium Priority

### 4. RSI returns 100 for flat series (should be 50)
**File:** `technicals.py`
Add: `if avg_gain == 0 and avg_loss == 0: return 50.0`

### 5. Backfill blindly drops last kline
**File:** `candle_aggregator.py`
Check if last kline's `end_time > now` before dropping. If it's already closed, keep it.

### 6. vol_pace leaks future info (non-causal)
**File:** `candle_aggregator.py`
Use trailing 20-bar window up to each candle instead of global average.

### 7. Market discovery misses previous boundary
**File:** `polymarket.py`
Try current → previous → next boundary instead of current → next.

---

## Low Priority

### 8. Bollinger uses sample stdev
**File:** `technicals.py`
Switch `statistics.stdev` → `statistics.pstdev`.

### 9. Market.time_remaining uses wall-clock in domain model
**File:** `domain/models.py`
Remove property. Compute in `market_state.py` instead. Domain stays pure.

---

## Verification

1. `uv run pytest tests/ -v` — all pass
2. Re-run Codex review on changed files
