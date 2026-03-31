"""Tests for PriceStream protocol conformance."""

from polybot.adapters.chainlink_streams import ChainlinkStreamsAdapter
from polybot.ports.price_stream import PriceStream


def test_adapter_satisfies_protocol():
    """ChainlinkStreamsAdapter structurally satisfies PriceStream."""
    adapter = ChainlinkStreamsAdapter(user_id="test", secret="test")
    assert isinstance(adapter, PriceStream)
