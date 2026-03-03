"""Live trading credentials, wallet settings, and safety limits."""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    DEFAULT_LIMIT_ORDER_TTL_SECONDS,
    DEFAULT_MAX_ORDER_SIZE_USD,
    DEFAULT_MAX_PRICE_DRIFT_PCT,
    DEFAULT_MAX_SESSION_LOSS_USD,
    DEFAULT_MIN_WALLET_BALANCE_USD,
    DEFAULT_TRADING_MODE,
    POLYGON_MAINNET_CHAIN_ID,
)


class TradingConfig(BaseModel):
    """Live trading credentials, wallet settings, and safety limits."""

    mode: str = DEFAULT_TRADING_MODE
    private_key: str = ""
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    chain_id: int = POLYGON_MAINNET_CHAIN_ID
    max_order_size_usd: float = DEFAULT_MAX_ORDER_SIZE_USD
    max_session_loss_usd: float = DEFAULT_MAX_SESSION_LOSS_USD
    min_wallet_balance_usd: float = DEFAULT_MIN_WALLET_BALANCE_USD
    max_price_drift_pct: float = DEFAULT_MAX_PRICE_DRIFT_PCT
    proxy_wallet_address: str = ""
    limit_order_ttl_seconds: int = DEFAULT_LIMIT_ORDER_TTL_SECONDS
    dry_run: bool = False
