"""REST wrapper around py-clob-client for async compatibility."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from py_clob_client.client import ClobClient

from polybot.config import ApiConfig, MarketConfig
from polybot.models import OrderbookLevel, OrderbookSnapshot


class PolymarketRestClient:
    """Wraps the sync py-clob-client with run_in_executor for async compat."""

    def __init__(
        self,
        market_config: MarketConfig,
        api_config: ApiConfig,
        logger: logging.Logger,
    ) -> None:
        self._log = logger
        self._market_config = market_config
        self._api_config = api_config
        self._client = ClobClient(api_config.polymarket_host)

    async def get_orderbook(self, token_id: str | None = None) -> OrderbookSnapshot:
        """Fetch current orderbook for the configured token."""
        tid = token_id or self._market_config.token_id
        if not tid:
            self._log.warning("No token_id configured, returning empty orderbook")
            return OrderbookSnapshot()

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, partial(self._client.get_order_book, tid))
        except Exception:
            self._log.exception("Failed to fetch orderbook")
            return OrderbookSnapshot()

        # py-clob-client returns OrderBookSummary with OrderSummary items
        # that have .price/.size as strings, or it may return a dict
        raw_bids = raw.bids if hasattr(raw, "bids") else (raw.get("bids") or [])
        raw_asks = raw.asks if hasattr(raw, "asks") else (raw.get("asks") or [])

        def _parse_level(item) -> OrderbookLevel:
            if hasattr(item, "price"):
                return OrderbookLevel(price=float(item.price), size=float(item.size))
            return OrderbookLevel(price=float(item["price"]), size=float(item["size"]))

        bids = [_parse_level(b) for b in raw_bids]
        asks = [_parse_level(a) for a in raw_asks]
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
            raw = await loop.run_in_executor(None, partial(self._client.get_last_trade_price, tid))
            if raw is None:
                return None
            price = raw.price if hasattr(raw, "price") else raw.get("price", 0)
            return float(price) if price else None
        except Exception:
            self._log.exception("Failed to fetch last trade price")
            return None

    async def get_market_info(self, condition_id: str | None = None) -> dict:
        """Fetch market metadata."""
        cid = condition_id or self._market_config.condition_id
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, partial(self._client.get_market, cid))
            return raw or {}
        except Exception:
            self._log.exception("Failed to fetch market info")
            return {}
