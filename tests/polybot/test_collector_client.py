"""Tests for CollectorClient with MessageRelay integration."""

import json
from unittest.mock import AsyncMock

import pytest

from polybot.adapters.collector_client import CollectorClient


class TestCollectorClientRelay:
    async def test_snapshot_forwarded_to_relay(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        relay.broadcast_json.assert_awaited_once_with(msg)

    async def test_candle_close_forwarded_to_relay(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        msg = {"type": "candle_close", "candle_id": "test-123", "outcome": "UP"}
        await client._handle_message(json.dumps(msg))
        relay.broadcast_json.assert_awaited_once_with(msg)

    async def test_no_relay_still_works(self):
        client = CollectorClient()
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert client.snapshot == msg

    async def test_properties_updated_with_relay(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        snap = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(snap))
        assert client.snapshot == snap

        candle = {"type": "candle_close", "candle_id": "x", "outcome": "DOWN"}
        await client._handle_message(json.dumps(candle))
        assert client.candle_close == candle

    async def test_unknown_message_type_still_relayed(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        msg = {"type": "unknown", "data": 123}
        await client._handle_message(json.dumps(msg))
        relay.broadcast_json.assert_awaited_once_with(msg)
        assert client.snapshot is None
        assert client.candle_close is None

    async def test_malformed_json_raises(self):
        client = CollectorClient()
        with pytest.raises(json.JSONDecodeError):
            await client._handle_message("not json")

    async def test_relay_error_does_not_crash(self):
        relay = AsyncMock()
        relay.broadcast_json.side_effect = Exception("relay down")
        client = CollectorClient(relay=relay)
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert client.snapshot == msg  # state still updated despite relay failure
