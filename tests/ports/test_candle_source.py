"""Tests for CandleSource protocol conformance."""

from unittest.mock import AsyncMock

from polybot.ports.candle_source import CandleSource
from polybot.services.candle_aggregator import CandleAggregator


def test_aggregator_satisfies_candle_source():
    """CandleAggregator structurally satisfies CandleSource."""
    aggregator = CandleAggregator(
        price_stream=AsyncMock(),
        volume_feed=AsyncMock(),
    )
    assert isinstance(aggregator, CandleSource)
