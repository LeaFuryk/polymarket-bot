"""REST wrapper around py-clob-client for async compatibility."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from py_clob_client.client import ClobClient

from polybot.config import MarketConfig, ApiConfig
from polybot.models import OrderbookLevel, OrderbookSnapshot

logger = logging.getLogger(__name__)


class PolymarketRestClient:
    """Wraps the sync py-clob-client with run_in_executor for async compat."""

    def __init__(self, market_config: MarketConfig, api_config: ApiConfig) -> None:
        self._market_config = market_config
        self._api_config = api_config
        self._client = ClobClient(api_config.polymarket_host)

    async def get_orderbook(self, token_id: str | None = None) -> OrderbookSnapshot:
        """Fetch current orderbook for the configured token."""
        tid = token_id or self._market_config.token_id
        if not tid:
            logger.warning("No token_id configured, returning empty orderbook")
            return OrderbookSnapshot()

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None, partial(self._client.get_order_book, tid)
            )
        except Exception:
            logger.exception("Failed to fetch orderbook")
            return OrderbookSnapshot()

        bids = [
            OrderbookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in (raw.get("bids") or [])
        ]
        asks = [
            OrderbookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in (raw.get("asks") or [])
        ]
        # Sort bids descending, asks ascending
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        return OrderbookSnapshot(bids=bids, asks=asks)

    async def get_last_trade_price(self, token_id: str | None = None) -> float | None:
        """Fetch last trade price for the token."""
        tid = token_id or self._market_config.token_id
        if not tid:
            return None

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None, partial(self._client.get_last_trade_price, tid)
            )
            return float(raw.get("price", 0)) if raw else None
        except Exception:
            logger.exception("Failed to fetch last trade price")
            return None

    async def get_market_info(self, condition_id: str | None = None) -> dict:
        """Fetch market metadata."""
        cid = condition_id or self._market_config.condition_id
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None, partial(self._client.get_market, cid)
            )
            return raw or {}
        except Exception:
            logger.exception("Failed to fetch market info")
            return {}
