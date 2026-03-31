"""Port: streaming price feed interface."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from polybot.domain.models import BtcTick


@runtime_checkable
class PriceStream(Protocol):
    """Async streaming interface for real-time BTC/USD ticks."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    def ticks(self) -> AsyncIterator[BtcTick]: ...
