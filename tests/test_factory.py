"""Tests for ContextFactory — builds AgentContext from AppConfig."""

from __future__ import annotations

from unittest.mock import patch

from polybot.agent.context import AgentContext
from polybot.agent.helpers import StartupData
from polybot.config import AppConfig

# All classes constructed inside ContextFactory.build()
_FACTORY_MODULE = "polybot.agent.factory"
_PATCHES = [
    f"{_FACTORY_MODULE}.MarketDiscovery",
    f"{_FACTORY_MODULE}.MarketDataProvider",
    f"{_FACTORY_MODULE}.DecisionEngine",
    f"{_FACTORY_MODULE}.ExecutionSimulator",
    f"{_FACTORY_MODULE}.SimulatedOrderBook",
    f"{_FACTORY_MODULE}.Portfolio",
    f"{_FACTORY_MODULE}.RiskManager",
    f"{_FACTORY_MODULE}.TradeLog",
    f"{_FACTORY_MODULE}.ResolutionTracker",
    f"{_FACTORY_MODULE}.MarketDataResolutionRepo",
    f"{_FACTORY_MODULE}.PreFilter",
    f"{_FACTORY_MODULE}.ConfidenceCalibrator",
    f"{_FACTORY_MODULE}.ExitTracker",
    f"{_FACTORY_MODULE}.AdaptiveEntryTracker",
    f"{_FACTORY_MODULE}.MLScorer",
    f"{_FACTORY_MODULE}.KnowledgeManager",
    f"{_FACTORY_MODULE}.FeatureConfig",
    f"{_FACTORY_MODULE}.DashboardBroadcaster",
    f"{_FACTORY_MODULE}.DataStore",
    f"{_FACTORY_MODULE}.MarketHistoryStore",
    f"{_FACTORY_MODULE}.SharedState",
]


def _apply_patches():
    """Start all patches and return (mocks_dict, patcher_list)."""
    mocks = {}
    patchers = []
    for target in _PATCHES:
        p = patch(target)
        mock = p.start()
        name = target.rsplit(".", 1)[-1]
        mocks[name] = mock
        patchers.append(p)
    return mocks, patchers


class TestContextFactory:
    """Smoke tests for ContextFactory.build()."""

    def test_build_returns_agent_context(self):
        from polybot.agent.factory import ContextFactory

        mocks, patchers = _apply_patches()
        try:
            config = AppConfig()
            factory = ContextFactory(config)
            ctx = factory.build()

            assert isinstance(ctx, AgentContext)
        finally:
            for p in patchers:
                p.stop()

    def test_build_populates_core_fields(self):
        from polybot.agent.factory import ContextFactory

        mocks, patchers = _apply_patches()
        try:
            config = AppConfig()
            factory = ContextFactory(config)
            ctx = factory.build()

            assert ctx.config is config
            assert ctx.discovery is mocks["MarketDiscovery"].return_value
            assert ctx.market_data is mocks["MarketDataProvider"].return_value
            assert ctx.decision_engine is mocks["DecisionEngine"].return_value
            assert ctx.execution_sim is mocks["ExecutionSimulator"].return_value
            assert ctx.orderbook is mocks["SimulatedOrderBook"].return_value
            assert ctx.portfolio is mocks["Portfolio"].return_value
            assert ctx.risk is mocks["RiskManager"].return_value
            assert ctx.trade_log is mocks["TradeLog"].return_value
            assert ctx.resolution_tracker is mocks["ResolutionTracker"].return_value
            assert ctx.prefilter is mocks["PreFilter"].return_value
            assert ctx.calibrator is mocks["ConfidenceCalibrator"].return_value
            assert ctx.exit_tracker is mocks["ExitTracker"].return_value
            assert ctx.adaptive_entry is mocks["AdaptiveEntryTracker"].return_value
            assert ctx.ml_scorer is mocks["MLScorer"].return_value
            assert ctx.knowledge_manager is mocks["KnowledgeManager"].return_value
            assert ctx.feature_config is mocks["FeatureConfig"].return_value
            assert ctx.shared is mocks["SharedState"].return_value
            assert ctx.ws_broadcaster is mocks["DashboardBroadcaster"].return_value
            assert ctx.market_history is mocks["MarketHistoryStore"].return_value
        finally:
            for p in patchers:
                p.stop()

    def test_build_populates_startup_data(self):
        from polybot.agent.factory import ContextFactory

        mocks, patchers = _apply_patches()
        try:
            config = AppConfig()
            sd = StartupData(
                resolutions_since_reflection=5,
                knowledge_state={"key": "val"},
                historical_resolutions=[{"slug": "a"}],
                historical_trades=[{"action": "BUY"}],
                iteration_summaries=[{"iter": 1}],
                iteration_label="iter_003",
            )
            factory = ContextFactory(config, sd)
            ctx = factory.build()

            assert ctx.resolutions_since_reflection == 5
            assert ctx.historical_resolutions == [{"slug": "a"}]
            assert ctx.historical_trades == [{"action": "BUY"}]
            assert ctx.iteration_summaries == [{"iter": 1}]
            # Knowledge state loaded
            mocks["KnowledgeManager"].return_value.load_state.assert_called_once_with({"key": "val"})
            # Iteration label used for MarketHistoryStore
            mocks["MarketHistoryStore"].assert_called_once()
            call_kwargs = mocks["MarketHistoryStore"].call_args
            assert call_kwargs[1].get("iteration") == "iter_003" or call_kwargs[0][1] == "iter_003"
        finally:
            for p in patchers:
                p.stop()

    def test_build_sim_mode_no_live_engine(self):
        from polybot.agent.factory import ContextFactory

        mocks, patchers = _apply_patches()
        try:
            config = AppConfig()  # default mode is not "live"
            ctx = ContextFactory(config, StartupData()).build()

            assert ctx.live_mode is False
            assert ctx.live_engine is None
            assert ctx.shadow_portfolio is None
        finally:
            for p in patchers:
                p.stop()

    def test_build_live_mode_creates_live_engine(self):
        from polybot.agent.factory import ContextFactory

        mocks, patchers = _apply_patches()
        live_engine_patch = patch(f"{_FACTORY_MODULE}.LiveExecutionEngine")
        mock_live = live_engine_patch.start()
        patchers.append(live_engine_patch)
        try:
            config = AppConfig(trading={"mode": "live"})
            ctx = ContextFactory(config, StartupData()).build()

            assert ctx.live_mode is True
            assert ctx.live_engine is mock_live.return_value
            assert ctx.shadow_portfolio is not None
        finally:
            for p in patchers:
                p.stop()

    def test_build_sqlite_disabled_no_datastore(self):
        from polybot.agent.factory import ContextFactory

        mocks, patchers = _apply_patches()
        try:
            config = AppConfig(logging={"sqlite_enabled": False})
            ctx = ContextFactory(config, StartupData()).build()

            assert ctx.datastore is None
            mocks["DataStore"].assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    def test_build_sqlite_enabled_creates_datastore(self):
        from polybot.agent.factory import ContextFactory

        mocks, patchers = _apply_patches()
        try:
            config = AppConfig(logging={"sqlite_enabled": True})
            ctx = ContextFactory(config, StartupData()).build()

            assert ctx.datastore is mocks["DataStore"].return_value
        finally:
            for p in patchers:
                p.stop()

    def test_import_from_package(self):
        from polybot.agent import ContextFactory

        assert ContextFactory.__name__ == "ContextFactory"
