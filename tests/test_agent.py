"""Tests for agent package structure and extracted modules."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestAgentPackageImports:
    """Smoke tests ensuring backward-compatible imports after agent/ refactor."""

    def test_import_trading_agent_from_package(self):
        from polybot.agent import TradingAgent

        assert TradingAgent.__name__ == "TradingAgent"

    def test_import_trading_agent_from_core(self):
        from polybot.agent.core import TradingAgent

        assert TradingAgent.__name__ == "TradingAgent"

    def test_import_agent_context(self):
        from polybot.agent import AgentContext

        assert AgentContext.__name__ == "AgentContext"

    def test_import_agent_context_from_context(self):
        from polybot.agent.context import AgentContext

        assert AgentContext.__name__ == "AgentContext"

    def test_agent_context_is_dataclass(self):
        import dataclasses

        from polybot.agent.context import AgentContext

        assert dataclasses.is_dataclass(AgentContext)


class TestComputePnlFromTrades:
    """Tests for compute_pnl_from_trades helper."""

    def test_up_winner_with_up_buy(self):
        from polybot.agent.helpers import compute_pnl_from_trades

        trades = [{"action": "BUY", "fill_price": 0.40, "fill_size": 10, "token_side": "up"}]
        pnl = compute_pnl_from_trades(trades, "up")
        # 10 shares * $1 - 10 * 0.40 = $6.00
        assert pnl == pytest.approx(6.0)

    def test_down_winner_with_up_buy(self):
        from polybot.agent.helpers import compute_pnl_from_trades

        trades = [{"action": "BUY", "fill_price": 0.40, "fill_size": 10, "token_side": "up"}]
        pnl = compute_pnl_from_trades(trades, "down")
        # 0 - 10 * 0.40 = -$4.00
        assert pnl == pytest.approx(-4.0)

    def test_skips_risk_blocked(self):
        from polybot.agent.helpers import compute_pnl_from_trades

        trades = [
            {"action": "BUY", "fill_price": 0.40, "fill_size": 10, "token_side": "up", "risk_blocked": True},
        ]
        pnl = compute_pnl_from_trades(trades, "up")
        assert pnl == pytest.approx(0.0)

    def test_skips_no_fill_price(self):
        from polybot.agent.helpers import compute_pnl_from_trades

        trades = [{"action": "BUY", "fill_size": 10, "token_side": "up"}]
        pnl = compute_pnl_from_trades(trades, "up")
        assert pnl == pytest.approx(0.0)

    def test_sell_reduces_position(self):
        from polybot.agent.helpers import compute_pnl_from_trades

        trades = [
            {"action": "BUY", "fill_price": 0.40, "fill_size": 10, "token_side": "up"},
            {"action": "SELL", "fill_price": 0.60, "fill_size": 5, "token_side": "up"},
        ]
        pnl = compute_pnl_from_trades(trades, "up")
        # up: (10-5) shares * 1 - (10*0.4 - 5*0.6) = 5 - 1.0 = 4.0
        assert pnl == pytest.approx(4.0)

    def test_down_buy_down_winner(self):
        from polybot.agent.helpers import compute_pnl_from_trades

        trades = [{"action": "BUY", "fill_price": 0.30, "fill_size": 10, "token_side": "down"}]
        pnl = compute_pnl_from_trades(trades, "down")
        # 10 * 1 - 10 * 0.30 = $7.00
        assert pnl == pytest.approx(7.0)

    def test_empty_trades(self):
        from polybot.agent.helpers import compute_pnl_from_trades

        assert compute_pnl_from_trades([], "up") == pytest.approx(0.0)


class TestEnrichIterationSummary:
    """Tests for enrich_iteration_summary."""

    def test_enriches_calibration(self):
        from polybot.agent.dashboard import enrich_iteration_summary

        summary: dict = {}
        dd = {
            "calibration": {"total_records": 10, "shadow_accuracy": 0.8, "shadow_total": 5, "bins": []},
            "exit_analysis": {},
            "ml_model": {},
        }
        enrich_iteration_summary(summary, dd)
        assert summary["calibration"]["total_records"] == 10
        assert summary["calibration"]["shadow_accuracy"] == 0.8

    def test_enriches_trade_analysis(self):
        from polybot.agent.dashboard import enrich_iteration_summary

        summary: dict = {}
        dd = {
            "calibration": {},
            "exit_analysis": {},
            "ml_model": {},
            "trades": [
                {"action": "BUY", "fill_price": 0.35, "confidence": 0.8},
                {"action": "BUY", "fill_price": 0.55, "confidence": 0.7},
                {"action": "HOLD"},
            ],
            "resolutions": [],
        }
        enrich_iteration_summary(summary, dd)
        assert summary["trade_analysis"]["total_buys"] == 2
        assert summary["trade_analysis"]["total_holds"] == 1
        assert summary["trade_analysis"]["cheap_entries"] == 1

    def test_enriches_resolution_analysis(self):
        from polybot.agent.dashboard import enrich_iteration_summary

        summary: dict = {}
        dd = {
            "calibration": {},
            "exit_analysis": {},
            "ml_model": {},
            "trades": [],
            "resolutions": [
                {"slug": "a", "btc_move": 100.0, "pnl": 5.0},
                {"slug": "b", "btc_move": -50.0, "pnl": -2.0},
            ],
        }
        enrich_iteration_summary(summary, dd)
        assert summary["resolution_analysis"]["total"] == 2
        assert summary["resolution_analysis"]["biggest_win"] == 5.0
        assert summary["resolution_analysis"]["biggest_loss"] == -2.0

    def test_import_from_package(self):
        from polybot.agent import enrich_iteration_summary

        assert callable(enrich_iteration_summary)

    def test_compute_market_trend_no_data(self):
        from polybot.agent.dashboard import DashboardAssembler

        assert DashboardAssembler.compute_market_trend(None) == {}


class TestStatePersistence:
    """Tests for StatePersistence load/save."""

    def test_compute_iteration_label_no_archive(self, tmp_path, monkeypatch):
        from polybot.agent.state import StatePersistence

        monkeypatch.chdir(tmp_path)
        assert StatePersistence.compute_iteration_label() == "iter_001"

    def test_compute_iteration_label_with_existing(self, tmp_path, monkeypatch):
        from polybot.agent.state import StatePersistence

        monkeypatch.chdir(tmp_path)
        archive = tmp_path / "archive"
        (archive / "iter_001").mkdir(parents=True)
        (archive / "iter_002").mkdir(parents=True)
        assert StatePersistence.compute_iteration_label() == "iter_003"

    def test_load_agent_state_fresh(self, tmp_path):
        from polybot.agent.state import StatePersistence

        sp = StatePersistence()
        ctx = MagicMock()
        # state file doesn't exist — fresh start
        ctx.state_path = tmp_path / "agent_state.json"
        ctx.config.logging.log_dir = str(tmp_path)
        ctx.historical_resolutions = []
        ctx.historical_trades = []

        sp.load_agent_state(ctx)
        assert ctx.historical_resolutions == []
        assert ctx.historical_trades == []

    def test_load_agent_state_from_file(self, tmp_path):
        from polybot.agent.state import StatePersistence

        state_file = tmp_path / "agent_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "resolutions_since_reflection": 7,
                    "knowledge": {"some": "data"},
                }
            )
        )

        sp = StatePersistence()
        ctx = MagicMock()
        ctx.state_path = state_file
        ctx.config.logging.log_dir = str(tmp_path)
        ctx.historical_resolutions = []
        ctx.historical_trades = []

        sp.load_agent_state(ctx)
        assert ctx.resolutions_since_reflection == 7
        ctx.knowledge_manager.load_state.assert_called_once_with({"some": "data"})

    def test_save_agent_state(self, tmp_path):
        from polybot.agent.state import StatePersistence

        sp = StatePersistence()
        ctx = MagicMock()
        ctx.state_path = tmp_path / "agent_state.json"
        ctx.bot_version = "0.1.0"
        ctx.resolutions_since_reflection = 3
        ctx.knowledge_manager.save_state.return_value = {"key": "val"}

        sp.save_agent_state(ctx)

        data = json.loads(ctx.state_path.read_text())
        assert data["bot_version"] == "0.1.0"
        assert data["resolutions_since_reflection"] == 3
        assert data["knowledge"] == {"key": "val"}

    def test_load_history_from_logs(self, tmp_path):
        from polybot.agent.state import StatePersistence

        # Write a resolution log
        res_file = tmp_path / "resolutions_2024.jsonl"
        res_file.write_text(
            json.dumps(
                {
                    "timestamp": 1709000000.0,
                    "slug": "btc-5m-123",
                    "winner": "up",
                    "btc_open": 65000.0,
                    "btc_close": 65100.0,
                    "total_pnl": 2.5,
                }
            )
            + "\n"
        )

        # Write a trades log
        trade_file = tmp_path / "trades_2024.jsonl"
        trade_file.write_text(
            json.dumps(
                {
                    "timestamp": 1709000010.0,
                    "cycle_number": 1,
                    "action": "BUY",
                    "token_side": "up",
                    "decision_size": 10,
                    "fill_price": 0.45,
                    "confidence": 0.7,
                    "reasoning": "test",
                    "market_view": "bull",
                    "candle_slug": "btc-5m-123",
                    "risk_blocked": False,
                    "risk_block_reason": "",
                    "cash": 990,
                    "portfolio_value": 1000,
                    "fee_amount": 0.01,
                    "realized_pnl": 0,
                    "unrealized_pnl": 0,
                    "ai_cost": 0.005,
                    "extra": {},
                }
            )
            + "\n"
        )

        sp = StatePersistence()
        ctx = MagicMock()
        ctx.config.logging.log_dir = str(tmp_path)
        ctx.historical_resolutions = []
        ctx.historical_trades = []

        sp.load_history_from_logs(ctx)
        assert len(ctx.historical_resolutions) == 1
        assert ctx.historical_resolutions[0]["slug"] == "btc-5m-123"
        assert ctx.historical_resolutions[0]["pnl"] == 2.5
        assert len(ctx.historical_trades) == 1
        assert ctx.historical_trades[0]["action"] == "BUY"


class TestRotationManager:
    """Tests for RotationManager."""

    def test_import_from_package(self):
        from polybot.agent.rotation import RotationManager

        assert RotationManager.__name__ == "RotationManager"

    def test_save_candle_microstructure_skips_short_history(self):
        from polybot.agent.rotation import RotationManager

        rm = RotationManager()
        ctx = MagicMock()
        ctx.shared.prefilter_history = [MagicMock() for _ in range(5)]  # < 10
        rm.save_candle_microstructure(ctx)
        # Should not append anything
        ctx.shared.microstructure_history.append.assert_not_called()

    def test_save_candle_microstructure_computes_summary(self):
        from polybot.agent.rotation import RotationManager

        rm = RotationManager()
        ctx = MagicMock()

        # Create 15 prefilter snapshots
        snapshots = []
        for i in range(15):
            s = MagicMock()
            s.up_spread_pct = 0.02
            s.down_spread_pct = 0.03
            s.btc_move_from_open = float(i)
            snapshots.append(s)
        ctx.shared.prefilter_history = snapshots
        ctx.shared.microstructure_history = []

        rm.save_candle_microstructure(ctx)
        assert len(ctx.shared.microstructure_history) == 1
        summary = ctx.shared.microstructure_history[0]
        assert summary.avg_spread_up == pytest.approx(0.02)
        assert summary.avg_spread_down == pytest.approx(0.03)
        assert summary.btc_range == pytest.approx(14.0)
        assert summary.btc_final_move == pytest.approx(14.0)

    @pytest.mark.asyncio
    async def test_discover_market_increments_failures(self):
        from polybot.agent.rotation import RotationManager

        rm = RotationManager()
        ctx = MagicMock()
        ctx.discovery.get_current_market = AsyncMock(return_value=None)
        ctx.discovery.get_next_market = AsyncMock(return_value=None)
        ctx.discovery_failures = 0
        ctx.outage_start = None
        ctx.current_market = None

        result = await rm.discover_market(ctx)
        assert ctx.discovery_failures == 1
        assert result is None

    @pytest.mark.asyncio
    async def test_discover_market_outage_detection(self):
        from polybot.agent.rotation import RotationManager

        rm = RotationManager()
        ctx = MagicMock()
        ctx.discovery.get_current_market = AsyncMock(return_value=None)
        ctx.discovery.get_next_market = AsyncMock(return_value=None)
        ctx.discovery_failures = 2  # already at 2
        ctx.outage_start = None
        ctx.current_market = None

        await rm.discover_market(ctx)
        assert ctx.discovery_failures == 3
        assert ctx.outage_start is not None  # outage detected at threshold
