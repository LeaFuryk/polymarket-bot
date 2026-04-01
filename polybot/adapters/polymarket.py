"""Adapter: Polymarket CLOB + Gamma API client (read-only)."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from polybot.domain.models import Market, MarketSnapshot, OrderBook, OrderBookLevel

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
CANDLE_INTERVAL = 300  # 5 minutes


class PolymarketAdapter:
    """MarketFeed implementation using Polymarket CLOB + Gamma APIs.

    Read-only: fetches orderbooks, prices, and market discovery.
    No authentication needed for reads.
    """

    def __init__(
        self,
        *,
        clob_host: str = CLOB_HOST,
        gamma_host: str = GAMMA_HOST,
    ) -> None:
        self._clob_host = clob_host
        self._gamma_host = gamma_host

    # -- MarketFeed interface -----------------------------------------------

    async def discover_market(self, series_slug: str) -> Market | None:
        """Find the current active candle market via Gamma API."""
        now = time.time()
        boundary = int(now - (now % CANDLE_INTERVAL))
        slug = f"{series_slug}-{boundary}"

        market = await self._fetch_market_by_slug(slug)
        if market is not None:
            return market

        # Fallback: try next boundary
        next_boundary = boundary + CANDLE_INTERVAL
        next_slug = f"{series_slug}-{next_boundary}"
        return await self._fetch_market_by_slug(next_slug)

    async def get_orderbooks(self, market: Market) -> tuple[OrderBook, OrderBook]:
        """Fetch UP and DOWN orderbooks in parallel."""
        up_book, down_book = await asyncio.gather(
            self._fetch_orderbook(market.up_token_id),
            self._fetch_orderbook(market.down_token_id),
        )
        return up_book, down_book

    async def get_last_trade_price(self, token_id: str) -> float | None:
        """Fetch last trade price for a token."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._clob_host}/last-trade-price",
                    params={"token_id": token_id},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
                price = data.get("price")
                return float(price) if price is not None else None
        except Exception:
            logger.exception("Failed to fetch last trade price for %s", token_id)
            return None

    async def get_snapshot(self, market: Market) -> MarketSnapshot:
        """Fetch complete market state."""
        (up_book, down_book), last_price = await asyncio.gather(
            self.get_orderbooks(market),
            self.get_last_trade_price(market.up_token_id),
        )
        return MarketSnapshot(
            market=market,
            up_book=up_book,
            down_book=down_book,
            last_trade_price=last_price,
        )

    # -- Gamma API ----------------------------------------------------------

    async def _fetch_market_by_slug(self, slug: str) -> Market | None:
        """Query Gamma API for a market by slug."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._gamma_host}/events",
                    params={"slug": slug},
                    timeout=10.0,
                )
                resp.raise_for_status()
                events = resp.json()

            if not events:
                logger.debug("No market found for slug: %s", slug)
                return None

            event = events[0]
            markets = event.get("markets", [])
            if not markets:
                return None

            mkt = markets[0]
            condition_id = mkt.get("conditionId", "")

            # Token IDs are JSON-encoded in clobTokenIds
            token_ids_raw = mkt.get("clobTokenIds", "[]")
            if isinstance(token_ids_raw, str):
                token_ids = json.loads(token_ids_raw)
            else:
                token_ids = token_ids_raw

            if len(token_ids) < 2:
                logger.warning("Market %s has fewer than 2 token IDs", slug)
                return None

            # Parse end time
            end_date = mkt.get("endDate", event.get("endDate", ""))
            end_time = self._parse_end_time(end_date)

            volume = float(mkt.get("volumeClob", mkt.get("volume", 0)))

            return Market(
                condition_id=condition_id,
                up_token_id=token_ids[0],
                down_token_id=token_ids[1],
                slug=slug,
                question=event.get("title", ""),
                end_time=end_time,
                volume=volume,
            )
        except Exception:
            logger.exception("Failed to discover market for slug: %s", slug)
            return None

    @staticmethod
    def _parse_end_time(end_date: str) -> float:
        """Parse ISO 8601 date string to epoch seconds."""
        if not end_date:
            return 0.0
        try:
            from datetime import datetime

            # Handle both "2024-01-01T00:00:00Z" and "2024-01-01T00:00:00.000Z"
            end_date = end_date.replace("Z", "+00:00")
            dt = datetime.fromisoformat(end_date)
            return dt.timestamp()
        except Exception:
            return 0.0

    # -- CLOB API -----------------------------------------------------------

    async def _fetch_orderbook(self, token_id: str) -> OrderBook:
        """Fetch orderbook for a single token."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._clob_host}/book",
                    params={"token_id": token_id},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()

            return self._parse_orderbook(data)
        except Exception:
            logger.exception("Failed to fetch orderbook for %s", token_id)
            return OrderBook(bids=(), asks=(), timestamp=time.time())

    @staticmethod
    def _parse_orderbook(data: dict) -> OrderBook:
        """Parse CLOB orderbook response into domain OrderBook."""
        bids = tuple(
            OrderBookLevel(price=float(level["price"]), size=float(level["size"])) for level in data.get("bids", [])
        )
        asks = tuple(
            OrderBookLevel(price=float(level["price"]), size=float(level["size"])) for level in data.get("asks", [])
        )
        return OrderBook(bids=bids, asks=asks, timestamp=time.time())
