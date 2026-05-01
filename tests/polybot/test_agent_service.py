"""Tests for AgentService orchestrator."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from polybot.services.agent_service import AgentService
from polybot_data.domain.collection import CandleRecord


def _make_agent(n_runners=2):
    indicators = MagicMock()
    indicators.on_snapshot.return_value = {"feat1": 1.0}
    indicators.prior_candles = []
    indicators.snapshots_so_far = []
    indicators.on_candle_close = AsyncMock()

    runners = []
    for i in range(n_runners):
        r = MagicMock()
        r.name = f"Model{i}"
        r.handle_snapshot = AsyncMock()
        r.handle_candle_close = AsyncMock()
        r.handle_correction = AsyncMock()
        runners.append(r)

    agent = AgentService(indicators=indicators, runners=runners)
    return agent, indicators, runners


class TestProcessSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_fans_out_to_all_runners(self):
        agent, indicators, runners = _make_agent(n_runners=3)
        msg = {
            "type": "snapshot",
            "candle_id": "c1",
            "timestamp": 1.0,
            "elapsed_pct": 0.5,
            "btc_price": 70000,
            "btc_bid": 69999,
            "btc_ask": 70001,
            "up_bids": [],
            "up_asks": [],
            "down_bids": [],
            "down_asks": [],
            "market_volume": 50,
        }
        await agent.process(msg)
        for r in runners:
            r.handle_snapshot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snapshot_skips_runners_if_not_synced(self):
        agent, indicators, runners = _make_agent(n_runners=2)
        indicators.on_snapshot.return_value = None  # not synced
        msg = {
            "type": "snapshot",
            "candle_id": "c1",
            "timestamp": 1.0,
            "elapsed_pct": 0.5,
            "btc_price": 70000,
            "btc_bid": 69999,
            "btc_ask": 70001,
            "up_bids": [],
            "up_asks": [],
            "down_bids": [],
            "down_asks": [],
            "market_volume": 50,
        }
        await agent.process(msg)
        for r in runners:
            r.handle_snapshot.assert_not_awaited()


class TestProcessCandleClose:
    @pytest.mark.asyncio
    async def test_candle_close_fans_out_to_all_runners(self):
        agent, indicators, runners = _make_agent(n_runners=3)
        msg = {
            "type": "candle_close",
            "candle_id": "c1",
            "start_time": 0,
            "end_time": 300,
            "open": 70000,
            "high": 70100,
            "low": 69900,
            "close": 70050,
            "volume": 50,
            "outcome": "UP",
            "final_ret": 0.001,
        }
        await agent.process(msg)
        for r in runners:
            r.handle_candle_close.assert_awaited_once()
        indicators.on_candle_close.assert_awaited_once()


class TestProcessCorrection:
    @pytest.mark.asyncio
    async def test_correction_fans_out_to_all_runners(self):
        agent, indicators, runners = _make_agent(n_runners=3)
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
            final_ret=0.001,
        )
        indicators.prior_candles = [candle]
        msg = {
            "type": "candle_correction",
            "candle_id": "c1",
            "start_time": 0,
            "end_time": 300,
            "open": 70000,
            "high": 70100,
            "low": 69900,
            "close": 69950,
            "volume": 50,
            "outcome": "DOWN",
            "final_ret": -0.001,
        }
        await agent.process(msg)
        for r in runners:
            r.handle_correction.assert_called_once()

    @pytest.mark.asyncio
    async def test_correction_no_outcome_change_skips_runners(self):
        agent, indicators, runners = _make_agent(n_runners=2)
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
            final_ret=0.001,
        )
        indicators.prior_candles = [candle]
        msg = {
            "type": "candle_correction",
            "candle_id": "c1",
            "start_time": 0,
            "end_time": 300,
            "open": 70000,
            "high": 70100,
            "low": 69900,
            "close": 70060,
            "volume": 50,
            "outcome": "UP",
            "final_ret": 0.001,
        }
        await agent.process(msg)
        for r in runners:
            r.handle_correction.assert_not_called()


class TestConsensusRunner:
    @pytest.mark.asyncio
    async def test_consensus_receives_predictions(self):
        agent, indicators, runners = _make_agent(n_runners=2)
        consensus = MagicMock()
        consensus.name = "Consensus"
        consensus.handle_snapshot = AsyncMock()
        consensus.handle_candle_close = AsyncMock()
        consensus.handle_correction = AsyncMock()

        for r in runners:
            r.last_prediction = 0.65

        agent_with_consensus = AgentService(indicators=indicators, runners=runners, consensus_runner=consensus)
        msg = {
            "type": "snapshot",
            "candle_id": "c1",
            "timestamp": 1.0,
            "elapsed_pct": 0.5,
            "btc_price": 70000,
            "btc_bid": 69999,
            "btc_ask": 70001,
            "up_bids": [[0.58, 100]],
            "up_asks": [[0.60, 100]],
            "down_bids": [[0.38, 100]],
            "down_asks": [[0.40, 100]],
            "market_volume": 50,
        }
        await agent_with_consensus.process(msg)

        consensus.handle_snapshot.assert_awaited_once()
        call_args = consensus.handle_snapshot.call_args
        predictions = call_args[1].get("predictions") if call_args[1] else call_args[0][2]
        assert "Model0" in predictions
        assert "Model1" in predictions

    @pytest.mark.asyncio
    async def test_consensus_settled_on_candle_close(self):
        agent, indicators, runners = _make_agent(n_runners=1)
        consensus = MagicMock()
        consensus.name = "Consensus"
        consensus.handle_candle_close = AsyncMock()
        consensus.handle_correction = AsyncMock()

        agent_with_consensus = AgentService(indicators=indicators, runners=runners, consensus_runner=consensus)
        msg = {
            "type": "candle_close",
            "candle_id": "c1",
            "start_time": 0,
            "end_time": 300,
            "open": 70000,
            "high": 70100,
            "low": 69900,
            "close": 70050,
            "volume": 50,
            "outcome": "UP",
            "final_ret": 0.001,
        }
        await agent_with_consensus.process(msg)
        consensus.handle_candle_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_consensus_still_works(self):
        """Existing behavior when no consensus runner provided."""
        agent, indicators, runners = _make_agent(n_runners=2)
        msg = {
            "type": "snapshot",
            "candle_id": "c1",
            "timestamp": 1.0,
            "elapsed_pct": 0.5,
            "btc_price": 70000,
            "btc_bid": 69999,
            "btc_ask": 70001,
            "up_bids": [[0.58, 100]],
            "up_asks": [[0.60, 100]],
            "down_bids": [[0.38, 100]],
            "down_asks": [[0.40, 100]],
            "market_volume": 50,
        }
        await agent.process(msg)
        for r in runners:
            r.handle_snapshot.assert_awaited_once()
