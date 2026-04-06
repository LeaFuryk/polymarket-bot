"""Tests for Broadcaster."""

import json
from unittest.mock import AsyncMock

from polybot.ports.message_relay import MessageRelay
from polybot.ws.broadcaster import Broadcaster


class TestBroadcaster:
    def test_implements_message_relay(self):
        assert isinstance(Broadcaster(), MessageRelay)

    async def test_broadcast_sends_to_client(self):
        bc = Broadcaster()
        ws = AsyncMock()
        bc.add_client(ws)
        await bc.broadcast("hello")
        ws.send.assert_awaited_once_with("hello")

    async def test_broadcast_sends_to_multiple_clients(self):
        bc = Broadcaster()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        bc.add_client(ws1)
        bc.add_client(ws2)
        await bc.broadcast("msg")
        ws1.send.assert_awaited_once_with("msg")
        ws2.send.assert_awaited_once_with("msg")

    async def test_broadcast_removes_dead_client(self):
        import websockets

        bc = Broadcaster()
        ws = AsyncMock()
        ws.send.side_effect = websockets.ConnectionClosed(None, None)
        bc.add_client(ws)
        await bc.broadcast("msg")
        assert bc.client_count == 0

    async def test_broadcast_no_clients_is_safe(self):
        bc = Broadcaster()
        await bc.broadcast("msg")  # no error

    async def test_broadcast_json(self):
        bc = Broadcaster()
        ws = AsyncMock()
        bc.add_client(ws)
        await bc.broadcast_json({"type": "snapshot", "btc_price": 69000.0})
        raw = ws.send.call_args[0][0]
        msg = json.loads(raw)
        assert msg["type"] == "snapshot"

    def test_client_count(self):
        bc = Broadcaster()
        ws = AsyncMock()
        assert bc.client_count == 0
        bc.add_client(ws)
        assert bc.client_count == 1
        bc.remove_client(ws)
        assert bc.client_count == 0
