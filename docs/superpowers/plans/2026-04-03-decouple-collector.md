# Decouple Collector — Three-Package Architecture

> **Goal:** Split the codebase into 3 packages: shared data layer, standalone
> collector/data server, and pure-consumer bot.

## Architecture

```
polybot_data/              # shared package — models, ports, adapters
  domain/                  # Candle, Snapshot, OrderBook, Market, etc.
  ports/                   # PriceStream, MarketFeed, VolumeFeed, DataStore, CandleSource
  adapters/                # Chainlink, Binance, Polymarket, SQLite
  services/                # CandleAggregator, DataCollector, technicals

collector/                 # data server process (uv run python -m collector)
  __main__.py              # wires adapters → aggregator → WS server → SQLite
  server.py                # local WebSocket broadcaster

polybot/                   # bot process (uv run python -m polybot)
  __main__.py              # connects to collector WS + reads SQLite for history
  services/                # MarketStateService, prompt builder
  adapters/                # collector_client.py (WS consumer implementing CandleSource)
```

### Dependency graph

```
collector/ ──imports──→ polybot_data/
polybot/   ──imports──→ polybot_data/  (models + ports only, never adapters)
polybot/   ──connects──→ collector/    (via WebSocket, not import)
```

The bot **never** imports Chainlink, Binance, or Polymarket adapters.
It only knows domain models, ports, and the collector's WebSocket protocol.

## WebSocket protocol (localhost:8765)

Two message types:

### 1. `snapshot` — every ~1s (saved to SQLite every 5s)

```json
{
  "type": "snapshot",
  "timestamp": 1775183100.5,
  "tick_timestamp": 1775183100.2,
  "candle_id": "btc-updown-5m-1775183100",
  "elapsed_pct": 0.42,
  "btc_price": 66800.0,
  "btc_bid": 66798.0,
  "btc_ask": 66802.0,
  "up_bids": [[0.50, 100], [0.49, 200]],
  "up_asks": [[0.51, 150], [0.52, 300]],
  "down_bids": [[0.49, 120]],
  "down_asks": [[0.52, 180]],
  "up_last_trade": 0.52,
  "down_last_trade": 0.48,
  "market_volume": 5000.0
}
```

### 2. `candle_close` — every ~5 min (saved to SQLite immediately)

```json
{
  "type": "candle_close",
  "candle_id": "btc-updown-5m-1775183100",
  "open": 66800.0,
  "high": 66850.0,
  "low": 66780.0,
  "close": 66830.0,
  "volume": 15.0,
  "outcome": "UP",
  "final_ret": 0.00045
}
```

**Bot behavior:** On receiving `candle_close`, bot has the outcome directly
in the message — no SQLite query needed. Discards remaining snapshots from
the old candle and starts fresh with the next `snapshot`'s `candle_id`.

## What moves where

### `polybot_data/` (new shared package)

Move FROM current `polybot/`:
- `domain/models.py` → `polybot_data/domain/models.py`
- `domain/collection.py` → `polybot_data/domain/collection.py`
- `ports/*` → `polybot_data/ports/`
- `adapters/chainlink_streams.py` → `polybot_data/adapters/`
- `adapters/binance_volume.py` → `polybot_data/adapters/`
- `adapters/polymarket.py` → `polybot_data/adapters/`
- `adapters/sqlite_store.py` → `polybot_data/adapters/`
- `services/candle_aggregator.py` → `polybot_data/services/`
- `services/data_collector.py` → `polybot_data/services/`
- `services/technicals.py` → `polybot_data/services/`

### `collector/` (new entry point)

Create:
- `collector/__init__.py`
- `collector/__main__.py` — wires Chainlink + Binance + Polymarket + CandleAggregator + DataCollector + WS server
- `collector/server.py` — WebSocket server broadcasting ticks/snapshots/candle_close to connected clients

### `polybot/` (rewritten as pure consumer)

Keep:
- `polybot/__init__.py`
- `polybot/__main__.py` — rewritten: connect to collector WS, read SQLite for history, build prompt
- `polybot/services/market_state.py` — reads from collector client instead of CandleSource directly
- `polybot/services/prompt_builder.py` — extracted from current `__main__.py` format_prompt

Create:
- `polybot/adapters/collector_client.py` — WS client that receives ticks/snapshots/candle_close and implements CandleSource protocol

Remove (moved to polybot_data):
- All adapters (chainlink, binance, polymarket, sqlite)
- All domain models
- All ports
- candle_aggregator, data_collector, technicals

### `pyproject.toml`

Update `[tool.setuptools.packages.find]` to find all three packages:
```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["polybot*", "polybot_data*", "collector*"]
```

## Run commands

```bash
# Terminal 1 — data server (always running, records to SQLite)
uv run python -m collector

# Terminal 2 — bot (connects when needed, pure consumer)
uv run python -m polybot

# Debug — see raw WebSocket stream
wscat -c ws://localhost:8765
```

## Implementation order

1. Create `polybot_data/` — move models, ports, adapters, core services
2. Update all imports across the codebase
3. Create `collector/` — new entry point + WS server
4. Create `polybot/adapters/collector_client.py` — WS consumer
5. Rewrite `polybot/__main__.py` — pure consumer
6. Update tests
7. Verify both run commands work independently

