"""Repository protocol for market_data external data access."""

from __future__ import annotations

from typing import Protocol

from polybot.models import BtcCandle, BtcPrice, CandleMarket, OrderbookSnapshot


class MarketDataRepository(Protocol):
    """Single abstraction for all external data needed by market_data consumers.

    Implementations bridge to concrete services (Polymarket REST API, Binance,
    Chainlink, CoinGecko, Gamma API). Test doubles can implement this protocol
    to avoid real network calls.
    """

    async def get_orderbook(self, token_id: str) -> OrderbookSnapshot:
        """Fetch current orderbook for a token."""
        ...

    async def get_last_trade_price(self, token_id: str) -> float | None:
        """Fetch last trade price for a token."""
        ...

    async def get_btc_price(self) -> BtcPrice | None:
        """Fetch current BTC/USD price from the primary source."""
        ...

    async def get_btc_price_at(self, timestamp: float) -> float | None:
        """Fetch historical BTC price at a specific timestamp."""
        ...

    async def get_btc_candles(self) -> list[BtcCandle]:
        """Fetch recent 5-min BTC OHLCV candles."""
        ...

    async def get_market_by_slug(self, slug: str) -> CandleMarket | None:
        """Fetch a candle market by its slug."""
        ...
