"""Port: read-only access to completed candle history."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from polybot_data.domain.collection import CandleRecord


@runtime_checkable
class CandleRepository(Protocol):
    """Reads completed candles for indicator computation."""

    async def get_recent_candles(self, limit: int) -> list[CandleRecord]:
        """Return last `limit` candles, oldest first.

        Each CandleRecord has: open, high, low, close, volume, outcome, final_ret.
        """
        ...
