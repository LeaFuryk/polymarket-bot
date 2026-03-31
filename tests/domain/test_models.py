"""Tests for domain models."""

from dataclasses import FrozenInstanceError

import pytest
from polybot.domain.models import BtcTick


class TestBtcTick:
    def test_creation(self):
        tick = BtcTick(price=87000.0, bid=86999.50, ask=87000.50, timestamp=1700000000.0)
        assert tick.price == 87000.0
        assert tick.bid == 86999.50
        assert tick.ask == 87000.50
        assert tick.timestamp == 1700000000.0

    def test_frozen(self):
        tick = BtcTick(price=87000.0, bid=86999.50, ask=87000.50, timestamp=1700000000.0)
        with pytest.raises(FrozenInstanceError):
            tick.price = 99999.0  # type: ignore[misc]

    def test_equality(self):
        a = BtcTick(price=87000.0, bid=86999.50, ask=87000.50, timestamp=1700000000.0)
        b = BtcTick(price=87000.0, bid=86999.50, ask=87000.50, timestamp=1700000000.0)
        assert a == b
