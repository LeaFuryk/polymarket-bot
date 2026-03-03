"""Tests for the WebSocket dashboard server."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polybot.ws.protocol import (
    MSG_MARKET,
    MSG_POSITION,
    MSG_RESOLUTION,
    MSG_SNAPSHOT,
    MSG_STATUS,
    MSG_TRADE,
    make_message,
)
from polybot.ws.broadcaster import DashboardBroadcaster
from polybot.ws.server import DashboardWSServer


# --- Protocol tests ---


class TestProtocol:
    def test_make_message_structure(self):
        msg = make_message("snapshot", {"key": "value"})
        parsed = json.loads(msg)
        assert parsed["type"] == "snapshot"
        assert parsed["data"] == {"key": "value"}

    def test_make_message_all_types(self):
        for msg_type in (MSG_SNAPSHOT, MSG_TRADE, MSG_RESOLUTION, MSG_MARKET, MSG_POSITION, MSG_STATUS):
            msg = make_message(msg_type, {})
            parsed = json.loads(msg)
            assert parsed["type"] == msg_type

    def test_make_message_complex_data(self):
        data = {"nested": {"list": [1, 2, 3]}, "float": 1.5, "null": None}
        msg = make_message("snapshot", data)
        parsed = json.loads(msg)
        assert parsed["data"]["nested"]["list"] == [1, 2, 3]
        assert parsed["data"]["float"] == 1.5
        assert parsed["data"]["null"] is None


# --- Broadcaster tests ---


class TestBroadcaster:
    def test_add_remove_client(self):
        b = DashboardBroadcaster()
        mock_ws = MagicMock()
        b.add_client(mock_ws)
        assert b.client_count == 1
        assert b.has_clients is True
        b.remove_client(mock_ws)
        assert b.client_count == 0
        assert b.has_clients is False

    def test_remove_nonexistent_client(self):
        b = DashboardBroadcaster()
        mock_ws = MagicMock()
        b.remove_client(mock_ws)  # should not raise
        assert b.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        b = DashboardBroadcaster()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        b.add_client(ws1)
        b.add_client(ws2)
        await b.broadcast("test message")
        ws1.send.assert_called_once_with("test message")
        ws2.send.assert_called_once_with("test message")

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_clients(self):
        b = DashboardBroadcaster()
        alive = AsyncMock()
        dead = AsyncMock()
        dead.send.side_effect = ConnectionError("gone")
        b.add_client(alive)
        b.add_client(dead)
        assert b.client_count == 2
        await b.broadcast("test")
        assert b.client_count == 1
        alive.send.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self):
        b = DashboardBroadcaster()
        await b.broadcast("test")  # should not raise

    def test_build_trade_event(self):
        b = DashboardBroadcaster()
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

        msg = b.build_trade_event(trade)
        parsed = json.loads(msg)
        assert parsed["type"] == "trade"
        assert parsed["data"]["action"] == "BUY"
        assert parsed["data"]["token_side"] == "up"
        assert parsed["data"]["fill_price"] == 0.45
        assert parsed["data"]["confidence"] == 0.72

    def test_build_resolution_event(self):
        b = DashboardBroadcaster()
        resolution = MagicMock()
        resolution.slug = "btc-updown-5m-123"
        resolution.winner = "up"
        resolution.btc_open = 85000.0
        resolution.btc_close = 85100.0
        resolution.total_pnl = 5.50

        msg = b.build_resolution_event(resolution)
        parsed = json.loads(msg)
        assert parsed["type"] == "resolution"
        assert parsed["data"]["winner"] == "up"
        assert parsed["data"]["btc_move"] == pytest.approx(100.0)
        assert parsed["data"]["pnl"] == 5.50

    def test_build_snapshot_calls_assemble(self):
        b = DashboardBroadcaster()
        agent = MagicMock()
        agent._assemble_dashboard_data.return_value = {"test": True}

        msg = b.build_snapshot(agent)
        parsed = json.loads(msg)
        assert parsed["type"] == "snapshot"
        assert parsed["data"]["test"] is True
        assert "ws_clients" in parsed["data"]
        agent._assemble_dashboard_data.assert_called_once()

    def test_build_market_update(self):
        b = DashboardBroadcaster()
        agent = MagicMock()
        agent._current_market = MagicMock()
        agent._current_market.time_remaining.return_value = 120.0
        agent._current_market.slug = "btc-updown-5m-123"

        snapshot = MagicMock()
        snapshot.orderbook.midpoint = 0.45
        snapshot.down_orderbook.midpoint = 0.55
        snapshot.btc_price.price_usd = 85000.0
        snapshot.btc_price.chainlink_price = 85001.0
        snapshot.btc_price.price_source = "chainlink_ws"
        agent._shared.latest_snapshot = snapshot

        msg = b.build_market_update(agent)
        parsed = json.loads(msg)
        assert parsed["type"] == "market"
        assert parsed["data"]["time_remaining"] == 120.0
        assert parsed["data"]["btc_price"] == 85000.0

    def test_build_position_update(self):
        b = DashboardBroadcaster()
        agent = MagicMock()
        agent._portfolio.up_position.shares = 10.0
        agent._portfolio.up_position.avg_entry_price = 0.45
        agent._portfolio.down_position.shares = 0.0
        agent._portfolio.down_position.avg_entry_price = 0.0
        agent._portfolio.cash = 955.0
        agent._shared.position_pnl_pct = {"up": 0.05}
        agent._shared.dynamic_sl = {"up": -0.25}
        agent._shared.dynamic_tp = {"up": 0.50}

        msg = b.build_position_update(agent)
        parsed = json.loads(msg)
        assert parsed["type"] == "position"
        assert parsed["data"]["up_shares"] == 10.0
        assert parsed["data"]["cash"] == 955.0

    def test_build_status_update(self):
        b = DashboardBroadcaster()
        agent = MagicMock()
        agent._shared.prefilter_history = [1] * 50
        agent._config.monitor.ai_cooldown_seconds = 60.0
        agent._shared.ai_last_call_time = 0.0
        agent._shared.ai_trigger_reason = "R/R threshold"
        agent._shared.monitor_status = {"gate": "open"}
        agent._risk.state.daily_pnl = -5.0
        agent._risk.state.daily_trades = 3
        agent._risk.state.daily_fees = 0.30
        agent._risk.state.max_drawdown = -8.0
        agent._risk.state.is_halted = False
        agent._shared.api_latencies = {"clob": 150}
        agent._shared.sqlite_queue_depth = 0
        agent._prefilter.skip_rate = 0.65
        agent._prefilter.total_skipped = 65
        agent._prefilter.total_checks = 100
        agent._ai_decision = MagicMock()
        agent._ai_decision._screen_calls = 10
        agent._ai_decision._screen_passes = 5

        msg = b.build_status_update(agent)
        parsed = json.loads(msg)
        assert parsed["type"] == "status"
        assert parsed["data"]["risk"]["daily_pnl"] == -5.0
        assert parsed["data"]["api_latencies"]["clob"] == 150


# --- Server tests ---


class TestServer:
    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self):
        broadcaster = DashboardBroadcaster()
        server = DashboardWSServer(broadcaster, port=0)  # port 0 = OS picks
        await server.start()
        assert server._server is not None
        await server.stop()

    @pytest.mark.asyncio
    async def test_server_accepts_connection(self):
        import websockets

        broadcaster = DashboardBroadcaster()
        server = DashboardWSServer(broadcaster, port=18765)

        # Set initial snapshot builder
        server._initial_snapshot_builder = lambda: make_message(
            "snapshot", {"test": True}
        )

        await server.start()
        try:
            async with websockets.connect("ws://localhost:18765") as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                parsed = json.loads(msg)
                assert parsed["type"] == "snapshot"
                assert parsed["data"]["test"] is True
                assert broadcaster.client_count == 1
        finally:
            await server.stop()
        # After disconnect + stop, client should be cleaned up
        assert broadcaster.client_count == 0

    @pytest.mark.asyncio
    async def test_server_broadcasts_to_connected_client(self):
        import websockets

        broadcaster = DashboardBroadcaster()
        server = DashboardWSServer(broadcaster, port=18766)
        server._initial_snapshot_builder = None

        await server.start()
        try:
            async with websockets.connect("ws://localhost:18766") as ws:
                await asyncio.sleep(0.1)  # let handler register client
                await broadcaster.broadcast(make_message("market", {"price": 85000}))
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                parsed = json.loads(msg)
                assert parsed["type"] == "market"
                assert parsed["data"]["price"] == 85000
        finally:
            await server.stop()
