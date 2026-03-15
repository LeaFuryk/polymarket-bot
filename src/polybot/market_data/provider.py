"""Unified market data facade — composes PolymarketRepository + BtcRepository."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING

from polybot.config import AppConfig
from polybot.models import BetData, BtcData, CandleMarket, MarketSnapshot

from .btc_price import BtcPriceFeed
from .btc_repository import BtcRepository
from .client import PolymarketRestClient
from .constants import BTC_PRICE_CACHE_TTL, PRICE_HISTORY_SIZE
from .discovery import MarketDiscovery
from .polymarket_repository import PolymarketRepository

if TYPE_CHECKING:
    from polybot.ws.broadcaster import Broadcaster


class MarketDataProvider:
    """Combines all market data sources into a single MarketSnapshot.

    Composes PolymarketRepository (orderbooks) and BtcRepository (price + candles),
    fetching them in parallel via asyncio.gather().

    Detects market rotation (condition_id change) and fires the on_rotation
    callback so the caller (RotationManager) can handle transition side effects.
    """

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        discovery: MarketDiscovery | None = None,
        on_rotation: Callable[[], Coroutine] | None = None,
        broadcaster: Broadcaster | None = None,
    ) -> None:
        self._log = logger
        self._config = config
        rest = PolymarketRestClient(config.market, config.api, logger=logger)
        cache_ttl = config.monitor.btc_price_cache_ttl if hasattr(config, "monitor") else BTC_PRICE_CACHE_TTL
        btc_feed = BtcPriceFeed(config.api, logger, cache_ttl=cache_ttl)

        disc = discovery or MarketDiscovery(config, logger=logger)
        self._polymarket = PolymarketRepository(rest, disc, logger=logger)
        self._btc_repo = BtcRepository(btc_feed, logger=logger)

        self._price_history: deque[float] = deque(maxlen=PRICE_HISTORY_SIZE)
        self._btc_price_history: deque[float] = deque(maxlen=PRICE_HISTORY_SIZE)

        self._prev_condition_id: str | None = None
        self._on_rotation = on_rotation
        self._broadcaster = broadcaster

    def set_on_rotation(self, callback: Callable[[], Coroutine]) -> None:
        """Register the callback fired when a market rotation is detected."""
        self._on_rotation = callback

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

    # Outage state — delegated from the polymarket repo
    @property
    def discovery_failures(self) -> int:
        return self._polymarket.discovery_failures

    @property
    def outage_start(self) -> float | None:
        return self._polymarket.outage_start

    @property
    def outage_recovered(self) -> float | None:
        return self._polymarket.outage_recovered

    @property
    def last_outage_duration(self) -> float:
        return self._polymarket.last_outage_duration

    def set_market(self, candle: CandleMarket) -> None:
        """Sync provider state for a new candle market."""
        self._polymarket.set_market(candle)
        self._price_history.clear()

    async def close(self) -> None:
        await self._btc_repo.close()

    # --- Core fetch ---

    async def get_snapshot(self) -> MarketSnapshot | None:
        """Fetch Polymarket + BTC data in parallel, merge into MarketSnapshot.

        Returns None when market discovery fails (no active market found).
        On market rotation (condition_id change), fires the on_rotation callback
        before building the snapshot.
        """
        bet_data, btc_data = await asyncio.gather(
            self._polymarket.fetch(),
            self._btc_repo.fetch(),
        )
        if bet_data is None:
            self._broadcast_outage()
            return None

        # Detect rotation or first market
        new_id = bet_data.market.condition_id
        if self._prev_condition_id is None or new_id != self._prev_condition_id:
            if self._on_rotation:
                await self._on_rotation()
            self._prev_condition_id = new_id

        snapshot = self._build_snapshot(bet_data, btc_data)
        self._broadcast_snapshot(snapshot)
        return snapshot

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

    def _broadcast_snapshot(self, snapshot: MarketSnapshot) -> None:
        """Broadcast fresh market snapshot to WS clients."""
        if self._broadcaster is None or not self._broadcaster.has_clients:
            return

        from polybot.ws.protocol import MSG_MARKET, make_message

        data: dict = {
            "timestamp": snapshot.timestamp,
            "time_remaining": snapshot.time_remaining,
            "slug": snapshot.slug,
            "up_mid": snapshot.orderbook.midpoint,
            "down_mid": snapshot.down_orderbook.midpoint,
        }

        if snapshot.btc_price:
            data["btc_price"] = snapshot.btc_price.price_usd
            data["chainlink_price"] = snapshot.btc_price.chainlink_price
            data["price_source"] = snapshot.btc_price.price_source

        msg = make_message(MSG_MARKET, data)
        asyncio.create_task(self._broadcaster.broadcast(msg))

    def _broadcast_outage(self) -> None:
        """Broadcast outage status to WS clients when discovery fails."""
        if self._broadcaster is None or not self._broadcaster.has_clients:
            return
        if self._polymarket.outage_start is None:
            return

        from polybot.ws.protocol import MSG_MARKET, make_message

        elapsed = time.time() - self._polymarket.outage_start
        msg = make_message(
            MSG_MARKET,
            {
                "outage": True,
                "failures": self._polymarket.discovery_failures,
                "outage_duration": round(elapsed, 1),
            },
        )
        asyncio.create_task(self._broadcaster.broadcast(msg))
