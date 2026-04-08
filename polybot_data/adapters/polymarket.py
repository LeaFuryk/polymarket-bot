"""Adapter: Polymarket CLOB + Gamma API client (read-only)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

import httpx

from polybot_data.domain.models import Market, MarketSnapshot, OrderBook, OrderBookLevel

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
        clob_host: str = CLOB_HOST,
        gamma_host: str = GAMMA_HOST,
        logger: logging.Logger | None = None,
    ) -> None:
        self._clob_host = clob_host
        self._gamma_host = gamma_host
        self._log = logger or logging.getLogger(__name__)
        self._clob_client = httpx.AsyncClient(base_url=clob_host, timeout=10.0)
        self._gamma_client = httpx.AsyncClient(base_url=gamma_host, timeout=10.0)
        self._cached_market: Market | None = None

    async def close(self) -> None:
        """Close HTTP clients."""
        await self._clob_client.aclose()
        await self._gamma_client.aclose()

    # -- MarketFeed interface -----------------------------------------------

    async def discover_market(self, series_slug: str) -> Market | None:
        """Find the current active candle market. Cached until expiry."""
        now = time.time()
        if self._cached_market is not None:
            # Only use cache if the market's time range contains now
            cache_start = self._cached_market.end_time - CANDLE_INTERVAL
            if cache_start <= now < self._cached_market.end_time:
                return self._cached_market
            self._cached_market = None

        boundary = int(now - (now % CANDLE_INTERVAL))

        # Try current, then previous (API lag) — never probe future
        for offset in [0, -CANDLE_INTERVAL]:
            slug = f"{series_slug}-{boundary + offset}"
            market = await self._fetch_market_by_slug(slug)
            if market is not None:
                self._cached_market = market
                return market
        return None

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
            resp = await self._clob_client.get(
                "/last-trade-price",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
            data = resp.json()
            price = data.get("price")
            return float(price) if price is not None else None
        except Exception:
            self._log.exception("Failed to fetch last trade price for %s", token_id)
            return None

    async def get_snapshot(self, market: Market) -> MarketSnapshot:
        """Fetch complete market state."""
        (up_book, down_book), up_price, down_price, volume = await asyncio.gather(
            self.get_orderbooks(market),
            self.get_last_trade_price(market.up_token_id),
            self.get_last_trade_price(market.down_token_id),
            self.get_market_volume(market.slug),
        )
        return MarketSnapshot(
            market=market,
            up_book=up_book,
            down_book=down_book,
            last_trade_price=up_price,
            down_last_trade_price=down_price,
            volume=volume,
        )

    async def get_market_volume(self, slug: str) -> float:
        """Fetch fresh cumulative volume from Gamma API."""
        try:
            resp = await self._gamma_client.get("/events", params={"slug": slug})
            resp.raise_for_status()
            events = resp.json()
            if not events:
                return 0.0
            mkt = events[0].get("markets", [{}])[0]
            return float(mkt.get("volumeClob", mkt.get("volume", 0)))
        except Exception:
            self._log.exception("Failed to fetch volume for %s", slug)
            return 0.0

    async def get_resolution(self, slug: str) -> dict | None:
        """Fetch Polymarket resolution from Gamma API eventMetadata.

        Returns dict with:
            open: float (priceToBeat)
            close: float (finalPrice)
            outcome: str ("UP" or "DOWN")
        Or None if resolution not available yet.
        """
        try:
            resp = await self._gamma_client.get("/events", params={"slug": slug})
            resp.raise_for_status()
            events = resp.json()
            if not events:
                return None

            event = events[0]
            mkt = event.get("markets", [{}])[0]

            # Market must be closed before resolution is available
            if not mkt.get("closed", False):
                return None

            meta = event.get("eventMetadata", {})
            if isinstance(meta, str):
                meta = json.loads(meta)

            price_to_beat = meta.get("priceToBeat")
            final_price = meta.get("finalPrice")
            if price_to_beat is None or final_price is None:
                return None
            # Derive outcome from outcomePrices if available, else from prices
            try:
                outcome_prices = mkt.get("outcomePrices", "[]")
                if isinstance(outcome_prices, str):
                    outcome_prices = json.loads(outcome_prices)
                if len(outcome_prices) >= 2:
                    up_price = float(outcome_prices[0])
                    down_price = float(outcome_prices[1])
                    if up_price > 0.5 and up_price > down_price:
                        outcome = "UP"
                    elif down_price > 0.5 and down_price > up_price:
                        outcome = "DOWN"
                    else:
                        outcome = "UP" if float(final_price) >= float(price_to_beat) else "DOWN"
                else:
                    outcome = "UP" if float(final_price) >= float(price_to_beat) else "DOWN"
            except (ValueError, TypeError, json.JSONDecodeError):
                outcome = "UP" if float(final_price) >= float(price_to_beat) else "DOWN"

            return {
                "open": float(price_to_beat),
                "close": float(final_price),
                "outcome": outcome,
            }
        except Exception:
            self._log.exception("Failed to fetch resolution for %s", slug)
            return None

    # -- Gamma API ----------------------------------------------------------

    async def _fetch_market_by_slug(self, slug: str) -> Market | None:
        """Query Gamma API for a market by slug."""
        try:
            resp = await self._gamma_client.get("/events", params={"slug": slug})
            resp.raise_for_status()
            events = resp.json()

            if not events:
                self._log.debug("No market found for slug: %s", slug)
                return None

            event = events[0]
            markets = event.get("markets", [])
            if not markets:
                return None

            mkt = markets[0]
            condition_id = mkt.get("conditionId", "")

            token_ids_raw = mkt.get("clobTokenIds", "[]")
            if isinstance(token_ids_raw, str):
                token_ids = json.loads(token_ids_raw)
            else:
                token_ids = token_ids_raw

            if len(token_ids) < 2:
                self._log.warning("Market %s has fewer than 2 token IDs", slug)
                return None

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
            self._log.exception("Failed to discover market for slug: %s", slug)
            return None

    @staticmethod
    def _parse_end_time(end_date: str) -> float:
        """Parse ISO 8601 date string to epoch seconds."""
        if not end_date:
            return 0.0
        try:
            end_date = end_date.replace("Z", "+00:00")
            dt = datetime.fromisoformat(end_date)
            return dt.timestamp()
        except Exception:
            return 0.0

    # -- CLOB API -----------------------------------------------------------

    async def _fetch_orderbook(self, token_id: str) -> OrderBook:
        """Fetch orderbook for a single token."""
        try:
            resp = await self._clob_client.get("/book", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
            return self._parse_orderbook(data)
        except Exception:
            self._log.exception("Failed to fetch orderbook for %s", token_id)
            return OrderBook(bids=(), asks=(), timestamp=time.time())

    @staticmethod
    def _parse_orderbook(data: dict) -> OrderBook:
        """Parse CLOB orderbook response into domain OrderBook.

        CLOB returns levels unsorted. Sort bids descending (highest first)
        and asks ascending (lowest first) so best_bid/best_ask are correct.
        """
        bids = tuple(
            sorted(
                (
                    OrderBookLevel(price=float(level["price"]), size=float(level["size"]))
                    for level in data.get("bids", [])
                ),
                key=lambda lvl: -lvl.price,
            )
        )
        asks = tuple(
            sorted(
                (
                    OrderBookLevel(price=float(level["price"]), size=float(level["size"]))
                    for level in data.get("asks", [])
                ),
                key=lambda lvl: lvl.price,
            )
        )
        return OrderBook(bids=bids, asks=asks, timestamp=time.time())
