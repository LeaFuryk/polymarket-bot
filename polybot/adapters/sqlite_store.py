"""Adapter: SQLite-backed data store for raw market snapshots and candles."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from polybot.domain.collection import CandleRecord, Snapshot

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candle_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    tick_timestamp REAL NOT NULL,
    elapsed_pct REAL NOT NULL,
    btc_price REAL NOT NULL,
    btc_bid REAL NOT NULL,
    btc_ask REAL NOT NULL,
    up_last_trade REAL,
    down_last_trade REAL,
    market_volume REAL NOT NULL,
    orderbook_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_snap_unique ON snapshots(candle_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(timestamp);

CREATE TABLE IF NOT EXISTS candles (
    candle_id TEXT PRIMARY KEY,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    outcome TEXT NOT NULL,
    final_ret REAL NOT NULL
);
"""


class SqliteStore:
    """SQLite adapter implementing the DataStore port."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the database and create tables if needed."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def write_snapshot(self, snapshot: Snapshot) -> None:
        """Insert a single snapshot row."""
        assert self._db is not None
        ob_json = json.dumps(
            {
                "up_bids": list(snapshot.up_bids),
                "up_asks": list(snapshot.up_asks),
                "down_bids": list(snapshot.down_bids),
                "down_asks": list(snapshot.down_asks),
            }
        )
        await self._db.execute(
            """
            INSERT OR IGNORE INTO snapshots
                (candle_id, timestamp, tick_timestamp, elapsed_pct,
                 btc_price, btc_bid, btc_ask,
                 up_last_trade, down_last_trade, market_volume, orderbook_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.candle_id,
                snapshot.timestamp,
                snapshot.tick_timestamp,
                snapshot.elapsed_pct,
                snapshot.btc_price,
                snapshot.btc_bid,
                snapshot.btc_ask,
                snapshot.up_last_trade,
                snapshot.down_last_trade,
                snapshot.market_volume,
                ob_json,
            ),
        )
        await self._db.commit()

    async def write_candle(self, record: CandleRecord) -> None:
        """Insert or replace a candle record."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR IGNORE INTO candles
                (candle_id, start_time, end_time, open, high, low, close,
                 volume, outcome, final_ret)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.candle_id,
                record.start_time,
                record.end_time,
                record.open,
                record.high,
                record.low,
                record.close,
                record.volume,
                record.outcome,
                record.final_ret,
            ),
        )
        await self._db.commit()

    async def get_candle(self, candle_id: str) -> CandleRecord | None:
        """Read a candle by ID. Returns None if not found."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT candle_id, start_time, end_time, open, high, low, close, volume, outcome, final_ret "
            "FROM candles WHERE candle_id = ?",
            (candle_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return CandleRecord(
            candle_id=row[0],
            start_time=row[1],
            end_time=row[2],
            open=row[3],
            high=row[4],
            low=row[5],
            close=row[6],
            volume=row[7],
            outcome=row[8],
            final_ret=row[9],
        )

    async def get_snapshots(self, candle_id: str) -> list[Snapshot]:
        """Return all snapshots for a candle, ordered by timestamp."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT candle_id, timestamp, tick_timestamp, elapsed_pct, "
            "btc_price, btc_bid, btc_ask, up_last_trade, down_last_trade, "
            "market_volume, orderbook_json "
            "FROM snapshots WHERE candle_id = ? ORDER BY timestamp",
            (candle_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        result: list[Snapshot] = []
        for row in rows:
            ob = json.loads(row[10])
            result.append(
                Snapshot(
                    candle_id=row[0],
                    timestamp=row[1],
                    tick_timestamp=row[2],
                    elapsed_pct=row[3],
                    btc_price=row[4],
                    btc_bid=row[5],
                    btc_ask=row[6],
                    up_last_trade=row[7],
                    down_last_trade=row[8],
                    market_volume=row[9],
                    up_bids=tuple(tuple(lvl) for lvl in ob["up_bids"]),
                    up_asks=tuple(tuple(lvl) for lvl in ob["up_asks"]),
                    down_bids=tuple(tuple(lvl) for lvl in ob["down_bids"]),
                    down_asks=tuple(tuple(lvl) for lvl in ob["down_asks"]),
                )
            )
        return result

    async def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None
