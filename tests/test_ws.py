"""Tests for the WebSocket server and broadcaster."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.ws.broadcaster import Broadcaster
from polybot.ws.constants import (
    DEFAULT_WS_HOST,
    DEFAULT_WS_PORT,
    PING_INTERVAL_SECONDS,
    PING_TIMEOUT_SECONDS,
)
from polybot.ws.protocol import (
    ALL_TYPES,
    MSG_MARKET,
    MSG_POSITION,
    MSG_RESOLUTION,
    MSG_SNAPSHOT,
    MSG_STATUS,
    MSG_TRADE,
    make_message,
)
from polybot.ws.server import DashboardWSServer

# --- Constants tests ---


class TestConstants:
    def test_default_host(self):
        assert DEFAULT_WS_HOST == "0.0.0.0"

    def test_default_port(self):
        assert DEFAULT_WS_PORT == 8765

    def test_ping_interval(self):
        assert PING_INTERVAL_SECONDS == 20

    def test_ping_timeout(self):
        assert PING_TIMEOUT_SECONDS == 20

    def test_all_types_frozenset(self):
        assert len(ALL_TYPES) == 6
        assert MSG_SNAPSHOT in ALL_TYPES


# --- Injectable logger tests ---


class TestInjectableLoggers:
    def test_broadcaster_default_logger(self):
        b = Broadcaster()
        assert b._logger.name == "polybot.ws.broadcaster"

    def test_broadcaster_custom_logger(self):
        custom = logging.getLogger("test.broadcaster")
        b = Broadcaster(logger=custom)
        assert b._logger is custom

    def test_server_uses_provided_logger(self):
        custom = logging.getLogger("test.server")
        b = Broadcaster()
        s = DashboardWSServer(b, ctx=MagicMock(), logger=custom)
        assert s._logger is custom


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
        b = Broadcaster()
        mock_ws = MagicMock()
        b.add_client(mock_ws)
        assert b.client_count == 1
        assert b.has_clients is True
        b.remove_client(mock_ws)
        assert b.client_count == 0
        assert b.has_clients is False

    def test_remove_nonexistent_client(self):
        b = Broadcaster()
        mock_ws = MagicMock()
        b.remove_client(mock_ws)  # should not raise
        assert b.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        b = Broadcaster()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        b.add_client(ws1)
        b.add_client(ws2)
        await b.broadcast("test message")
        ws1.send.assert_called_once_with("test message")
        ws2.send.assert_called_once_with("test message")

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_clients(self):
        b = Broadcaster()
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
        b = Broadcaster()
        await b.broadcast("test")  # should not raise


# --- Server tests ---


class TestServer:
    @pytest.mark.asyncio
    async def test_server_starts_and_stops(self):
        broadcaster = Broadcaster()
        server = DashboardWSServer(broadcaster, ctx=MagicMock(), logger=logging.getLogger("test"), port=0)
        await server.start()
        assert server._server is not None
        await server.stop()

    @pytest.mark.asyncio
    async def test_server_accepts_connection(self):
        import websockets

        broadcaster = Broadcaster()
        server = DashboardWSServer(broadcaster, ctx=MagicMock(), logger=logging.getLogger("test"), port=18765)

        # Override snapshot builder to return test data (no real ctx needed)
        server._build_initial_snapshot = lambda: make_message("snapshot", {"test": True})

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

        broadcaster = Broadcaster()
        server = DashboardWSServer(broadcaster, ctx=MagicMock(), logger=logging.getLogger("test"), port=18766)

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


# --- Re-export tests ---


class TestReExports:
    def test_broadcaster_reexported(self):
        from polybot.ws import Broadcaster

        assert Broadcaster is not None

    def test_server_reexported(self):
        from polybot.ws import DashboardWSServer

        assert DashboardWSServer is not None

    def test_make_message_reexported(self):
        from polybot.ws import make_message

        assert callable(make_message)

    def test_constants_reexported(self):
        from polybot.ws import DEFAULT_WS_HOST, DEFAULT_WS_PORT

        assert DEFAULT_WS_HOST == "0.0.0.0"
        assert DEFAULT_WS_PORT == 8765
