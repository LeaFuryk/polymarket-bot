# market_data — Unified market data facade

Combines REST APIs (Polymarket CLOB), BTC price feeds (Binance + Chainlink),
and WebSocket streams (Chainlink RTDS) into a single snapshot for the trading agent.

## Architecture

```
provider.py        MarketDataProvider — main facade, orchestrates all sources
client.py          PolymarketRestClient — REST wrapper around py-clob-client
btc_price.py       BtcPriceFeed — Binance (primary) + CoinGecko (fallback) + Chainlink (cross-ref)
chainlink_ws.py    ChainlinkWSFeed — real-time RTDS WebSocket for Chainlink BTC/USD ticks
discovery.py       MarketDiscovery — Gamma API market lookup for 5-min candle markets
protocol.py        MarketDataRepository — Protocol defining external data access contract
constants.py       All configuration constants (cache TTLs, API URLs, intervals)
```

## Data flow

```
Binance API ──────┐
CoinGecko API ────┤
Chainlink RPC ────┼── BtcPriceFeed ──┐
Chainlink RTDS WS ── ChainlinkWSFeed ┤
                                      ├── MarketDataProvider ──► MarketSnapshot
Polymarket CLOB ──── RestClient ──────┤
Gamma API ────────── MarketDiscovery ─┘
```

## Key consumers

| Consumer | Uses | For |
|---|---|---|
| `MarketMonitor` | `MarketDataProvider.get_snapshot()` | 1s polling loop |
| `RotationManager` | `MarketDiscovery.get_current/next_market()` | 5-min candle rotation |
| `ResolutionTracker` | `BtcPriceFeed` (via `btc_feed` property) | Resolution price lookup |
| `AgentContext` | All three | Dependency injection container |

## Data sources

| Source | Update frequency | Failover |
|---|---|---|
| Binance spot API | Real-time (~1s) | CoinGecko fallback |
| Chainlink RPC | On-chain (~1h or 0.5% deviation) | Cross-reference only |
| Chainlink RTDS WS | Real-time ticks (~1s) | Auto-reconnect with 5s delay |
| Polymarket CLOB | Per-request | Empty orderbook on failure |
| Gamma API | Per-request | None (logs warning) |
