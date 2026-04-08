# AgentService Design Spec

## Goal

AgentService maintains the bot's live state (prior candles + current candle snapshots) and computes 56 technical indicators every second, producing the exact row the trained model expects — minus `outcome`.

## Architecture

Hexagonal. AgentService depends on ports, not adapters. Pure indicator functions live in a shared module (`indicator_engine`), moved from the notebook.

## Components

### Port: `CandleRepository`

**File:** `polybot/ports/candle_repository.py`

```python
@runtime_checkable
class CandleRepository(Protocol):
    async def get_recent_candles(self, limit: int) -> list[dict]: ...
```

Returns candle dicts ordered oldest-first, matching the shape `compute_all` expects:
```python
{"open": float, "high": float, "low": float, "close": float, "volume": float, "start_time": float, "end_time": float, "outcome": str, "final_ret": float}
```

### Adapter: `SqliteCandleRepository`

**File:** `polybot/adapters/sqlite_candle_repo.py`

Implements `CandleRepository`. Opens SQLite in **read-only mode** (`file:...?mode=ro`). Queries:

```sql
SELECT * FROM candles ORDER BY start_time DESC LIMIT ?
```

Then reverses to oldest-first. Connection opened once at init, closed on shutdown.

### Service: `indicator_engine`

**File:** `polybot_data/services/indicator_engine.py`

Moved from `notebooks/technicals.py`. Contains all 56 indicator functions + `compute_all()`. Pure, stateless. The notebook imports from here instead of its local copy.

No changes to the computation logic — just relocation.

### Service: `AgentService`

**File:** `polybot/services/agent_service.py`

**Dependencies (injected):**
- `candle_repo: CandleRepository` — fetch prior candles on sync
- `logger: Logger | None`

**State:**
- `_prior_candles: list[dict]` — completed candles (rolling window, 35 deep)
- `_snapshots_so_far: list[dict]` — snapshots accumulated in current candle
- `_candle_open: float | None` — BTC open price of current candle
- `_current_candle_id: str | None` — tracks candle boundary
- `_synced: bool` — False until first candle_close seen

**Lifecycle:**

1. **Not synced** (`_synced = False`):
   - `on_snapshot()` — no-op
   - `on_candle_close()` — fetch 35 candles from repo, set `_synced = True`, log sync complete

2. **Synced** (`_synced = True`):
   - `on_snapshot(msg)`:
     - If `candle_id` changed from `_current_candle_id`: reset `_snapshots_so_far`, set `_candle_open` from `btc_price`, update `_current_candle_id`
     - Append snapshot to `_snapshots_so_far`
     - Call `compute_all(_prior_candles, _candle_open, _snapshots_so_far)`
     - Build row dict, log it
   - `on_candle_close(msg)`:
     - Append candle dict to `_prior_candles` (trim to 35)
     - Reset `_snapshots_so_far`
     - Reset `_candle_open`

**Row format (printed every second):**
```python
{
    "candle_id": str,
    "timestamp": float,
    "elapsed_pct": float,
    "btc_price": float,
    "up_best_bid": float | None,
    "up_best_ask": float | None,
    "up_bid_depth": float | None,
    "up_ask_depth": float | None,
    "down_best_bid": float | None,
    "down_best_ask": float | None,
    "down_bid_depth": float | None,
    "down_ask_depth": float | None,
    "market_volume": float,
    **indicators,  # 56 indicator values from compute_all
}
```

### Wiring: `__main__.py`

```
CollectorClient._handle_message(raw):
    msg = json.loads(raw)
    if snapshot:
        agent_service.on_snapshot(msg)
    elif candle_close:
        await agent_service.on_candle_close(msg)
    relay.broadcast_json(msg)
```

`AgentService.on_candle_close` is async (fetches from SQLite on first call). `on_snapshot` is sync (pure computation).

The CollectorClient needs a way to dispatch messages to AgentService. Two options evaluated:

- **Inject AgentService into CollectorClient**: adds coupling, CollectorClient shouldn't know about agents
- **Dispatch in `__main__`**: CollectorClient already has the `on_message` callback pattern we considered earlier. Instead, we use a simple message handler list or just wire it in main.

**Chosen approach:** CollectorClient accepts an optional `on_message` async callback. `__main__` creates a dispatcher that calls both AgentService and Broadcaster:

```python
async def on_message(msg: dict) -> None:
    msg_type = msg.get("type")
    if msg_type == "snapshot":
        agent.on_snapshot(msg)
    elif msg_type == "candle_close":
        await agent.on_candle_close(msg)
    await broadcaster.broadcast_json(msg)

client = CollectorClient(on_message=on_message)
```

This replaces the `relay: MessageRelay` injection. The dispatcher in `__main__` is the composition root — it knows about both AgentService and Broadcaster, but neither knows about each other.

## What This Does NOT Include

- Model inference (future)
- Bet state tracking (future)
- Trading execution (future)
- Dashboard-specific transformations (future)

## Testing

- `indicator_engine`: existing notebook validation serves as integration test; unit tests for `compute_all` with known inputs
- `SqliteCandleRepository`: test with in-memory SQLite
- `AgentService`: test lifecycle (not synced → sync → snapshot → candle close), mock the repo
- Row output: verify shape matches expected 56 indicators + 13 market state fields
