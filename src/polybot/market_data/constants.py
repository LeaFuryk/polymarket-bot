"""Constants for the market_data package."""

from __future__ import annotations

# --- BTC price feed (btc_price.py) ---

# Seconds before a cached BTC price is considered stale
BTC_PRICE_CACHE_TTL: float = 30.0

# Chainlink BTC/USD Price Feed on Ethereum mainnet
# latestRoundData() function selector
CHAINLINK_LATEST_ROUND_SELECTOR: str = "0xfeaf968c"

# Chainlink BTC/USD uses 8 decimal places
CHAINLINK_DECIMALS: int = 8

# Full candle history refresh interval (seconds)
BTC_CANDLE_REFRESH_INTERVAL: int = 600

# Maximum candles to keep per fetch
BTC_CANDLE_WINDOW_SIZE: int = 200

# CoinGecko 24h change refresh interval (seconds)
COINGECKO_REFRESH_INTERVAL: int = 300

# --- Market data provider (provider.py) ---

# Number of recent midpoints to keep in price history
PRICE_HISTORY_SIZE: int = 60

# --- Market discovery (discovery.py) ---

# Gamma API base URL
GAMMA_API_BASE: str = "https://gamma-api.polymarket.com"

# Candle interval in seconds (5 minutes)
CANDLE_INTERVAL_SECONDS: int = 300
