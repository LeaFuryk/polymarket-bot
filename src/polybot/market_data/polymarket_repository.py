"""Polymarket repository — orderbook fetching + market discovery + WS cache."""

from __future__ import annotations

import asyncio
import logging
import time

from polybot.models import BetData, CandleMarket, OrderbookSnapshot

from .client import PolymarketRestClient
from .discovery import MarketDiscovery

# Outage is declared after this many consecutive discovery failures.
_OUTAGE_THRESHOLD: int = 3
# Log an ongoing-outage warning every N failures (~60 s at 5 s tick rate).
_OUTAGE_LOG_INTERVAL: int = 12
# How long to show the "recovered" banner before clearing it.
_RECOVERY_BANNER_TTL: float = 60.0


class PolymarketRepository:
    """Wraps PolymarketRestClient + MarketDiscovery + WS cache.

    Owns the current CandleMarket, handles lazy discovery, and tracks
    discovery failures / outage state internally.
    """

    def __init__(
        self,
        rest: PolymarketRestClient,
        discovery: MarketDiscovery,
        logger: logging.Logger,
    ) -> None:
        self._rest = rest
        self._discovery = discovery
        self._log = logger
        self._market: CandleMarket | None = None
        self._ws_orderbook: OrderbookSnapshot | None = None
        self._ws_last_price: float | None = None

        # Outage tracking — owned by the repo, read by provider/dashboard
        self.discovery_failures: int = 0
        self.outage_start: float | None = None
        self.outage_recovered: float | None = None
        self.last_outage_duration: float = 0.0

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
        Tracks discovery failures and outage state internally.
        """
        if self._market is None or self._market.time_remaining() <= 0:
            self._market = await self._discover()
            if self._market is None:
                self._record_failure()
                return None
            self._record_success()

        up_orderbook, down_orderbook, last_price = await self._fetch_market_data()

        return BetData(
            market=self._market,
            orderbook=up_orderbook,
            down_orderbook=down_orderbook,
            last_trade_price=last_price,
        )

    async def _fetch_market_data(self) -> tuple[OrderbookSnapshot, OrderbookSnapshot, float | None]:
        """Fetch UP orderbook, DOWN orderbook, and last price in parallel."""
        assert self._market is not None  # noqa: S101 — caller guarantees

        # Build coroutines, using WS cache where available
        up_coro = (
            asyncio.sleep(0, result=self._ws_orderbook)
            if self._ws_orderbook is not None
            else self._rest.get_orderbook(token_id=self._market.up_token_id)
        )
        down_coro = self._rest.get_orderbook(token_id=self._market.down_token_id)
        price_coro = (
            asyncio.sleep(0, result=self._ws_last_price)
            if self._ws_last_price is not None
            else self._rest.get_last_trade_price(token_id=self._market.up_token_id)
        )

        return await asyncio.gather(up_coro, down_coro, price_coro)

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

    # --- Outage tracking (internal) ---

    def _record_failure(self) -> None:
        """Increment failure counter; start outage after threshold."""
        self.discovery_failures += 1
        if self.discovery_failures >= _OUTAGE_THRESHOLD and self.outage_start is None:
            self.outage_start = time.time()
            self._log.warning(
                "Polymarket outage detected: %d consecutive discovery failures",
                self.discovery_failures,
            )
        elif self.outage_start is not None and self.discovery_failures % _OUTAGE_LOG_INTERVAL == 0:
            elapsed = time.time() - self.outage_start
            self._log.warning(
                "Polymarket outage ongoing: %.0fs elapsed (%d failures)",
                elapsed,
                self.discovery_failures,
            )

    def _record_success(self) -> None:
        """Clear outage state on successful discovery."""
        if self.outage_start is not None:
            duration = time.time() - self.outage_start
            self.last_outage_duration = duration
            self.outage_recovered = time.time()
            self._log.info(
                "Polymarket outage recovered after %.0fs (%d failures)",
                duration,
                self.discovery_failures,
            )
        self.discovery_failures = 0
        self.outage_start = None
        if self.outage_recovered and time.time() - self.outage_recovered > _RECOVERY_BANNER_TTL:
            self.outage_recovered = None
