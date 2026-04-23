"""Integration tests: DnnPredictor → ModelRunner → AgentService pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import joblib
import pytest

torch = pytest.importorskip("torch")

from polybot.adapters.dnn_predictor import DnnPredictor  # noqa: E402
from polybot.domain.trading_strategy import TradingStrategy  # noqa: E402
from polybot.services.agent_service import AgentService  # noqa: E402
from polybot.services.model_runner import ModelRunner  # noqa: E402
from polybot.services.portfolio_service import PortfolioService  # noqa: E402
from polybot_data.domain.collection import CandleRecord  # noqa: E402
from polybot_data.services.indicator_engine import IndicatorSnapshot  # noqa: E402

_N_FEATURES = 11
_FEATURE_COLS = [f"feat_{i}" for i in range(_N_FEATURES)]


# -- fixtures --------------------------------------------------------


@pytest.fixture()
def dnn_model(tmp_path: Path) -> tuple[str, str]:
    """Save a tiny nn.Linear(11, 1) with fixed weights and feature_cols."""
    model = torch.nn.Linear(_N_FEATURES, 1)
    with torch.no_grad():
        model.weight.fill_(0.1)
        model.bias.fill_(0.0)
    model_path = str(tmp_path / "dnn_v1.pt")
    cols_path = str(tmp_path / "feature_cols.joblib")
    torch.save(model, model_path)
    joblib.dump(_FEATURE_COLS, cols_path)
    return model_path, cols_path


@pytest.fixture()
def dnn_predictor(dnn_model: tuple[str, str]) -> DnnPredictor:
    """DnnPredictor in single-snapshot mode (temporal=False)."""
    model_path, cols_path = dnn_model
    return DnnPredictor(model_path=model_path, feature_cols_path=cols_path, temporal=False)


@pytest.fixture()
def strategy() -> TradingStrategy:
    """Strategy with a single entry at 5% elapsed, 1 consecutive, no min confidence."""
    return TradingStrategy(
        name="DNN",
        entry_points=((0.05, 1),),
        min_confidence=0.0,
        min_btc_move=0.0,
        noise_entry_elapsed=1.0,
    )


def _make_snapshot(candle_id: str = "c1", elapsed: float = 0.06) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        candle_id=candle_id,
        timestamp=time.time(),
        elapsed_pct=elapsed,
        btc_price=70000.0,
        btc_bid=69999.0,
        btc_ask=70001.0,
        up_bids=[(0.58, 100)],
        up_asks=[(0.60, 100)],
        down_bids=[(0.38, 100)],
        down_asks=[(0.40, 100)],
        market_volume=50.0,
    )


def _make_runner(predictor, strat) -> ModelRunner:
    return ModelRunner(
        name="DNN",
        predictor=predictor,
        portfolio=PortfolioService(initial_cash=1000.0),
        strategy=strat,
        bet_store=AsyncMock(),
        broadcaster=AsyncMock(),
    )


# -- tests -----------------------------------------------------------


class TestDnnModelRunnerSnapshot:
    @pytest.mark.asyncio
    async def test_predict_triggers_entry(self, dnn_predictor, strategy):
        """DnnPredictor returns P(UP) > 0.5, so runner places an UP entry."""
        runner = _make_runner(dnn_predictor, strategy)
        row = {col: 1.0 for col in _FEATURE_COLS}
        await runner.handle_snapshot(row, _make_snapshot())
        assert runner._entries_made == 1
        assert runner._first_direction == "UP"

    @pytest.mark.asyncio
    async def test_broadcast_contains_model_name(self, dnn_predictor, strategy):
        """Broadcast message includes the DNN model name."""
        runner = _make_runner(dnn_predictor, strategy)
        row = {col: 1.0 for col in _FEATURE_COLS}
        await runner.handle_snapshot(row, _make_snapshot())
        msg = runner._broadcaster.broadcast_json.call_args[0][0]
        assert msg["type"] == "model_entry"
        assert msg["model"] == "DNN"


class TestDnnModelRunnerCandleClose:
    @pytest.mark.asyncio
    async def test_settlement_computes_pnl(self, dnn_predictor, strategy):
        """After entry + candle close, portfolio settles and PnL is recorded."""
        runner = _make_runner(dnn_predictor, strategy)
        row = {col: 1.0 for col in _FEATURE_COLS}
        await runner.handle_snapshot(row, _make_snapshot())
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

        saved = runner._bet_store.save_bet.call_args[0][0]
        assert saved.won is True
        assert saved.pnl > 0
        assert runner._entries_made == 0  # state reset


class TestAgentServiceWithDnn:
    @pytest.mark.asyncio
    async def test_fanout_includes_dnn_runner(self, dnn_predictor, strategy):
        """AgentService fans snapshot to DNN runner alongside a mocked runner."""
        dnn_runner = _make_runner(dnn_predictor, strategy)
        mock_runner = MagicMock()
        mock_runner.name = "RF"
        mock_runner.handle_snapshot = AsyncMock()
        mock_runner.handle_candle_close = AsyncMock()

        indicators = MagicMock()
        indicators.prior_candles = []
        indicators.on_candle_close = AsyncMock()
        indicators.on_snapshot.return_value = {col: 1.0 for col in _FEATURE_COLS}

        agent = AgentService(indicators=indicators, runners=[dnn_runner, mock_runner])
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

        assert dnn_runner._entries_made == 1
        mock_runner.handle_snapshot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broadcast_messages_include_dnn(self, dnn_predictor, strategy):
        """Broadcast from DNN runner carries model='DNN'."""
        broadcaster = AsyncMock()
        runner = ModelRunner(
            name="DNN",
            predictor=dnn_predictor,
            portfolio=PortfolioService(initial_cash=1000.0),
            strategy=strategy,
            bet_store=AsyncMock(),
            broadcaster=broadcaster,
        )
        indicators = MagicMock()
        indicators.prior_candles = []
        indicators.on_candle_close = AsyncMock()
        indicators.on_snapshot.return_value = {col: 1.0 for col in _FEATURE_COLS}

        agent = AgentService(indicators=indicators, runners=[runner])
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

        entry_msgs = [
            c[0][0] for c in broadcaster.broadcast_json.call_args_list if c[0][0].get("type") == "model_entry"
        ]
        assert len(entry_msgs) == 1
        assert entry_msgs[0]["model"] == "DNN"
