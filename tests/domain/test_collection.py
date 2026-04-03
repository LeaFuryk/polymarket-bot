"""Tests for domain collection models."""

import dataclasses

import pytest
from polybot.domain.collection import CandleRecord, Snapshot


class TestSnapshot:
    def test_creation(self):
        snap = Snapshot(
            timestamp=1000.0,
            tick_timestamp=999.5,
            candle_id="btc-updown-5m-900",
            elapsed_pct=0.33,
            btc_price=67800.0,
            btc_bid=67798.0,
            btc_ask=67802.0,
            up_bids=((0.55, 100.0),),
            up_asks=((0.57, 150.0),),
            down_bids=((0.43, 80.0),),
            down_asks=((0.45, 120.0),),
            up_last_trade=0.56,
            down_last_trade=0.44,
            market_volume=5000.0,
        )
        assert snap.btc_price == 67800.0
        assert snap.candle_id == "btc-updown-5m-900"
        assert snap.up_bids == ((0.55, 100.0),)

    def test_frozen(self):
        snap = Snapshot(
            timestamp=1000.0,
            tick_timestamp=999.5,
            candle_id="btc-updown-5m-900",
            elapsed_pct=0.33,
            btc_price=67800.0,
            btc_bid=67798.0,
            btc_ask=67802.0,
            up_bids=(),
            up_asks=(),
            down_bids=(),
            down_asks=(),
            up_last_trade=None,
            down_last_trade=None,
            market_volume=0.0,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.btc_price = 99999.0  # type: ignore[misc]


class TestCandleRecord:
    def test_creation_up(self):
        rec = CandleRecord(
            candle_id="btc-updown-5m-900",
            start_time=900.0,
            end_time=1200.0,
            open=67800.0,
            high=67900.0,
            low=67750.0,
            close=67850.0,
            volume=15.0,
            outcome="UP",
            final_ret=0.0007,
        )
        assert rec.outcome == "UP"
        assert rec.close > rec.open

    def test_creation_down(self):
        rec = CandleRecord(
            candle_id="btc-updown-5m-1200",
            start_time=1200.0,
            end_time=1500.0,
            open=67850.0,
            high=67860.0,
            low=67700.0,
            close=67720.0,
            volume=20.0,
            outcome="DOWN",
            final_ret=-0.0019,
        )
        assert rec.outcome == "DOWN"
        assert rec.close < rec.open
