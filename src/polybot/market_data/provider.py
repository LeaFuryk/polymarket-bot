"""Unified market data facade — composes PolymarketRepository + BtcRepository."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from polybot.config import AppConfig
from polybot.models import BetData, BtcData, CandleMarket, MarketSnapshot

from .btc_price import BtcPriceFeed
from .btc_repository import BtcRepository
from .client import PolymarketRestClient
from .constants import BTC_PRICE_CACHE_TTL, PRICE_HISTORY_SIZE
from .discovery import MarketDiscovery
from .polymarket_repository import PolymarketRepository


class MarketDataProvider:
    """Combines all market data sources into a single MarketSnapshot.

    Composes PolymarketRepository (orderbooks) and BtcRepository (price + candles),
    fetching them in parallel via asyncio.gather().
    """

    def __init__(
        self,
        config: AppConfig,
        discovery: MarketDiscovery | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._config = config
        rest = PolymarketRestClient(config.market, config.api)
        cache_ttl = config.monitor.btc_price_cache_ttl if hasattr(config, "monitor") else BTC_PRICE_CACHE_TTL
        btc_feed = BtcPriceFeed(config.api, cache_ttl=cache_ttl)

        disc = discovery or MarketDiscovery(config)
        self._polymarket = PolymarketRepository(rest, disc)
        self._btc_repo = BtcRepository(btc_feed)

        self._price_history: deque[float] = deque(maxlen=PRICE_HISTORY_SIZE)
        self._btc_price_history: deque[float] = deque(maxlen=PRICE_HISTORY_SIZE)

    # --- Public properties for sub-component access ---

    @property
    def polymarket(self) -> PolymarketRepository:
        return self._polymarket

    @property
    def btc_repo(self) -> BtcRepository:
        return self._btc_repo

    @property
    def btc_feed(self) -> BtcPriceFeed:
        return self._btc_repo._feed

    @property
    def rest_client(self) -> PolymarketRestClient:
        return self._polymarket.rest_client

    # --- Backward-compat delegations ---

    def set_market(self, candle: CandleMarket) -> None:
        """Update internal market and config for a new candle market."""
        self._polymarket.set_market(candle)
        self._config.market.condition_id = candle.condition_id
        self._config.market.token_id = candle.up_token_id
        self._price_history.clear()
        self._log.info(
            "Market set: %s (up=%s, down=%s)",
            candle.slug,
            candle.up_token_id[:8],
            candle.down_token_id[:8],
        )

    def update_from_ws(
        self,
        orderbook=None,
        last_price: float | None = None,
    ) -> None:
        """Called by WebSocket handler to push real-time updates."""
        self._polymarket.update_from_ws(orderbook=orderbook, last_price=last_price)

    async def close(self) -> None:
        await self._btc_repo.close()

    # --- Core fetch ---

    async def get_snapshot(self) -> MarketSnapshot:
        """Fetch Polymarket + BTC data in parallel, merge into MarketSnapshot."""
        bet_data, btc_data = await asyncio.gather(
            self._polymarket.fetch(),
            self._btc_repo.fetch(),
        )
        return self.build_snapshot(bet_data, btc_data)

    def build_snapshot(self, bet_data: BetData | None, btc_data: BtcData) -> MarketSnapshot:
        """Merge BetData + BtcData into a MarketSnapshot, tracking price history."""
        from polybot.models import OrderbookSnapshot

        if bet_data is not None:
            market = bet_data.market
            up_orderbook = bet_data.orderbook
            down_orderbook = bet_data.down_orderbook
            last_price = bet_data.last_trade_price
            condition_id = market.condition_id
            token_id = market.up_token_id
            up_token_id = market.up_token_id
            down_token_id = market.down_token_id
            time_remaining = market.time_remaining()
            slug = market.slug
        else:
            up_orderbook = OrderbookSnapshot()
            down_orderbook = OrderbookSnapshot()
            last_price = None
            condition_id = self._config.market.condition_id
            token_id = self._config.market.token_id
            up_token_id = ""
            down_token_id = ""
            time_remaining = 0.0
            slug = ""

        # Track midpoint history (Up token)
        if up_orderbook.midpoint is not None:
            self._price_history.append(up_orderbook.midpoint)

        # Track BTC price history (persists across market rotations)
        if btc_data.price is not None:
            self._btc_price_history.append(btc_data.price.price_usd)

        return MarketSnapshot(
            condition_id=condition_id,
            token_id=token_id,
            orderbook=up_orderbook,
            down_orderbook=down_orderbook,
            up_token_id=up_token_id,
            down_token_id=down_token_id,
            time_remaining=time_remaining,
            slug=slug,
            last_trade_price=last_price,
            timestamp=time.time(),
            btc_price=btc_data.price,
            price_history=list(self._price_history),
            btc_price_history=list(self._btc_price_history),
            btc_candles=btc_data.candles,
        )
