"""Polymarket repository — orderbook fetching + market discovery + WS cache."""

from __future__ import annotations

import logging

from polybot.models import BetData, CandleMarket, OrderbookSnapshot

from .client import PolymarketRestClient
from .discovery import MarketDiscovery


class PolymarketRepository:
    """Wraps PolymarketRestClient + MarketDiscovery + WS cache.

    Owns the current CandleMarket and handles lazy discovery.
    """

    def __init__(
        self,
        rest: PolymarketRestClient,
        discovery: MarketDiscovery,
        logger: logging.Logger | None = None,
    ) -> None:
        self._rest = rest
        self._discovery = discovery
        self._log = logger or logging.getLogger(__name__)
        self._market: CandleMarket | None = None
        self._ws_orderbook: OrderbookSnapshot | None = None
        self._ws_last_price: float | None = None

    @property
    def market(self) -> CandleMarket | None:
        return self._market

    @property
    def discovery(self) -> MarketDiscovery:
        return self._discovery

    @property
    def rest_client(self) -> PolymarketRestClient:
        return self._rest

    async def fetch(self) -> BetData | None:
        """Fetch orderbooks for current market. Discovers market if needed.

        Returns None if no market is available (discovery failed or not set).
        """
        if self._market is None or self._market.time_remaining() <= 0:
            self._market = await self._discover()
            if self._market is None:
                return None

        # Fetch UP orderbook (WS cache or REST)
        if self._ws_orderbook is not None:
            up_orderbook = self._ws_orderbook
        else:
            up_orderbook = await self._rest.get_orderbook(token_id=self._market.up_token_id)

        # Fetch DOWN orderbook (always REST)
        down_orderbook = await self._rest.get_orderbook(token_id=self._market.down_token_id)

        # Last trade price (WS cache or REST)
        if self._ws_last_price is not None:
            last_price = self._ws_last_price
        else:
            last_price = await self._rest.get_last_trade_price(token_id=self._market.up_token_id)

        return BetData(
            market=self._market,
            orderbook=up_orderbook,
            down_orderbook=down_orderbook,
            last_trade_price=last_price,
        )

    async def _discover(self) -> CandleMarket | None:
        """Try current boundary, fallback to next."""
        market = await self._discovery.get_current_market()
        if market is None:
            market = await self._discovery.get_next_market()
        return market

    def set_market(self, market: CandleMarket) -> None:
        """Force-set market (called by RotationManager after transition)."""
        self._market = market

    def update_from_ws(
        self,
        orderbook: OrderbookSnapshot | None = None,
        last_price: float | None = None,
    ) -> None:
        """Push real-time WebSocket updates."""
        if orderbook is not None:
            self._ws_orderbook = orderbook
        if last_price is not None:
            self._ws_last_price = last_price
