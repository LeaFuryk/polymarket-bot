"""Tests for PriceStream protocol conformance."""

from polybot_data.adapters.chainlink_streams import ChainlinkStreamsAdapter
from polybot_data.ports.price_stream import PriceStream


def test_adapter_satisfies_protocol():
    """ChainlinkStreamsAdapter structurally satisfies PriceStream."""
    adapter = ChainlinkStreamsAdapter(user_id="test", secret="test")
    assert isinstance(adapter, PriceStream)
