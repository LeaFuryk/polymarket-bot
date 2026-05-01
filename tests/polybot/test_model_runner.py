"""Tests for ModelRunner."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from polybot.domain.trading_strategy import TradingStrategy
from polybot.services.model_runner import ModelRunner
from polybot.services.portfolio_service import PortfolioService
from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot


def _make_strategy(min_edge=0.0, max_entries=1, min_btc_move=0.0):
    return TradingStrategy(
        name="TestModel",
        min_edge=min_edge,
        max_entries=max_entries,
        min_btc_move=min_btc_move,
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
    async def test_no_entry_before_btc_move(self):
        """No entry when BTC hasn't moved enough from candle open."""
        strategy = _make_strategy(min_btc_move=0.01)  # 1% move required
        runner = _make_runner(strategy=strategy)
        row = {"feat1": 1.0}
        snapshot = _make_snapshot(elapsed=0.06)
        await runner.handle_snapshot(row, snapshot)
        assert runner._entries_made == 0

    @pytest.mark.asyncio
    async def test_entry_when_edge_exceeds_threshold(self):
        """Entry placed on first snapshot when edge >= min_edge."""
        # p_up=0.7, direction=UP, ask=0.60, edge=0.7-0.6=0.10 >= 0.0
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06, up_ask=0.60)
        row = {"feat1": 1.0}
        await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 1

    @pytest.mark.asyncio
    async def test_entry_broadcasts_model_entry(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        await runner.handle_snapshot(row, snap)
        runner._broadcaster.broadcast_json.assert_awaited_once()
        msg = runner._broadcaster.broadcast_json.call_args[0][0]
        assert msg["type"] == "model_entry"
        assert msg["model"] == "TestModel"
        assert msg["direction"] == "UP"
        assert "inference_ms" in msg

    @pytest.mark.asyncio
    async def test_min_edge_filters_entry(self):
        """No entry when edge < min_edge."""
        predictor = MagicMock()
        predictor.predict.return_value = 0.52  # confidence=0.52, ask=0.60, edge=-0.08
        strategy = _make_strategy(min_edge=0.05)
        runner = _make_runner(strategy=strategy, predictor=predictor)
        snap = _make_snapshot(elapsed=0.06, up_ask=0.60)
        row = {"feat1": 1.0}
        await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 0

    @pytest.mark.asyncio
    async def test_max_entries_caps_entries(self):
        """No more than max_entries bets per candle."""
        strategy = _make_strategy(max_entries=2)
        runner = _make_runner(strategy=strategy)
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
        for _ in range(5):
            await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 2

    @pytest.mark.asyncio
    async def test_direction_lock_prevents_opposite_entry(self):
        """After first UP entry, DOWN prediction is skipped."""
        predictor = MagicMock()
        predictor.predict.side_effect = [0.7, 0.3]  # UP then DOWN
        runner = _make_runner(predictor=predictor)
        snap = _make_snapshot(elapsed=0.06, up_ask=0.60, down_ask=0.40)
        row = {"feat1": 1.0}
        await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 1
        assert runner._first_direction == "UP"
        await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 1  # no second entry (direction locked)

    @pytest.mark.asyncio
    async def test_max_bid_filters_entry(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06, up_ask=0.90)  # above MAX_BID
        row = {"feat1": 1.0}
        await runner.handle_snapshot(row, snap)
        assert runner._entries_made == 0


class TestHandleCandleClose:
    @pytest.mark.asyncio
    async def test_settlement_saves_bet_and_broadcasts(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06)
        row = {"feat1": 1.0}
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
    @pytest.mark.asyncio
    async def test_correction_reverses_and_resettles(self):
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
        await runner.handle_correction(corrected)
        # Should not raise — reverse_and_resettle handles it

    @pytest.mark.asyncio
    async def test_correction_updates_bet_store(self):
        """Correction rewrites the persisted bet record."""
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06, up_ask=0.60)
        row = {"feat1": 1.0}
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
        assert runner._settled_bets.get("c1") is not None

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
        await runner.handle_correction(corrected)

        runner._bet_store.update_bet.assert_awaited_once()
        args = runner._bet_store.update_bet.call_args[0]
        assert args[0] == "c1"  # candle_id
        assert args[1] == "DOWN"  # new_outcome
        assert args[2] is False  # new_won (direction was UP, outcome now DOWN)
        assert args[3] < 0  # pnl is negative (lost)

    @pytest.mark.asyncio
    async def test_correction_broadcasts_model_correction(self):
        """Correction broadcasts updated portfolio state to dashboard."""
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06, up_ask=0.60)
        row = {"feat1": 1.0}
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
        await runner.handle_correction(corrected)

        calls = runner._broadcaster.broadcast_json.call_args_list
        correction_msg = calls[-1][0][0]
        assert correction_msg["type"] == "model_correction"
        assert correction_msg["model"] == "TestModel"
        assert correction_msg["candle_id"] == "c1"
        assert correction_msg["outcome"] == "DOWN"
        assert correction_msg["won"] is False

    @pytest.mark.asyncio
    async def test_correction_without_bet_is_noop(self):
        """Correction on candle with no bet doesn't update store or broadcast."""
        runner = _make_runner()
        corrected = CandleRecord(
            candle_id="c99",
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
        await runner.handle_correction(corrected)
        runner._bet_store.update_bet.assert_not_awaited()
        for call in runner._broadcaster.broadcast_json.call_args_list:
            assert call[0][0].get("type") != "model_correction"


class TestEnsembleMode:
    @pytest.mark.asyncio
    async def test_last_prediction_set_after_snapshot(self):
        runner = _make_runner()
        snap = _make_snapshot(elapsed=0.06, up_ask=0.60)
        row = {"feat1": 1.0}
        await runner.handle_snapshot(row, snap)
        assert runner.last_prediction is not None
        assert 0.0 <= runner.last_prediction <= 1.0

    @pytest.mark.asyncio
    async def test_ensemble_uses_predict_ensemble(self):
        ensemble_predictor = MagicMock()
        ensemble_predictor.predict_ensemble.return_value = 0.7

        runner = ModelRunner(
            name="Consensus",
            predictor=ensemble_predictor,
            portfolio=PortfolioService(initial_cash=1000.0),
            strategy=_make_strategy(),
            bet_store=AsyncMock(),
            broadcaster=AsyncMock(),
            is_ensemble=True,
        )
        snap = _make_snapshot(elapsed=0.06, up_ask=0.60)
        row = {"feat1": 1.0}
        predictions = {"LR": 0.6, "RF": 0.7, "XGB": 0.65, "DNN": 0.72}
        await runner.handle_snapshot(row, snap, predictions=predictions)

        ensemble_predictor.predict_ensemble.assert_called_once_with(predictions, row, snap)
        assert runner.last_prediction == 0.7
