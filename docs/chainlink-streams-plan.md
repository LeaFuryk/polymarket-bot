# Chainlink Data Streams — Implementation Plan

> **Goal:** Connect to Chainlink Data Streams via WebSocket and stream real-time
> BTC/USD price ticks (price, bid, ask). First module on the new hexagonal architecture.

---

## Context

Polymarket resolves candles using Chainlink prices. Our legacy bot used Binance,
causing resolution mismatches. Chainlink Data Streams is the exact source.

### Credentials

Already in `.env`:
- `CH_STREAM_USER_ID` — API key (UUID)
- `CH_STREAM_SECRET` — HMAC signing secret

---

## Chainlink Data Streams API

| Detail | Value |
|---|---|
| WebSocket URL | `wss://ws.dataengine.chain.link` |
| REST URL (fallback) | `https://api.dataengine.chain.link` |
| Auth | HMAC-SHA256 (3 headers) |
| Report schema | V3 (Crypto Advanced) |
| BTC/USD feed ID | `0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8` |
| Decimals | 18 (divide by 10^18) |

### V3 report — fields per tick

| Field | Description |
|---|---|
| `benchmarkPrice` | DON consensus median BTC/USD price |
| `bid` | Liquidity-weighted simulated buy price |
| `ask` | Liquidity-weighted simulated sell price |
| `observationsTimestamp` | When price was observed (seconds) |
| `validFromTimestamp` | Start of validity window |
| `expiresAt` | Report expiry |

No volume. No volatility. Just price + bid/ask.

### Authentication

3 headers required per request/connection:

1. `Authorization` — API key
2. `X-Authorization-Timestamp` — milliseconds since epoch (within 5s of server)
3. `X-Authorization-Signature-SHA256` — HMAC-SHA256 of signing string

```
Signing string: "{method} {path} {sha256(body)} {api_key} {timestamp_ms}"
```

### REST endpoints (for fallback / backfill)

| Endpoint | Description |
|---|---|
| `GET /api/v1/reports/latest?feedID={id}` | Latest report |
| `GET /api/v1/reports?feedID={id}&timestamp={ts}` | Report at timestamp |
| `GET /api/v1/reports/page?feedID={id}&startTimestamp={ts}` | Paginated history |

---

## Architecture

```
polybot/
├── domain/
│   └── models.py                  # BtcTick (pure data)
│
├── ports/
│   └── price_stream.py            # PriceStream protocol
│
├── adapters/
│   └── chainlink_streams.py       # Implements PriceStream via WebSocket
│
└── services/
    └── (none yet)
```

### Dependency rule

```
domain  ←  ports  ←  adapters
```

- Domain: no imports from anywhere
- Ports: import only domain models
- Adapters: implement ports, import domain models

---

## Implementation

### Step 1: Domain model

`polybot/domain/models.py`

```python
@dataclass(frozen=True)
class BtcTick:
    price: float         # benchmarkPrice (USD)
    bid: float           # liquidity-weighted bid
    ask: float           # liquidity-weighted ask
    timestamp: float     # observationsTimestamp (seconds)
```

Frozen, immutable, no dependencies.

### Step 2: Port

`polybot/ports/price_stream.py`

```python
from typing import Protocol, AsyncIterator

class PriceStream(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def ticks(self) -> AsyncIterator[BtcTick]: ...
```

Streaming interface. Adapter pushes ticks, consumer pulls them.

### Step 3: Chainlink adapter

`polybot/adapters/chainlink_streams.py`

```python
class ChainlinkStreamsAdapter:
    """PriceStream implementation using Chainlink Data Streams WebSocket."""

    def __init__(self, user_id: str, secret: str, feed_id: str): ...

    async def connect(self) -> None:
        """Open WebSocket, authenticate, subscribe to feed."""

    async def disconnect(self) -> None:
        """Close WebSocket connection."""

    async def ticks(self) -> AsyncIterator[BtcTick]:
        """Yield BtcTick for each incoming V3 report."""

    def _build_auth_headers(self, method: str, path: str) -> dict[str, str]:
        """Generate the 3 HMAC-SHA256 headers."""

    def _parse_v3_report(self, raw: dict) -> BtcTick:
        """Decode V3 report into BtcTick."""
```

Responsibilities:
- WebSocket lifecycle (connect, reconnect on drop, disconnect)
- HMAC-SHA256 authentication header generation
- V3 report parsing (int256 / 10^18 → float)
- Yield `BtcTick` per incoming message

Does NOT:
- Aggregate candles
- Compute indicators
- Broadcast to dashboard
- Know about Polymarket or trading logic

Dependencies: `websockets` (already in pyproject.toml).

### Step 4: Tests

`tests/domain/test_models.py`
- `BtcTick` is frozen
- Fields are correct types

`tests/adapters/test_chainlink_streams.py`
- HMAC header generation (known input → expected output)
- V3 report parsing (raw dict → `BtcTick` with correct price/bid/ask)
- Malformed report → handled gracefully
- Reconnection logic on WebSocket disconnect

`tests/ports/test_price_stream.py`
- `ChainlinkStreamsAdapter` satisfies `PriceStream` protocol

### Step 5: Smoke script

`polybot/__main__.py`

```python
async def main():
    feed = ChainlinkStreamsAdapter(
        user_id=os.environ["CH_STREAM_USER_ID"],
        secret=os.environ["CH_STREAM_SECRET"],
        feed_id=BTC_USD_FEED_ID,
    )
    await feed.connect()
    async for tick in feed.ticks():
        spread = tick.ask - tick.bid
        print(f"BTC ${tick.price:,.2f}  bid ${tick.bid:,.2f}  ask ${tick.ask:,.2f}  spread ${spread:.2f}")
```

Run with: `uv run python -m polybot`

---

## What this delivers

- WebSocket connection to Chainlink Data Streams with HMAC auth
- Real-time BTC/USD tick stream (price, bid, ask)
- V3 report decoding
- Auto-reconnect on disconnect
- Clean hexagonal boundaries (domain / port / adapter)

## What comes after (separate PRs)

- Candle aggregation from ticks (service layer)
- Volume from Binance (separate adapter + port)
- Technicals computation (RSI, MACD, BB, ATR)
- Polymarket CLOB adapter
- LLM prompt builder
