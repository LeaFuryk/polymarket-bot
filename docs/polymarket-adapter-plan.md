# Polymarket Adapter — Implementation Plan

> **Goal:** Fetch Polymarket market data (orderbook, prices, market discovery)
> and expose it through clean hexagonal ports for the trading bot.

---

## What we need from Polymarket

Looking at the LLM JSON model, Polymarket provides:

```json
"microstructure": {
    "polymarket_yes_price":   0.57,    // YES token midpoint
    "polymarket_yes_delta":   0.03,    // change since candle open
    "polymarket_vol_delta":   312.0    // change in market volume
},
"bet_state": {
    "bet_open_price":     43121.00,    // BTC price when bet was placed
    "unrealised_ret":     0.00093,     // current unrealized return
    "hold_count":         1,           // number of positions held
    "time_remaining_sec": 210          // seconds until market resolves
}
```

Plus the bot needs market discovery (which market to bet on) and execution (placing orders).

---

## Data sources

Polymarket has two APIs:

| API | Base URL | Purpose | Auth |
|---|---|---|---|
| **CLOB** | `https://clob.polymarket.com` | Orderbooks, prices, orders, balances | API key (for writes) |
| **Gamma** | `https://gamma-api.polymarket.com` | Market discovery, metadata | None |

### What we fetch

| Data | API | Endpoint | Frequency |
|---|---|---|---|
| YES orderbook (bids/asks) | CLOB | `get_order_book(up_token_id)` | Every tick (~1-5s) |
| DOWN orderbook (bids/asks) | CLOB | `get_order_book(down_token_id)` | Every tick |
| Last trade price | CLOB | `get_last_trade_price(token_id)` | Every tick |
| Market metadata | Gamma | `GET /events?slug={slug}` | Every 5min (rotation) |
| USDC balance | CLOB | `get_balance_allowance(COLLATERAL)` | Per trade |
| Token balance | CLOB | `get_balance_allowance(CONDITIONAL, token_id)` | Per sell |

### Legacy note on volume

The legacy bot never actually fetched Polymarket volume — `volume_24h` was always 0.0.
For `polymarket_vol_delta` in the LLM model, we need to track orderbook depth changes
over time (bid_depth + ask_depth delta), or fetch volume from the Gamma API if available.

---

## Architecture

Two separate concerns, two separate ports:

```
polybot/
├── domain/
│   └── models.py              # + Market, OrderBook, Position
│
├── ports/
│   ├── market_feed.py         # MarketFeed: discovery + orderbook reads
│   └── order_gateway.py       # OrderGateway: execution (future PR)
│
├── adapters/
│   └── polymarket.py          # PolymarketAdapter (implements MarketFeed)
│
└── services/
    └── (future: trading service consumes both ports)
```

**Why two ports?**
- **MarketFeed** is read-only, high frequency, no auth needed for reads
- **OrderGateway** is write, low frequency, requires API keys + wallet
- Separating them means we can test and develop market reading without execution

---

## Domain models

```python
@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    size: float

@dataclass(frozen=True)
class OrderBook:
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    timestamp: float

    @property
    def best_bid(self) -> float | None
    @property
    def best_ask(self) -> float | None
    @property
    def midpoint(self) -> float | None
    @property
    def spread_pct(self) -> float | None
    @property
    def bid_depth(self) -> float       # sum(price * size)
    @property
    def ask_depth(self) -> float

@dataclass(frozen=True)
class Market:
    condition_id: str
    up_token_id: str
    down_token_id: str
    slug: str
    question: str
    end_time: float                    # resolution timestamp

    @property
    def time_remaining(self) -> float  # end_time - now

@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    up_book: OrderBook
    down_book: OrderBook
    last_trade_price: float | None
```

All frozen/immutable. No Polymarket SDK types leak into domain.

---

## Port: MarketFeed

```python
@runtime_checkable
class MarketFeed(Protocol):

    async def discover_market(self, series_slug: str) -> Market | None:
        """Find the current active market for a series."""
        ...

    async def get_orderbooks(self, market: Market) -> tuple[OrderBook, OrderBook]:
        """Fetch UP and DOWN orderbooks for a market."""
        ...

    async def get_last_trade_price(self, token_id: str) -> float | None:
        """Get the last trade price for a token."""
        ...

    async def get_snapshot(self, market: Market) -> MarketSnapshot:
        """Fetch complete market state (orderbooks + last trade)."""
        ...
```

### Why `discover_market` is on MarketFeed

Market discovery is read-only (Gamma API) and tightly coupled to market data reads.
The bot needs to know which market to read orderbooks for. Keeping them together
means one adapter handles the full "read Polymarket" surface.

---

## Port: OrderGateway (future PR)

```python
class OrderGateway(Protocol):

    async def place_order(self, token_id: str, side: str, price: float, size: float) -> str:
        """Place a GTC limit order. Returns order_id."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        ...

    async def get_order_status(self, order_id: str) -> dict:
        ...

    async def get_balance(self) -> float:
        """USDC balance."""
        ...
```

Not implementing this now — execution is a separate concern for after we have
the data pipeline working.

---

## Adapter: PolymarketAdapter

```python
class PolymarketAdapter:
    """MarketFeed implementation using Polymarket CLOB + Gamma APIs."""

    def __init__(
        self,
        clob_host: str = "https://clob.polymarket.com",
        gamma_host: str = "https://gamma-api.polymarket.com",
    ): ...

    async def discover_market(self, series_slug: str) -> Market | None:
        """Query Gamma API for the current candle market."""
        # 1. Calculate current 5-min boundary
        # 2. Build slug: {series_slug}-{boundary_timestamp}
        # 3. GET /events?slug={slug}
        # 4. Parse response → Market

    async def get_orderbooks(self, market: Market) -> tuple[OrderBook, OrderBook]:
        """Fetch UP + DOWN orderbooks in parallel."""
        # asyncio.gather(fetch_up, fetch_down)

    async def get_last_trade_price(self, token_id: str) -> float | None:
        """CLOB last trade price."""

    async def get_snapshot(self, market: Market) -> MarketSnapshot:
        """Fetch orderbooks + last trade → MarketSnapshot."""
```

### CLOB client approach

The legacy code uses `py-clob-client` (sync) wrapped in `asyncio.to_thread()`.
Two options:

**A) Keep py-clob-client** — It handles order signing, wallet auth, and the CLOB
REST protocol. Wrap sync calls in `asyncio.to_thread()` for async.
Pros: proven, handles signing complexity.
Cons: sync library, adds complexity for reads.

**B) Direct httpx for reads, py-clob-client for writes** — Orderbook and price
queries are simple GET requests, no auth needed. Use raw httpx for reads (faster,
truly async). Keep py-clob-client only for OrderGateway (needs signing).
Pros: clean async reads, minimal deps for data pipeline.
Cons: two HTTP clients.

**Recommended: Option B.** The MarketFeed adapter only does reads — no auth,
no signing. Direct httpx is simpler and truly async. py-clob-client stays in
OrderGateway (future PR) where signing is needed.

### CLOB REST endpoints (for direct httpx)

| Endpoint | Method |
|---|---|
| `GET /book?token_id={id}` | Orderbook |
| `GET /last-trade-price?token_id={id}` | Last trade |
| `GET /market/{condition_id}` | Market info |

---

## How this maps to the LLM JSON

| LLM field | Source | Computation |
|---|---|---|
| `microstructure.polymarket_yes_price` | `up_book.midpoint` | (best_bid + best_ask) / 2 |
| `microstructure.polymarket_yes_delta` | Midpoint now − midpoint at candle open | Service tracks candle-open snapshot |
| `microstructure.polymarket_vol_delta` | `(bid_depth + ask_depth)` delta | Service tracks depth at candle open |
| `microstructure.ob_imbalance` | `(bid_depth - ask_depth) / (bid_depth + ask_depth)` | From OrderBook |
| `microstructure.spread_bps` | Chainlink bid/ask (not Polymarket) | Already in BtcTick |
| `bet_state.time_remaining_sec` | `market.time_remaining` | Market.end_time − now |
| `bet_state.bet_open_price` | Entry price from portfolio | Domain state |
| `bet_state.unrealised_ret` | (current_price − entry_price) / entry_price | Domain computation |
| `bet_state.hold_count` | Number of open positions | Domain state |

---

## Market rotation

Every 5 minutes, a new Polymarket candle market opens. The bot must:

1. Detect that the current market is expiring (`time_remaining ≤ 0`)
2. Discover the next market (`discover_market(series_slug)`)
3. Switch to the new market's token IDs

This is **orchestration logic**, not adapter logic. The adapter just exposes
`discover_market()`. A future service (MarketMonitor or Orchestrator) calls it
at the right time.

---

## Implementation steps

### Step 1: Domain models
Add `OrderBookLevel`, `OrderBook`, `Market`, `MarketSnapshot` to `domain/models.py`.

### Step 2: MarketFeed port
`ports/market_feed.py` — protocol with 4 methods.

### Step 3: PolymarketAdapter
`adapters/polymarket.py` — httpx-based reads for orderbooks + Gamma API for discovery.

### Step 4: Tests
- Domain: OrderBook properties (midpoint, spread, depth, imbalance)
- Adapter: mock httpx responses for orderbook parsing, discovery parsing, error handling
- Port: protocol conformance

### Step 5: Smoke script
Update `__main__.py` to discover a market and print live orderbook data.

---

## Dependencies

- `httpx` — already in pyproject.toml (async HTTP for CLOB + Gamma reads)
- `py-clob-client` — already in pyproject.toml (only needed later for OrderGateway)

No new dependencies.

---

## What this PR delivers

- Polymarket market discovery (Gamma API)
- Orderbook + last trade price fetching (CLOB API)
- Clean domain models (OrderBook, Market, MarketSnapshot)
- All read-only — no execution, no wallet, no signing

## What comes after

- OrderGateway port + adapter (execution, needs wallet/signing)
- CandleAggregator service (combines Chainlink ticks + Binance volume into candles)
- MarketMonitor service (orchestrates rotation + tick loop)
- LLM prompt builder (assembles the JSON model from all data sources)
