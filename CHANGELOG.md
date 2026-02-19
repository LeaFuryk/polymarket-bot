# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Pending bet resolution on startup** — When the bot restarts after a crash or stop mid-candle, it now automatically detects unresolved trades (fills with no matching resolution record), fetches historical BTC prices from Binance, verifies the winner via Polymarket token prices, computes PnL from logged fills, and writes the missing resolution records. This ensures all-time stats and dashboard history remain accurate across restarts.
- `MarketDiscovery.fetch_market_by_slug()` — Public method to fetch a specific candle market by its exact slug, used by the pending bet resolver to look up past markets on the Gamma API.
- `_compute_pnl_from_trades()` helper — Reconstructs position PnL from logged BUY/SELL fills for settlement (winning token = $1, losing = $0).
