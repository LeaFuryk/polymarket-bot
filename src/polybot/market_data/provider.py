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

    # --- Public properties ---

    @property
    def fetched_market(self) -> CandleMarket | None:
        """The CandleMarket used in the last successful fetch (or None)."""
        return self._polymarket.market

    @property
    def btc_feed(self) -> BtcPriceFeed:
        return self._btc_repo._feed

    @property
    def rest_client(self) -> PolymarketRestClient:
        return self._polymarket.rest_client

    # --- Delegations ---

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

    async def get_snapshot(self) -> MarketSnapshot | None:
        """Fetch Polymarket + BTC data in parallel, merge into MarketSnapshot.

        Returns None when market discovery fails (no active market found).
        """
        bet_data, btc_data = await asyncio.gather(
            self._polymarket.fetch(),
            self._btc_repo.fetch(),
        )
        if bet_data is None:
            return None
        return self._build_snapshot(bet_data, btc_data)

    def _build_snapshot(self, bet_data: BetData, btc_data: BtcData) -> MarketSnapshot:
        """Merge BetData + BtcData into a MarketSnapshot, tracking price history."""
        market = bet_data.market

        # Track midpoint history (Up token)
        if bet_data.orderbook.midpoint is not None:
            self._price_history.append(bet_data.orderbook.midpoint)

        # Track BTC price history (persists across market rotations)
        if btc_data.price is not None:
            self._btc_price_history.append(btc_data.price.price_usd)

        return MarketSnapshot(
            condition_id=market.condition_id,
            token_id=market.up_token_id,
            orderbook=bet_data.orderbook,
            down_orderbook=bet_data.down_orderbook,
            up_token_id=market.up_token_id,
            down_token_id=market.down_token_id,
            time_remaining=market.time_remaining(),
            slug=market.slug,
            last_trade_price=bet_data.last_trade_price,
            timestamp=time.time(),
            btc_price=btc_data.price,
            price_history=list(self._price_history),
            btc_price_history=list(self._btc_price_history),
            btc_candles=btc_data.candles,
        )
