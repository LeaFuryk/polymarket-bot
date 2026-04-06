"""Tests for IndicatorService."""

from unittest.mock import AsyncMock

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot

from polybot.services.indicator_service import IndicatorService

MINIMUM_CANDLES = 21


def _make_candle(i: int) -> CandleRecord:
    return CandleRecord(
        candle_id=f"candle-{i}",
        start_time=float(i * 300),
        end_time=float((i + 1) * 300),
        open=100.0 + i,
        high=110.0 + i,
        low=90.0 + i,
        close=105.0 + i,
        volume=10.0,
        outcome="UP" if i % 2 == 0 else "DOWN",
        final_ret=0.001 if i % 2 == 0 else -0.001,
    )


def _make_snapshot(candle_id: str = "test-100", elapsed: float = 0.5, price: float = 69000.0) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        candle_id=candle_id,
        timestamp=1000.0,
        elapsed_pct=elapsed,
        btc_price=price,
        btc_bid=price - 2,
        btc_ask=price + 2,
        up_bids=[[0.55, 100]],
        up_asks=[[0.57, 150]],
        down_bids=[[0.43, 120]],
        down_asks=[[0.45, 80]],
        market_volume=5000.0,
    )


def _make_candle_close(candle_id: str = "test-100") -> CandleRecord:
    return CandleRecord(
        candle_id=candle_id,
        start_time=0.0,
        end_time=0.0,
        open=69000.0,
        high=69100.0,
        low=68900.0,
        close=69050.0,
        volume=15.0,
        outcome="UP",
        final_ret=0.0007,
    )


class TestIndicatorServiceSync:
    async def test_not_synced_on_init(self):
        repo = AsyncMock()
        svc = IndicatorService(candle_repo=repo)
        assert svc.synced is False

    async def test_snapshot_ignored_before_sync(self):
        repo = AsyncMock()
        svc = IndicatorService(candle_repo=repo)
        row = svc.on_snapshot(_make_snapshot("test-100"))
        assert row is None

    async def test_sync_on_first_candle_close(self):
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=[_make_candle(i) for i in range(MINIMUM_CANDLES)])
        svc = IndicatorService(candle_repo=repo)
        await svc.on_candle_close(_make_candle_close())
        assert svc.synced is True
        repo.get_recent_candles.assert_awaited_once_with(MINIMUM_CANDLES)

    async def test_prior_candles_loaded_on_sync(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        svc = IndicatorService(candle_repo=repo)
        await svc.on_candle_close(_make_candle_close())
        assert len(svc._prior_candles) == MINIMUM_CANDLES + 1


class TestIndicatorServiceRow:
    async def test_snapshot_returns_row_after_sync(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        svc = IndicatorService(candle_repo=repo)
        await svc.on_candle_close(_make_candle_close("candle-1"))
        row = svc.on_snapshot(_make_snapshot("candle-2"))
        assert row is not None
        assert row["candle_id"] == "candle-2"
        assert row["btc_price"] == 69000.0
        assert "rsi" in row
        assert "prior_return" in row
        assert "outcome" not in row

    async def test_candle_close_appends(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        svc = IndicatorService(candle_repo=repo)
        await svc.on_candle_close(_make_candle_close("candle-1"))
        initial_count = len(svc._prior_candles)
        await svc.on_candle_close(_make_candle_close("candle-2"))
        assert len(svc._prior_candles) == initial_count + 1

    async def test_snapshots_reset_on_new_candle(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        svc = IndicatorService(candle_repo=repo)
        await svc.on_candle_close(_make_candle_close("candle-1"))
        svc.on_snapshot(_make_snapshot("candle-2", elapsed=0.1, price=69000.0))
        svc.on_snapshot(_make_snapshot("candle-2", elapsed=0.2, price=69010.0))
        assert len(svc._snapshots_so_far) == 2

        svc.on_snapshot(_make_snapshot("candle-3", elapsed=0.01, price=69020.0))
        assert len(svc._snapshots_so_far) == 1
        assert svc._current_candle_id == "candle-3"

    async def test_row_has_all_56_indicators(self):
        candles = [_make_candle(i) for i in range(MINIMUM_CANDLES)]
        repo = AsyncMock()
        repo.get_recent_candles = AsyncMock(return_value=candles)
        svc = IndicatorService(candle_repo=repo)
        await svc.on_candle_close(_make_candle_close("candle-1"))
        row = svc.on_snapshot(_make_snapshot("candle-2"))
        assert len(row) >= 69
