"""Tests for CollectorClient."""

import json

import pytest

from polybot.adapters.collector_client import CollectorClient


class TestCollectorClientCallback:
    async def test_snapshot_invokes_on_message(self):
        received = []

        async def handler(msg):
            received.append(msg)

        client = CollectorClient(on_message=handler)
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert len(received) == 1
        assert received[0] == msg

    async def test_candle_close_invokes_on_message(self):
        received = []

        async def handler(msg):
            received.append(msg)

        client = CollectorClient(on_message=handler)
        msg = {"type": "candle_close", "candle_id": "test-123", "outcome": "UP"}
        await client._handle_message(json.dumps(msg))
        assert len(received) == 1

    async def test_no_callback_still_works(self):
        client = CollectorClient()
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert client.snapshot == msg

    async def test_properties_updated(self):
        async def noop(msg):
            pass

        client = CollectorClient(on_message=noop)
        snap = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(snap))
        assert client.snapshot == snap

        candle = {"type": "candle_close", "candle_id": "x", "outcome": "DOWN"}
        await client._handle_message(json.dumps(candle))
        assert client.candle_close == candle

    async def test_callback_error_does_not_crash(self):
        async def bad_handler(msg):
            raise RuntimeError("boom")

        client = CollectorClient(on_message=bad_handler)
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert client.snapshot == msg

    async def test_malformed_json_raises(self):
        client = CollectorClient()
        with pytest.raises(json.JSONDecodeError):
            await client._handle_message("not json")
