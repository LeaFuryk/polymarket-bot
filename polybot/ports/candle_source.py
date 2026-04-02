"""Port: candle data source interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from polybot.domain.models import BtcTick, Candle, CandleData, PartialCandle


@runtime_checkable
class CandleSource(Protocol):
    """Read-only interface for candle data. Used by MarketStateService."""

    @property
    def latest_tick(self) -> BtcTick | None: ...

    @property
    def partial(self) -> PartialCandle | None: ...

    def closed_candles(self) -> tuple[Candle, ...]: ...

    def candle_data(self) -> tuple[CandleData, ...]: ...

    async def get_partial_volume(self, start_time: float = 0, end_time: float = 0) -> float:
        """Get BTC volume for a candle interval.

        If start_time/end_time are provided, uses those (for snapshot consistency).
        Otherwise reads from the current partial candle.
        """
        ...
