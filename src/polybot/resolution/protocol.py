"""Repository protocol for resolution external data access."""

from __future__ import annotations

from typing import Protocol


class ResolutionRepository(Protocol):
    """Single abstraction for all external data needed during resolution.

    Implementations bridge to concrete services (Binance, Polymarket REST API).
    """

    async def get_btc_price_at(self, timestamp: float) -> float | None:
        """Fetch historical BTC price at the given timestamp."""
        ...

    async def get_last_trade_price(self, token_id: str) -> float | None:
        """Fetch last trade price for a Polymarket token."""
        ...
