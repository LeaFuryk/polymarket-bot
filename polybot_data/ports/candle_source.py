"""Port: candle data source interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from polybot_data.domain.models import BtcTick, PartialCandle


@runtime_checkable
class CandleSource(Protocol):
    """Read-only interface for candle data. Used by DataCollector."""

    @property
    def latest_tick(self) -> BtcTick | None: ...

    @property
    def partial(self) -> PartialCandle | None: ...

    async def get_partial_volume(self, start_time: float = 0, end_time: float = 0) -> float: ...
