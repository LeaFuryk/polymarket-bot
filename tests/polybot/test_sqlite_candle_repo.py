"""Tests for SqliteCandleRepository."""

from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.ports.candle_repository import CandleRepository
from polybot_data.domain.collection import CandleRecord


class TestSqliteCandleRepository:
    def test_implements_protocol(self):
        repo = SqliteCandleRepository(":memory:")
        assert isinstance(repo, CandleRepository)

    async def test_get_recent_candles_returns_oldest_first(self):
        repo = SqliteCandleRepository(":memory:")
        await repo.init()
        try:
            db = repo._db
            await db.execute(
                "CREATE TABLE candles ("
                "candle_id TEXT PRIMARY KEY, start_time REAL, end_time REAL, "
                "open REAL, high REAL, low REAL, close REAL, volume REAL, "
                "outcome TEXT, final_ret REAL)"
            )
            for i in range(5):
                await db.execute(
                    "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"c-{i}",
                        i * 300.0,
                        (i + 1) * 300.0,
                        100.0 + i,
                        110.0 + i,
                        90.0 + i,
                        105.0 + i,
                        10.0,
                        "UP",
                        0.001,
                    ),
                )
            await db.commit()

            candles = await repo.get_recent_candles(3)
            assert len(candles) == 3
            assert candles[0].open == 102.0  # 3rd oldest of 5
            assert candles[2].open == 104.0  # most recent
        finally:
            await repo.close()

    async def test_get_recent_candles_empty_db(self):
        repo = SqliteCandleRepository(":memory:")
        await repo.init()
        try:
            db = repo._db
            await db.execute(
                "CREATE TABLE candles ("
                "candle_id TEXT PRIMARY KEY, start_time REAL, end_time REAL, "
                "open REAL, high REAL, low REAL, close REAL, volume REAL, "
                "outcome TEXT, final_ret REAL)"
            )
            await db.commit()
            candles = await repo.get_recent_candles(10)
            assert candles == []
        finally:
            await repo.close()

    async def test_returns_candle_record_with_correct_fields(self):
        repo = SqliteCandleRepository(":memory:")
        await repo.init()
        try:
            db = repo._db
            await db.execute(
                "CREATE TABLE candles ("
                "candle_id TEXT PRIMARY KEY, start_time REAL, end_time REAL, "
                "open REAL, high REAL, low REAL, close REAL, volume REAL, "
                "outcome TEXT, final_ret REAL)"
            )
            await db.execute(
                "INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("c-0", 0.0, 300.0, 100.0, 110.0, 90.0, 105.0, 10.0, "UP", 0.001),
            )
            await db.commit()
            candles = await repo.get_recent_candles(1)
            assert isinstance(candles[0], CandleRecord)
            assert candles[0].candle_id == "c-0"
            assert candles[0].open == 100.0
            assert candles[0].high == 110.0
            assert candles[0].low == 90.0
            assert candles[0].close == 105.0
            assert candles[0].volume == 10.0
            assert candles[0].outcome == "UP"
            assert candles[0].final_ret == 0.001
        finally:
            await repo.close()
