"""Tests for ModelRunner."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot

from polybot.domain.trading_strategy import TradingStrategy
from polybot.services.model_runner import ModelRunner
from polybot.services.portfolio_service import PortfolioService


def _make_strategy(entry_points=((0.05, 3),), min_confidence=0.0):
    return TradingStrategy(
        name="TestModel",
        entry_points=tuple(entry_points),
        min_confidence=min_confidence,
    )


def _make_snapshot(candle_id="c1", elapsed=0.06, up_ask=0.60, down_ask=0.40):
    return IndicatorSnapshot(
        candle_id=candle_id,
        timestamp=time.time(),
        elapsed_pct=elapsed,
        btc_price=70000.0,
        btc_bid=69999.0,
        btc_ask=70001.0,
        up_bids=[(0.58, 100)],
        up_asks=[(up_ask, 100)],
        down_bids=[(0.38, 100)],
        down_asks=[(down_ask, 100)],
        market_volume=50.0,
    )


def _make_runner(strategy=None, predictor=None):
    if strategy is None:
        strategy = _make_strategy()
    if predictor is None:
        predictor = MagicMock()
        predictor.predict.return_value = 0.7  # predict UP
    portfolio = PortfolioService(initial_cash=1000.0)
    bet_store = AsyncMock()
    broadcaster = AsyncMock()
    return ModelRunner(
        name="TestModel",
        predictor=predictor,
        portfolio=portfolio,
        strategy=strategy,
        bet_store=bet_store,
        broadcaster=broadcaster,
    )


class TestHandleSnapshot:
    @pytest.mark.asyncio
    async def test_no_entry_before_checkpoint_elapsed(self):
        runner = _make_runner()
        row = {"feat1": 1.0}
        snapshot = _make_snapshot(elapsed=0.01)  # before 5%
        await runner.handle_snapshot(row, snapshot)
        assert runner._entries_made == 0

    @pytest.mark.asyncio
    async def test_entry_after_3_consecutive_predictions(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(3):
            await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 1

    @pytest.mark.asyncio
    async def test_entry_broadcasts_model_entry(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(3):
            await runner.handle_snapshot(row, snap)
        runner._broadcaster.broadcast_json.assert_awaited_once()
        msg = runner._broadcaster.broadcast_json.call_args[0][0]
        assert msg["type"] == "model_entry"
        assert msg["model"] == "TestModel"
        assert msg["direction"] == "UP"
        assert "inference_ms" in msg

    @pytest.mark.asyncio
    async def test_min_confidence_filters_entry(self):
        predictor = MagicMock()
        predictor.predict.return_value = 0.52  # confidence = 0.52, below 0.6
        strategy = _make_strategy(min_confidence=0.6)
        runner = _make_runner(strategy=strategy, predictor=predictor)
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(10):
            await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 0

    @pytest.mark.asyncio
    async def test_max_bid_filters_entry(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06, up_ask=0.90)  # above MAX_BID
        row = {"feat1": 1.0}
        for _ in range(3):
            await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 0


class TestHandleCandleClose:
    @pytest.mark.asyncio
    async def test_settlement_saves_bet_and_broadcasts(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(3):
            await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 1

        candle = CandleRecord(
            candle_id="c1",
            start_time=0,
            end_time=300,
            open=70000,
            high=70100,
            low=69900,
            close=70050,
            volume=50,
            outcome="UP",
            final_ret=0.0007,
        )
        await runner.handle_candle_close(candle)

        runner._bet_store.save_bet.assert_awaited_once()
        saved = runner._bet_store.save_bet.call_args[0][0]
        assert saved.won is True
        assert saved.direction == "UP"

        calls = runner._broadcaster.broadcast_json.call_args_list
        settlement = calls[-1][0][0]
        assert settlement["type"] == "model_settlement"
        assert settlement["model"] == "TestModel"
        assert settlement["won"] is True

    @pytest.mark.asyncio
    async def test_settlement_resets_candle_state(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(3):
            await runner.handle_snapshot(row, snap)

        candle = CandleRecord(
            candle_id="c1",
            start_time=0,
            end_time=300,
            open=70000,
            high=70100,
            low=69900,
            close=70050,
            volume=50,
            outcome="UP",
            final_ret=0.0007,
        )
        await runner.handle_candle_close(candle)

        assert runner._entries_made == 0
        assert runner._predictions == []
        assert runner._first_direction is None

    @pytest.mark.asyncio
    async def test_no_position_skips_bet_save(self):
        runner = _make_runner()
        candle = CandleRecord(
            candle_id="c1",
            start_time=0,
            end_time=300,
            open=70000,
            high=70100,
            low=69900,
            close=70050,
            volume=50,
            outcome="UP",
            final_ret=0.0007,
        )
        await runner.handle_candle_close(candle)
        runner._bet_store.save_bet.assert_not_awaited()


class TestHandleCorrection:
    def test_correction_calls_reverse_and_resettle(self):
        runner = _make_runner()
        # Manually buy to create a settlement record
        runner._portfolio.buy("UP", amount_usd=20.0, price=0.60)
        runner._portfolio.settle("UP", candle_id="c1")

        corrected = CandleRecord(
            candle_id="c1",
            start_time=0,
            end_time=300,
            open=70000,
            high=70100,
            low=69900,
            close=69950,
            volume=50,
            outcome="DOWN",
            final_ret=-0.0007,
        )
        runner.handle_correction(corrected)
        # Should not raise — reverse_and_resettle handles it
