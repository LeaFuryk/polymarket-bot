"""Tests for PolybotServer."""

import asyncio
import json

import websockets
from polybot.ws.broadcaster import Broadcaster
from polybot.ws.server import PolybotServer


class TestPolybotServer:
    async def test_client_receives_broadcast(self):
        bc = Broadcaster()
        server = PolybotServer(bc, port=0)
        await server.start()
        try:
            async with websockets.connect(f"ws://localhost:{server.port}") as ws:
                await asyncio.sleep(0.05)  # let handler register client
                await bc.broadcast_json({"type": "snapshot", "btc_price": 69000.0})
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                assert msg["type"] == "snapshot"
                assert msg["btc_price"] == 69000.0
        finally:
            await server.stop()

    async def test_start_stop_no_clients(self):
        bc = Broadcaster()
        server = PolybotServer(bc, port=0)
        await server.start()
        assert server.port > 0
        await server.stop()
