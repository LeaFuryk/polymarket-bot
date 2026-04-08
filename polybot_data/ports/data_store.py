"""Port: data persistence interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from polybot_data.domain.collection import CandleRecord, Snapshot


@runtime_checkable
class DataStore(Protocol):
    async def init(self) -> None: ...
    async def write_snapshot(self, snapshot: Snapshot) -> None: ...
    async def write_candle(self, record: CandleRecord) -> None: ...
    async def get_candle(self, candle_id: str) -> CandleRecord | None: ...
    async def get_snapshots(self, candle_id: str) -> list[Snapshot]: ...
    async def update_candle(
        self,
        candle_id: str,
        open: float,
        high: float,
        low: float,
        close: float,
        outcome: str,
        final_ret: float,
    ) -> None: ...
    async def close(self) -> None: ...
