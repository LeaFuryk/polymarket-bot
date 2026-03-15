"""BTC data repository — wraps BtcPriceFeed into a single fetch() call."""

from __future__ import annotations

import logging

from polybot.models import BtcData, BtcPrice

from .btc_price import BtcPriceFeed


class BtcRepository:
    """Fetches BTC price + candle history as a single unit of work."""

    def __init__(
        self,
        feed: BtcPriceFeed,
        logger: logging.Logger | None = None,
    ) -> None:
        self._feed = feed
        self._log = logger or logging.getLogger(__name__)

    async def fetch(self) -> BtcData:
        """Fetch BTC price + append latest candle. Always returns (price may be None)."""
        price = await self._feed.get_price()
        await self._feed.append_latest_candle()
        return BtcData(price=price, candles=self._feed.candles)

    # --- Delegate methods for external consumers ---

    async def get_price(self) -> BtcPrice | None:
        return await self._feed.get_price()

    async def get_price_at(self, timestamp: float) -> float | None:
        return await self._feed.get_price_at(timestamp)

    async def load_history(self, limit: int = 200) -> None:
        await self._feed.load_candle_history(limit)

    async def close(self) -> None:
        await self._feed.close()
