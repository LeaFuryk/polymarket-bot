"""External service URLs for market data and trading APIs."""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    CHAINLINK_BTCUSD_ADDRESS,
    DEFAULT_COINGECKO_URL,
    DEFAULT_ETHEREUM_RPC_URL,
    DEFAULT_POLYMARKET_HOST,
    DEFAULT_POLYMARKET_RTDS_URL,
    DEFAULT_POLYMARKET_WS_URL,
)


class ApiConfig(BaseModel):
    """External service URLs for market data and trading APIs."""

    polymarket_host: str = DEFAULT_POLYMARKET_HOST
    coingecko_url: str = DEFAULT_COINGECKO_URL
    polymarket_ws_url: str = DEFAULT_POLYMARKET_WS_URL
    ethereum_rpc_url: str = DEFAULT_ETHEREUM_RPC_URL
    chainlink_btcusd_address: str = CHAINLINK_BTCUSD_ADDRESS
    polymarket_rtds_url: str = DEFAULT_POLYMARKET_RTDS_URL
