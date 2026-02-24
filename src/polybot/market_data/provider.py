"""Unified market data facade combining REST + BTC + WebSocket sources."""

from __future__ import annotations

import logging
import time
from collections import deque

from polybot.config import AppConfig
from polybot.models import CandleMarket, MarketSnapshot

from .btc_price import BtcPriceFeed
from .client import PolymarketRestClient

logger = logging.getLogger(__name__)

PRICE_HISTORY_SIZE = 60  # keep last 60 midpoints


class MarketDataProvider:
    """Combines all market data sources into a single MarketSnapshot."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._rest = PolymarketRestClient(config.market, config.api)
        cache_ttl = config.monitor.btc_price_cache_ttl if hasattr(config, 'monitor') else 30
        self._btc = BtcPriceFeed(config.api, cache_ttl=cache_ttl)
        self._price_history: deque[float] = deque(maxlen=PRICE_HISTORY_SIZE)
        self._btc_price_history: deque[float] = deque(maxlen=PRICE_HISTORY_SIZE)
        self._ws_orderbook = None  # set by websocket module when active
        self._ws_last_price: float | None = None

        # Dual-token state (set via set_market)
        self._candle: CandleMarket | None = None

    @property
    def btc_feed(self) -> BtcPriceFeed:
        return self._btc

    def set_market(self, candle: CandleMarket) -> None:
        """Update internal token IDs and condition ID for a new candle market."""
        self._candle = candle
        self._config.market.condition_id = candle.condition_id
        self._config.market.token_id = candle.up_token_id
        # Clear price history on market change
        self._price_history.clear()
        logger.info(
            "Market set: %s (up=%s, down=%s)",
            candle.slug, candle.up_token_id[:8], candle.down_token_id[:8],
        )

    async def get_snapshot(self) -> MarketSnapshot:
        """Fetch a complete market snapshot from all sources."""
        # Fetch Up token orderbook
        if self._ws_orderbook is not None:
            up_orderbook = self._ws_orderbook
        else:
            up_token = self._candle.up_token_id if self._candle else None
            up_orderbook = await self._rest.get_orderbook(token_id=up_token)

        # Fetch Down token orderbook (only if we have a candle market)
        if self._candle:
            down_orderbook = await self._rest.get_orderbook(
                token_id=self._candle.down_token_id
            )
        else:
            from polybot.models import OrderbookSnapshot
            down_orderbook = OrderbookSnapshot()

        if self._ws_last_price is not None:
            last_price = self._ws_last_price
        else:
            up_token = self._candle.up_token_id if self._candle else None
            last_price = await self._rest.get_last_trade_price(token_id=up_token)

        btc_price = await self._btc.get_price()

        # Append latest 5-min BTC candle
        await self._btc.append_latest_candle()

        # Track midpoint history (Up token)
        if up_orderbook.midpoint is not None:
            self._price_history.append(up_orderbook.midpoint)

        # Track BTC price history (persists across market rotations)
        if btc_price is not None:
            self._btc_price_history.append(btc_price.price_usd)

        time_remaining = self._candle.time_remaining() if self._candle else 0.0

        return MarketSnapshot(
            condition_id=self._config.market.condition_id,
            token_id=self._candle.up_token_id if self._candle else self._config.market.token_id,
            orderbook=up_orderbook,
            down_orderbook=down_orderbook,
            up_token_id=self._candle.up_token_id if self._candle else "",
            down_token_id=self._candle.down_token_id if self._candle else "",
            time_remaining=time_remaining,
            last_trade_price=last_price,
            timestamp=time.time(),
            btc_price=btc_price,
            price_history=list(self._price_history),
            btc_price_history=list(self._btc_price_history),
            btc_candles=self._btc.candles,
        )

    def update_from_ws(
        self,
        orderbook=None,
        last_price: float | None = None,
    ) -> None:
        """Called by WebSocket handler to push real-time updates."""
        if orderbook is not None:
            self._ws_orderbook = orderbook
        if last_price is not None:
            self._ws_last_price = last_price

    async def close(self) -> None:
        await self._btc.close()
