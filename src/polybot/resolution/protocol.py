"""Protocols for resolution dependencies — depend on abstractions, not concretions."""

from __future__ import annotations

from typing import Protocol


class BtcPriceFeedProtocol(Protocol):
    """Provides historical BTC prices for resolution fallback."""

    async def get_price_at(self, timestamp: float) -> float | None: ...


class PriceClient(Protocol):
    """Provides last-trade prices for Polymarket tokens."""

    async def get_last_trade_price(self, token_id: str) -> float | None: ...
