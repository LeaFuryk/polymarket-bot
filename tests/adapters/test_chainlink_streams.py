"""Tests for ChainlinkStreamsAdapter."""

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from eth_abi import encode
from polybot_data.adapters.chainlink_streams import (
    _OUTER_ABI,
    _V3_ABI,
    ChainlinkStreamsAdapter,
)
from polybot_data.domain.models import BtcTick

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_v3_report(
    price: float,
    bid: float,
    ask: float,
    timestamp: int = 1700000000,
) -> str:
    """Build a hex-encoded fullReport matching Chainlink V3 format."""
    feed_id = bytes.fromhex("00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8")
    inner = encode(
        _V3_ABI,
        [
            feed_id,  # feedId
            timestamp,  # validFromTimestamp
            timestamp,  # observationsTimestamp
            0,  # nativeFee
            0,  # linkFee
            timestamp + 3600,  # expiresAt
            int(price * 1e18),  # benchmarkPrice
            int(bid * 1e18),  # bid
            int(ask * 1e18),  # ask
        ],
    )
    outer = encode(
        _OUTER_ABI,
        [
            [b"\x00" * 32, b"\x00" * 32, b"\x00" * 32],  # reportContext
            inner,  # reportBlob
            [],  # rawRs
            [],  # rawSs
            b"\x00" * 32,  # rawVs
        ],
    )
    return "0x" + outer.hex()


# ---------------------------------------------------------------------------
# HMAC auth header tests
# ---------------------------------------------------------------------------


class TestAuthHeaders:
    def test_headers_contain_required_keys(self):
        adapter = ChainlinkStreamsAdapter(user_id="my-api-key", secret="my-secret")
        headers = adapter._build_auth_headers("GET", "/api/v1/ws?feedIDs=0x123")

        assert "Authorization" in headers
        assert "X-Authorization-Timestamp" in headers
        assert "X-Authorization-Signature-SHA256" in headers

    def test_authorization_is_user_id(self):
        adapter = ChainlinkStreamsAdapter(user_id="my-api-key", secret="my-secret")
        headers = adapter._build_auth_headers("GET", "/test")
        assert headers["Authorization"] == "my-api-key"

    def test_signature_is_valid_hmac(self):
        adapter = ChainlinkStreamsAdapter(user_id="my-key", secret="my-secret")

        with patch("polybot_data.adapters.chainlink_streams.time") as mock_time:
            mock_time.time.return_value = 1700000.0  # fixed time
            headers = adapter._build_auth_headers("GET", "/api/v1/ws")

        timestamp = headers["X-Authorization-Timestamp"]
        assert timestamp == "1700000000"  # 1700000.0 * 1000

        body_hash = hashlib.sha256(b"").hexdigest()
        expected_string = f"GET /api/v1/ws {body_hash} my-key {timestamp}"
        expected_sig = hmac.new(b"my-secret", expected_string.encode(), hashlib.sha256).hexdigest()
        assert headers["X-Authorization-Signature-SHA256"] == expected_sig


# ---------------------------------------------------------------------------
# V3 report parsing tests
# ---------------------------------------------------------------------------


class TestV3Parsing:
    def test_parse_valid_report(self):
        adapter = ChainlinkStreamsAdapter(user_id="test", secret="test")

        full_report = _encode_v3_report(price=87656.35, bid=87656.31, ask=87656.86, timestamp=1700000000)
        msg = json.dumps({"report": {"fullReport": full_report}})
        tick = adapter._parse_message(msg)

        assert tick is not None
        assert isinstance(tick, BtcTick)
        assert tick.price == pytest.approx(87656.35, rel=1e-6)
        assert tick.bid == pytest.approx(87656.31, rel=1e-6)
        assert tick.ask == pytest.approx(87656.86, rel=1e-6)
        assert tick.timestamp == 1700000000.0

    def test_parse_missing_report_key(self):
        adapter = ChainlinkStreamsAdapter(user_id="test", secret="test")
        tick = adapter._parse_message(json.dumps({"status": "ok"}))
        assert tick is None

    def test_parse_missing_full_report(self):
        adapter = ChainlinkStreamsAdapter(user_id="test", secret="test")
        tick = adapter._parse_message(json.dumps({"report": {"feedID": "0x123"}}))
        assert tick is None

    def test_parse_invalid_json(self):
        adapter = ChainlinkStreamsAdapter(user_id="test", secret="test")
        tick = adapter._parse_message("not json at all")
        assert tick is None

    def test_parse_invalid_hex(self):
        adapter = ChainlinkStreamsAdapter(user_id="test", secret="test")
        msg = json.dumps({"report": {"fullReport": "0xINVALID"}})
        tick = adapter._parse_message(msg)
        assert tick is None
