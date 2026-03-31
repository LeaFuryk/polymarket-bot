# Chainlink On-Chain Price Feed — Migration Plan

> **Goal:** Replace unreliable Polymarket RTDS WebSocket and non-matching Binance prices
> with direct Chainlink on-chain reads from Polygon, giving us the **exact resolution
> source** for real-time BTC price during candles.

---

## Problem

| Current source | Role | Issue |
|---|---|---|
| Polymarket RTDS WebSocket | Was meant to be primary Chainlink price | Constantly disconnects, demoted to "cross-reference only" in code |
| Binance spot API | De facto primary BTC price | **Doesn't match Polymarket resolution prices** — different source, different timestamps |
| Binance klines | Historical price lookup (`get_price_at`) | Same mismatch — resolution disagreements with actual market outcomes |
| Chainlink Ethereum RPC | Cross-reference only | Ethereum mainnet feed: 1-hour heartbeat, 0.5% deviation — too slow |

The core issue: we calculate PnL and make trading decisions based on Binance prices,
but Polymarket resolves candles using Chainlink prices. Any divergence means our signals
and resolution calculations can disagree with reality.

---

## Solution

Read the **Chainlink BTC/USD aggregator on Polygon** directly via `eth_call`. This is
the same data source Polymarket uses for resolution.

| Parameter | Polygon BTC/USD feed |
|---|---|
| Contract | `0xc907E116054Ad103354f2D350FD2514433D57F6f` |
| Heartbeat | 27 seconds |
| Deviation threshold | 0.1% (~$90 at $90k BTC) |
| Oracle nodes | 16 |
| Decimals | 8 |
| Cost | Free (permissionless `eth_call`) |
| RPC | Any public Polygon RPC (Alchemy, Infura, publicnode) |

### What stays the same

- **Candle resolution** — still comes from Polymarket (the bet lives there)
- **`BtcCandle` model** — same OHLCV structure
- **Dashboard, indicators, velocity** — all consume `BtcPrice` and `BtcCandle` unchanged

### What changes

| Concern | Before | After |
|---|---|---|
| Real-time BTC price | Binance spot API | Chainlink Polygon `latestRoundData()` |
| 5-min candle history | Binance klines API | Chainlink Polygon `getRoundData()` backfill |
| Cross-reference | Chainlink WS or Ethereum RPC | Removed (primary IS Chainlink now) |
| Price source in `BtcPrice` | `"binance"` | `"chainlink_polygon"` |
| Fallback | CoinGecko | Binance (demoted to fallback) |
| ChainlinkWSFeed | Started at boot, mostly broken | Removed entirely |

---

## Contract Interface

### `latestRoundData()` — current price

Function selector: `0xfeaf968c`

```
Returns: (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
```

- `answer` = BTC price × 10^8 (e.g. `8953214000000` = $89,532.14)
- `updatedAt` = unix timestamp of last update
- `roundId` = sequential, can walk backwards for history

### `getRoundData(uint80 _roundId)` — historical price

Function selector: `0x9a6fc8f5`

```
Input: roundId (uint80, padded to 32 bytes)
Returns: same 5-tuple as latestRoundData
```

Walk backwards from `latestRoundData().roundId` to reconstruct price history.

### Raw `eth_call` (no web3 library needed)

```python
# latestRoundData
resp = await client.post(rpc_url, json={
    "jsonrpc": "2.0",
    "method": "eth_call",
    "params": [{"to": CONTRACT, "data": "0xfeaf968c"}, "latest"],
    "id": 1,
})

# getRoundData(roundId)
# Selector 0x9a6fc8f5 + roundId padded to 32 bytes
data = "0x9a6fc8f5" + hex(round_id)[2:].zfill(64)
resp = await client.post(rpc_url, json={
    "jsonrpc": "2.0",
    "method": "eth_call",
    "params": [{"to": CONTRACT, "data": data}, "latest"],
    "id": 1,
})
```

---

## Architecture

```
BEFORE:
  Binance API ──(primary)──> BtcPriceFeed.get_price() ──> BtcPrice(source="binance")
  CoinGecko   ──(fallback)──┘
  RTDS WS     ──(cross-ref, broken)── divergence display only
  Ethereum RPC──(cross-ref, slow)────┘

AFTER:
  Polygon RPC ──(primary)──> BtcPriceFeed.get_price() ──> BtcPrice(source="chainlink_polygon")
  Binance API ──(fallback)──┘
  CoinGecko   ──(fallback)──┘

  Resolution: still from Polymarket (market outcome), not BTC price source
```

---

## Implementation

### Phase 1: New Polygon Chainlink reader

**New file: `src/polybot/market_data/chainlink_polygon.py`**

A stateless async reader for the Polygon Chainlink BTC/USD aggregator.

```python
class ChainlinkPolygonReader:
    """Read BTC/USD from Chainlink aggregator on Polygon via eth_call."""

    def __init__(self, rpc_url: str, contract: str, logger=None): ...

    async def latest_price(self) -> tuple[float, int, float]:
        """Returns (price_usd, round_id, updated_at)."""

    async def price_at_round(self, round_id: int) -> tuple[float, float]:
        """Returns (price_usd, updated_at) for a specific round."""

    async def get_rounds_since(self, since_ts: float, latest_round_id: int) -> list[tuple[float, float]]:
        """Walk backwards from latest_round_id, return [(price, timestamp), ...] until timestamp < since_ts."""

    async def get_price_at(self, timestamp: float) -> float | None:
        """Find the closest round to a given timestamp. For historical lookups."""
```

Key details:
- Pure `httpx` POST to Polygon RPC — no web3 dependency
- Parses the 5-tuple ABI response (same logic as existing `_fetch_chainlink_price`)
- `get_rounds_since()` walks backwards via `getRoundData(roundId - 1, roundId - 2, ...)` — used for candle backfill
- Batch RPC calls where possible (`eth_call` doesn't support batching, but we can send multiple JSON-RPC requests in one POST)

### Phase 2: Integrate into BtcPriceFeed

**Modify: `src/polybot/market_data/btc_price.py`**

- Add `ChainlinkPolygonReader` as a constructor dependency
- `get_price()`: Chainlink Polygon primary → Binance fallback → CoinGecko fallback
- `get_price_at()`: Use `ChainlinkPolygonReader.get_price_at()` primary → Binance klines fallback
- Remove `_fetch_chainlink_price()` (Ethereum mainnet RPC — replaced by Polygon reader)
- Remove Chainlink WS cross-reference logic (no longer needed)
- `chainlink_price` and `price_divergence` fields on `BtcPrice`: repurpose or remove (primary IS Chainlink now)

New `get_price()` fallback chain:
```python
async def get_price(self) -> BtcPrice | None:
    # 1. Chainlink Polygon (exact resolution source)
    price_usd = await self._chainlink_polygon.latest_price()
    source = "chainlink_polygon"

    if price_usd is None:
        # 2. Binance (fast, reliable, close approximation)
        price_usd = await self._fetch_binance_price()
        source = "binance"

    if price_usd is None:
        # 3. CoinGecko (last resort)
        price_usd = await self._fetch_coingecko_price()
        source = "coingecko"
```

### Phase 3: Candle history from on-chain rounds

**Modify: `BtcPriceFeed.load_candle_history()`**

Replace Binance 5-min klines with Chainlink round data:

1. Call `latest_price()` to get current `round_id`
2. Call `get_rounds_since(now - 200 * 300)` to get ~200 candles worth of rounds
3. Bucket rounds into 5-minute intervals, compute OHLC from the prices within each bucket
4. Fallback: if Polygon RPC fails, fall back to Binance klines (existing logic)

With 27s heartbeat: ~11 rounds per 5-min candle, ~2200 rounds for 200 candles.
Backfill strategy: batch requests in groups of 50 round IDs to avoid RPC rate limits.

### Phase 4: Remove ChainlinkWSFeed

- Delete `src/polybot/market_data/chainlink_ws.py`
- Remove from `ContextFactory` (`chainlink_ws = ChainlinkWSFeed(...)`)
- Remove from `AgentContext` (the `chainlink_ws` field)
- Remove from `MarketDataProvider` constructor
- Remove `start()`/`stop()` calls in `core.py`
- Remove WS-related constants from `constants.py`
- Clean up `BtcPrice` model: remove `chainlink_price`, `price_divergence` (or repurpose for Binance divergence monitoring)

### Phase 5: Config updates

**`src/polybot/config/constants.py`:**

```python
# Replace Ethereum RPC with Polygon
DEFAULT_POLYGON_RPC_URL: str = "https://polygon-rpc.com"
CHAINLINK_POLYGON_BTCUSD_ADDRESS: str = "0xc907E116054Ad103354f2D350FD2514433D57F6f"

# Keep for reference / removal
# DEFAULT_ETHEREUM_RPC_URL — remove
# CHAINLINK_BTCUSD_ADDRESS — remove (Ethereum contract)
# DEFAULT_POLYMARKET_RTDS_URL — remove
```

**`src/polybot/config/api.py`:**

- Add `polygon_rpc_url` field
- Add `chainlink_polygon_btcusd_address` field
- Deprecate `ethereum_rpc_url`, `chainlink_btcusd_address`, `polymarket_rtds_url`

---

## Polling Strategy

The bot's market monitor already runs every 1 second. The Chainlink read fits into this loop:

| Interval | Action |
|---|---|
| Every ~5s | `latestRoundData()` → update live BTC price (single `eth_call`, ~100ms) |
| On startup | `get_rounds_since()` → backfill 200 candles (~2200 rounds, batched) |
| Every 5 min | Append completed candle from accumulated rounds |

**Rate limits:** Public Polygon RPCs (Alchemy free tier, publicnode) allow 100+ requests/sec.
Polling every 5s = 0.2 req/s — well within limits.

**Staleness handling:** If Polygon RPC fails 3 consecutive times, fall back to Binance for that
cycle. Log a warning. Resume Chainlink on next successful call.

---

## Files Touched

| File | Action |
|---|---|
| `src/polybot/market_data/chainlink_polygon.py` | **New** — Polygon on-chain reader |
| `src/polybot/market_data/btc_price.py` | Modify — new primary source, remove Ethereum RPC |
| `src/polybot/market_data/chainlink_ws.py` | **Delete** |
| `src/polybot/market_data/constants.py` | Add Polygon constants, remove WS constants |
| `src/polybot/market_data/provider.py` | Remove `chainlink_ws` dependency |
| `src/polybot/config/constants.py` | Add Polygon RPC URL + contract address |
| `src/polybot/config/api.py` | Add Polygon config fields |
| `src/polybot/agent/factory.py` | Remove ChainlinkWSFeed, wire ChainlinkPolygonReader |
| `src/polybot/agent/context.py` | Remove `chainlink_ws` field |
| `src/polybot/agent/core.py` | Remove `chainlink_ws.start()`/`stop()` |
| `src/polybot/models/core.py` | Update `BtcPrice` fields, add `"chainlink_polygon"` source |
| Tests | New tests for ChainlinkPolygonReader, update existing BTC price tests |

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Polygon RPC downtime | Binance fallback (existing, tested) |
| RPC rate limiting on free tier | Poll every 5s (0.2 req/s), use multiple RPC providers |
| Round data gaps (missed updates) | Heartbeat guarantees max 27s gap — acceptable for 5-min candles |
| Candle backfill is slow (~2200 getRoundData calls) | Batch into multicall or parallelize; only runs once at startup |
| Contract upgrade changes ABI | Chainlink uses proxy pattern — `latestRoundData` ABI is stable across upgrades |

---

## Verification

```bash
# Quick smoke test: read current BTC price from Polygon Chainlink
curl -X POST https://polygon-rpc.com -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0",
  "method": "eth_call",
  "params": [{"to": "0xc907E116054Ad103354f2D350FD2514433D57F6f", "data": "0xfeaf968c"}, "latest"],
  "id": 1
}'
# Parse: answer is bytes 32-64 of result, divide by 10^8
```

After implementation:
```bash
uv run ruff check src/
uv run pytest tests/ -v
```
