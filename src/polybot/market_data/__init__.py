"""Unified market data facade — REST, BTC price, market discovery, WebSocket feeds."""

from polybot.market_data.btc_price import BtcPriceFeed
from polybot.market_data.btc_repository import BtcRepository
from polybot.market_data.client import PolymarketRestClient
from polybot.market_data.discovery import MarketDiscovery
from polybot.market_data.polymarket_repository import PolymarketRepository
from polybot.market_data.protocol import MarketDataRepository
from polybot.market_data.provider import MarketDataProvider

__all__ = [
    "BtcPriceFeed",
    "BtcRepository",
    "MarketDataProvider",
    "MarketDataRepository",
    "MarketDiscovery",
    "PolymarketRepository",
    "PolymarketRestClient",
]
