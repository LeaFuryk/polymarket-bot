"""Integration test: 3 model runners process the same snapshot independently."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from polybot.domain.trading_strategy import TradingStrategy
from polybot.services.agent_service import AgentService
from polybot.services.model_runner import ModelRunner
from polybot.services.portfolio_service import PortfolioService


def _make_predictor(p_up: float):
    p = MagicMock()
    p.predict.return_value = p_up
    return p


@pytest.mark.asyncio
async def test_three_runners_independent_portfolios():
    """3 runners with different predictions produce independent results."""
    broadcaster = AsyncMock()

    runners = []
    for name, p_up in [("LR", 0.7), ("RF", 0.3), ("XGB", 0.8)]:
        strategy = TradingStrategy(
            name=name,
            entry_points=((0.05, 1),),  # 1 consecutive for simplicity
            min_confidence=0.0,
            min_btc_move=0.0,  # disable dual-mode for this test
            noise_entry_elapsed=1.0,
        )
        runner = ModelRunner(
            name=name,
            predictor=_make_predictor(p_up),
            portfolio=PortfolioService(initial_cash=1000.0),
            strategy=strategy,
            bet_store=AsyncMock(),
            broadcaster=broadcaster,
        )
        runners.append(runner)

    indicators = MagicMock()
    indicators.prior_candles = []
    indicators.snapshots_so_far = []
    indicators.on_candle_close = AsyncMock()
    row = {"feat1": 1.0}
    indicators.on_snapshot.return_value = row

    agent = AgentService(indicators=indicators, runners=runners)

    msg = {
        "type": "snapshot",
        "candle_id": "c1",
        "timestamp": 1.0,
        "elapsed_pct": 0.06,
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

    # LR predicts UP (0.7), RF predicts DOWN (0.3), XGB predicts UP (0.8)
    assert runners[0]._entries_made == 1  # LR: UP
    assert runners[0]._first_direction == "UP"
    assert runners[1]._entries_made == 1  # RF: DOWN
    assert runners[1]._first_direction == "DOWN"
    assert runners[2]._entries_made == 1  # XGB: UP
    assert runners[2]._first_direction == "UP"

    # Each has its own portfolio — cash deducted independently
    assert runners[0].portfolio.state.cash < 1000.0
    assert runners[1].portfolio.state.cash < 1000.0
    assert runners[2].portfolio.state.cash < 1000.0

    # 3 model_entry broadcasts
    entry_calls = [c[0][0] for c in broadcaster.broadcast_json.call_args_list if c[0][0].get("type") == "model_entry"]
    assert len(entry_calls) == 3
    models = {c["model"] for c in entry_calls}
    assert models == {"LR", "RF", "XGB"}
