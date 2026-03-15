"""Tests for DashboardMessageBuilder — WS message construction."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from polybot.dashboard.message_builder import DashboardMessageBuilder


class TestDashboardMessageBuilder:
    def setup_method(self):
        self.builder = DashboardMessageBuilder()

    def test_build_trade_event(self):
        trade = MagicMock()
        trade.timestamp = 1709000000.0
        trade.action.value = "BUY"
        trade.token_side.value = "up"
        trade.decision_size = 10.0
        trade.fill_price = 0.45
        trade.confidence = 0.72
        trade.reasoning = "Strong momentum"
        trade.candle_slug = "btc-updown-5m-123"
        trade.risk_blocked = False
        trade.cash = 990.0
        trade.portfolio_value = 1000.0
        trade.fee_amount = 0.09
        trade.ai_cost = 0.003
        trade.extra = {}

        msg = self.builder.build_trade_event(trade)
        parsed = json.loads(msg)
        assert parsed["type"] == "trade"
        assert parsed["data"]["action"] == "BUY"
        assert parsed["data"]["token_side"] == "up"
        assert parsed["data"]["fill_price"] == 0.45
        assert parsed["data"]["confidence"] == 0.72

    def test_build_resolution_event(self):
        resolution = MagicMock()
        resolution.slug = "btc-updown-5m-123"
        resolution.winner = "up"
        resolution.btc_open = 85000.0
        resolution.btc_close = 85100.0
        resolution.total_pnl = 5.50

        msg = self.builder.build_resolution_event(resolution)
        parsed = json.loads(msg)
        assert parsed["type"] == "resolution"
        assert parsed["data"]["winner"] == "up"
        assert parsed["data"]["btc_move"] == pytest.approx(100.0)
        assert parsed["data"]["pnl"] == 5.50

    def test_build_market_update(self):
        ctx = MagicMock()
        ctx.current_market = MagicMock()
        ctx.current_market.time_remaining.return_value = 120.0
        ctx.current_market.slug = "btc-updown-5m-123"

        snapshot = MagicMock()
        snapshot.orderbook.midpoint = 0.45
        snapshot.down_orderbook.midpoint = 0.55
        snapshot.btc_price.price_usd = 85000.0
        snapshot.btc_price.chainlink_price = 85001.0
        snapshot.btc_price.price_source = "binance"
        ctx.shared.latest_snapshot = snapshot

        msg = self.builder.build_market_update(ctx)
        parsed = json.loads(msg)
        assert parsed["type"] == "market"
        assert parsed["data"]["time_remaining"] == 120.0
        assert parsed["data"]["btc_price"] == 85000.0

    def test_build_position_update(self):
        ctx = MagicMock()
        ctx.portfolio.up_position.shares = 10.0
        ctx.portfolio.up_position.avg_entry_price = 0.45
        ctx.portfolio.down_position.shares = 0.0
        ctx.portfolio.down_position.avg_entry_price = 0.0
        ctx.portfolio.cash = 955.0
        ctx.shared.position_pnl_pct = {"up": 0.05}
        ctx.shared.dynamic_sl = {"up": -0.25}
        ctx.shared.dynamic_tp = {"up": 0.50}

        msg = self.builder.build_position_update(ctx)
        parsed = json.loads(msg)
        assert parsed["type"] == "position"
        assert parsed["data"]["up_shares"] == 10.0
        assert parsed["data"]["cash"] == 955.0

    def test_build_status_update(self):
        ctx = MagicMock()
        ctx.shared.prefilter_history = [1] * 50
        ctx.config.monitor.ai_cooldown_seconds = 60.0
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.ai_trigger_reason = "R/R threshold"
        ctx.shared.monitor_status = {"gate": "open"}
        ctx.risk.state.daily_pnl = -5.0
        ctx.risk.state.daily_trades = 3
        ctx.risk.state.daily_fees = 0.30
        ctx.risk.state.max_drawdown = -8.0
        ctx.risk.state.is_halted = False
        ctx.shared.api_latencies = {"clob": 150}
        ctx.shared.sqlite_queue_depth = 0
        ctx.prefilter.skip_rate = 0.65
        ctx.prefilter.total_skipped = 65
        ctx.prefilter.total_checks = 100

        msg = self.builder.build_status_update(ctx, ws_client_count=3)
        parsed = json.loads(msg)
        assert parsed["type"] == "status"
        assert parsed["data"]["risk"]["daily_pnl"] == -5.0
        assert parsed["data"]["api_latencies"]["clob"] == 150
        assert parsed["data"]["ws_clients"] == 3

    def test_build_status_update_default_client_count(self):
        ctx = MagicMock()
        ctx.shared.prefilter_history = []
        ctx.config.monitor.ai_cooldown_seconds = 60.0
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.ai_trigger_reason = None
        ctx.shared.monitor_status = {}
        ctx.risk.state.daily_pnl = 0.0
        ctx.risk.state.daily_trades = 0
        ctx.risk.state.daily_fees = 0.0
        ctx.risk.state.max_drawdown = 0.0
        ctx.risk.state.is_halted = False
        ctx.shared.api_latencies = {}
        ctx.shared.sqlite_queue_depth = 0
        ctx.prefilter.skip_rate = 0.0
        ctx.prefilter.total_skipped = 0
        ctx.prefilter.total_checks = 0

        msg = self.builder.build_status_update(ctx)
        parsed = json.loads(msg)
        assert parsed["data"]["ws_clients"] == 0

    def test_build_status_update_with_ai_decision(self):
        ctx = MagicMock()
        ctx.shared.prefilter_history = []
        ctx.config.monitor.ai_cooldown_seconds = 60.0
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.ai_trigger_reason = None
        ctx.shared.monitor_status = {}
        ctx.risk.state.daily_pnl = 0.0
        ctx.risk.state.daily_trades = 0
        ctx.risk.state.daily_fees = 0.0
        ctx.risk.state.max_drawdown = 0.0
        ctx.risk.state.is_halted = False
        ctx.shared.api_latencies = {}
        ctx.shared.sqlite_queue_depth = 0
        ctx.prefilter.skip_rate = 0.0
        ctx.prefilter.total_skipped = 0
        ctx.prefilter.total_checks = 0

        ai_decision = MagicMock()
        ai_decision._screen_calls = 10
        ai_decision._screen_passes = 5

        msg = self.builder.build_status_update(ctx, ai_decision=ai_decision)
        parsed = json.loads(msg)
        assert parsed["data"]["ensemble"]["screen_calls"] == 10
        assert parsed["data"]["ensemble"]["screen_passes"] == 5
