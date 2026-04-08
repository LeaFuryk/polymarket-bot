"""Tests for CandleSource protocol conformance."""

from unittest.mock import AsyncMock

from polybot_data.ports.candle_source import CandleSource
from polybot_data.services.candle_aggregator import CandleAggregator


def test_aggregator_satisfies_candle_source():
    """CandleAggregator structurally satisfies CandleSource."""
    aggregator = CandleAggregator(
        price_stream=AsyncMock(),
        volume_feed=AsyncMock(),
    )
    assert isinstance(aggregator, CandleSource)
