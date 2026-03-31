"""Port: BTC volume feed interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VolumeFeed(Protocol):
    """Fetches BTC trading volume for time intervals."""

    async def get_volume(self, start_time: float, end_time: float) -> float:
        """Get BTC trading volume (in BTC) for a time interval."""
        ...

    async def get_candle_volumes(self, count: int, interval_sec: int = 300) -> list[float]:
        """Get volume for the last N candle intervals."""
        ...
