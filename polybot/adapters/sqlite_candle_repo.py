"""Adapter: read-only SQLite access to completed candle history."""

from __future__ import annotations

import logging

import aiosqlite
from polybot_data.domain.collection import CandleRecord


class SqliteCandleRepository:
    """Reads candles from SQLite in read-only mode."""

    def __init__(self, db_path: str, logger: logging.Logger | None = None) -> None:
        self._db_path = db_path
        self._log = logger or logging.getLogger(__name__)
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        uri = f"file:{self._db_path}?mode=ro"
        if self._db_path == ":memory:":
            uri = self._db_path
        self._db = await aiosqlite.connect(uri, uri=self._db_path != ":memory:")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def get_recent_candles(self, limit: int) -> list[CandleRecord]:
        """Return last `limit` candles, oldest first."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT candle_id, start_time, end_time, "
            "open, high, low, close, volume, outcome, final_ret "
            "FROM candles ORDER BY start_time DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            CandleRecord(
                candle_id=r[0],
                start_time=r[1],
                end_time=r[2],
                open=r[3],
                high=r[4],
                low=r[5],
                close=r[6],
                volume=r[7],
                outcome=r[8],
                final_ret=r[9],
            )
            for r in reversed(rows)
        ]
