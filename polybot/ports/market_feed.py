"""Port: Polymarket market data interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from polybot.domain.models import Market, MarketSnapshot, OrderBook


@runtime_checkable
class MarketFeed(Protocol):
    """Read-only interface for Polymarket market data."""

    async def discover_market(self, series_slug: str) -> Market | None:
        """Find the current active market for a series."""
        ...

    async def get_orderbooks(self, market: Market) -> tuple[OrderBook, OrderBook]:
        """Fetch UP and DOWN orderbooks. Returns (up_book, down_book)."""
        ...

    async def get_last_trade_price(self, token_id: str) -> float | None:
        """Get the last executed trade price for a token."""
        ...

    async def get_snapshot(self, market: Market) -> MarketSnapshot:
        """Fetch complete market state (orderbooks + last trade)."""
        ...
