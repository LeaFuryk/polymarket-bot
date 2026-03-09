"""Default values for all configuration fields.

Centralizes magic numbers, URLs, and thresholds so they are easy to
find, audit, and override.  Each constant is named
``DEFAULT_<FIELD>`` and grouped by the config section it belongs to.
"""

from __future__ import annotations

# -- Market -------------------------------------------------------------------
DEFAULT_CONDITION_ID: str = "0x"
DEFAULT_SERIES_SLUG: str = "btc-updown-5m"

# -- API endpoints ------------------------------------------------------------
DEFAULT_POLYMARKET_HOST: str = "https://clob.polymarket.com"
DEFAULT_COINGECKO_URL: str = "https://api.coingecko.com/api/v3"
DEFAULT_ETHEREUM_RPC_URL: str = "https://ethereum.publicnode.com"
CHAINLINK_BTCUSD_ADDRESS: str = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"
DEFAULT_POLYMARKET_RTDS_URL: str = "wss://ws-live-data.polymarket.com"

# -- Agent behaviour ----------------------------------------------------------
DEFAULT_INITIAL_CASH: float = 10_000.0
DEFAULT_RESOLUTION_BUFFER_SECONDS: int = 10
DEFAULT_MIN_CONFIDENCE: float = 0.55

# -- AI models & costs --------------------------------------------------------
DEFAULT_AI_MODEL: str = "claude-sonnet-4-5-20250929"
DEFAULT_SCREEN_MODEL: str = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS: int = 1024
DEFAULT_INPUT_COST_PER_MTOK: float = 3.0
DEFAULT_OUTPUT_COST_PER_MTOK: float = 8.0
DEFAULT_SCREEN_INPUT_COST_PER_MTOK: float = 0.80
DEFAULT_SCREEN_OUTPUT_COST_PER_MTOK: float = 4.0

# -- Simulator ----------------------------------------------------------------
DEFAULT_BASE_SLIPPAGE_BPS: float = 5.0
DEFAULT_PROPORTIONAL_FACTOR: float = 0.5
DEFAULT_FEE_BPS: float = 20.0
DEFAULT_LIMIT_ORDER_TTL: int = 300  # seconds

# -- Risk management ----------------------------------------------------------
DEFAULT_MAX_POSITION_PCT: float = 0.25
DEFAULT_MAX_SPREAD_PCT: float = 0.05
DEFAULT_MIN_LIQUIDITY: float = 100.0
DEFAULT_DAILY_LOSS_LIMIT_PCT: float = 0.10
DEFAULT_MAX_CONCENTRATION_PCT: float = 0.50

# -- Monitoring ---------------------------------------------------------------
DEFAULT_MARKET_MONITOR_INTERVAL: float = 1.0  # seconds
DEFAULT_POSITION_MONITOR_INTERVAL: float = 1.0  # seconds
DEFAULT_AI_COOLDOWN_SECONDS: float = 60.0
DEFAULT_RR_TRIGGER_THRESHOLD: float = 1.0
DEFAULT_STOP_LOSS_PCT: float = -0.35  # -35 %
DEFAULT_TAKE_PROFIT_PCT: float = 0.50  # +50 %
DEFAULT_BTC_PRICE_CACHE_TTL: float = 2.0  # seconds
DEFAULT_ADAPTIVE_ENTRY_WINDOW: int = 10  # rolling candle window
DEFAULT_SL_FLOOR: float = -0.75  # never wider than -75 %
DEFAULT_SL_CEILING: float = -0.15  # never tighter than -15 %
DEFAULT_TP_FLOOR: float = 0.20  # never below +20 %
DEFAULT_TP_CEILING: float = 1.20  # never above +120 %

# -- Logging & storage --------------------------------------------------------
DEFAULT_LOG_DIR: str = "logs"
DEFAULT_KNOWLEDGE_DIR: str = "data/knowledge"
DEFAULT_SQLITE_DB_PATH: str = "logs/polybot.db"
DEFAULT_MARKET_HISTORY_DB_PATH: str = "data/market_history.db"
DEFAULT_WS_PORT: int = 8765

# -- Trading ------------------------------------------------------------------
DEFAULT_TRADING_MODE: str = "paper"
POLYGON_MAINNET_CHAIN_ID: int = 137
DEFAULT_MAX_ORDER_SIZE_USD: float = 50.0
DEFAULT_MAX_SESSION_LOSS_USD: float = 40.0
DEFAULT_MIN_WALLET_BALANCE_USD: float = 5.0
DEFAULT_MAX_PRICE_DRIFT_PCT: float = 0.05  # 5 % — max drift before skipping BUY
DEFAULT_LIMIT_ORDER_TTL_SECONDS: int = 3
