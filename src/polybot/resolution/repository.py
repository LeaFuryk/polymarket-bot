"""Concrete ResolutionRepository backed by MarketData services."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.market_data.btc_price import BtcPriceFeed
    from polybot.market_data.client import PolymarketRestClient


class MarketDataResolutionRepo:
    """Adapts BtcPriceFeed + PolymarketRestClient to the ResolutionRepository protocol."""

    def __init__(self, btc_feed: BtcPriceFeed, rest_client: PolymarketRestClient) -> None:
        self._btc = btc_feed
        self._rest = rest_client

    async def get_btc_price_at(self, timestamp: float) -> float | None:
        return await self._btc.get_price_at(timestamp)

    async def get_last_trade_price(self, token_id: str) -> float | None:
        return await self._rest.get_last_trade_price(token_id=token_id)
