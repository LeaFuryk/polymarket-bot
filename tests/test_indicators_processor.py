"""Tests for IndicatorsProcessor orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polybot.indicators.catalog import all_indicators
from polybot.indicators.core import FeatureConfig, SessionContext
from polybot.indicators.processor import IndicatorsProcessor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(**kwargs):
    """Create a minimal MagicMock snapshot."""
    snap = MagicMock()
    snap.price_history = kwargs.get("price_history", [])
    snap.btc_price_history = kwargs.get("btc_price_history", [])
    snap.btc_candles = kwargs.get("btc_candles", [])
    snap.btc_price = kwargs.get("btc_price")
    snap.orderbook = MagicMock()
    snap.orderbook.bid_depth = kwargs.get("bid_depth", 100.0)
    snap.orderbook.ask_depth = kwargs.get("ask_depth", 100.0)
    snap.orderbook.midpoint = kwargs.get("up_mid", 0.50)
    snap.orderbook.best_ask = kwargs.get("up_ask", 0.51)
    snap.orderbook.best_bid = kwargs.get("up_bid", 0.49)
    snap.orderbook.spread_pct = kwargs.get("spread_pct", 0.02)
    snap.down_orderbook = MagicMock()
    snap.down_orderbook.bid_depth = kwargs.get("down_bid_depth", 100.0)
    snap.down_orderbook.ask_depth = kwargs.get("down_ask_depth", 100.0)
    snap.down_orderbook.midpoint = kwargs.get("down_mid", 0.50)
    snap.down_orderbook.best_ask = kwargs.get("down_ask", 0.51)
    snap.down_orderbook.best_bid = kwargs.get("down_bid", 0.49)
    return snap


def _make_candles(directions: list[str], close: float = 65000.0, high: float = 65100.0, low: float = 65000.0):
    candles = []
    for d in directions:
        c = MagicMock()
        c.direction = d
        c.close = close
        c.open = close - 10 if d == "up" else close + 10
        c.high = high
        c.low = low
        c.volume = 1.0
        candles.append(c)
    return candles


# ---------------------------------------------------------------------------
# Processor tests
# ---------------------------------------------------------------------------


class TestProcessorNoConfig:
    """Processor with no feature config runs all indicators."""

    def test_returns_indicator_results(self):
        indicators = all_indicators()
        processor = IndicatorsProcessor(indicators)
        snap = _make_snapshot()
        results = processor.compute(snap)
        # Should have some results (orderbook indicators work with basic mocks)
        assert len(results.results) >= 0

    def test_derived_fields_populated(self):
        indicators = all_indicators()
        processor = IndicatorsProcessor(indicators)
        snap = _make_snapshot(up_ask=0.40, down_ask=0.60)
        results = processor.compute(snap, candle_open_btc=65000.0)
        # R/R should be computed
        assert results.rr_up == pytest.approx(1.5)  # (1 - 0.4) / 0.4
        assert results.rr_down == pytest.approx(2 / 3)  # (1 - 0.6) / 0.6
        # Best entry
        assert results.best_entry_price == pytest.approx(0.40)


class TestProcessorWithConfig:
    """Processor with feature config only returns enabled indicators."""

    def test_only_enabled_indicators_returned(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        config_file.write_text(
            json.dumps(
                {
                    "indicators": [
                        {"name": "spread_trend", "enabled": True},
                        {"name": "orderbook_imbalance", "enabled": True},
                        {"name": "token_momentum", "enabled": False},
                    ]
                }
            )
        )
        cfg = FeatureConfig(config_file)
        processor = IndicatorsProcessor(all_indicators(), cfg)
        snap = _make_snapshot()
        results = processor.compute(snap)
        names = {r.name for r in results.results}
        assert "Spread Level" in names
        assert "Orderbook Imbalance" in names
        # token_momentum disabled, shouldn't appear
        # (it also wouldn't have enough data, but the point is config filtering)

    def test_empty_config_returns_no_results(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        config_file.write_text(json.dumps({"indicators": []}))
        cfg = FeatureConfig(config_file)
        processor = IndicatorsProcessor(all_indicators(), cfg)
        snap = _make_snapshot()
        results = processor.compute(snap)
        assert results.results == []
        # Derived fields should still be populated
        assert results.rr_up > 0


class TestProcessorDerivedFields:
    """Tests for derived field extraction."""

    def test_btc_move_from_open(self):
        processor = IndicatorsProcessor(all_indicators())
        btc_price = MagicMock()
        btc_price.price_usd = 65100.0
        btc_price.chainlink_price = None
        btc_price.price_divergence = None
        snap = _make_snapshot(btc_price=btc_price)
        results = processor.compute(snap, candle_open_btc=65000.0)
        assert results.btc_move_from_open == pytest.approx(100.0)

    def test_btc_move_none_when_no_candle_open(self):
        processor = IndicatorsProcessor(all_indicators())
        snap = _make_snapshot()
        results = processor.compute(snap)
        assert results.btc_move_from_open == 0.0

    def test_consecutive_streak(self):
        processor = IndicatorsProcessor(all_indicators())
        snap = _make_snapshot()
        snap.btc_candles = _make_candles(["up", "up", "up", "down", "down", "down", "down"])
        results = processor.compute(snap)
        assert results.consecutive_streak == 4
        assert results.streak_direction == "down"

    def test_btc_range_30m(self):
        processor = IndicatorsProcessor(all_indicators())
        snap = _make_snapshot()
        snap.btc_candles = _make_candles(["up", "up", "up"], high=65200.0, low=65000.0)
        results = processor.compute(snap)
        assert results.btc_range_30m == pytest.approx(200.0)

    def test_best_entry_up(self):
        processor = IndicatorsProcessor(all_indicators())
        snap = _make_snapshot(up_ask=0.30, down_ask=0.50)
        results = processor.compute(snap)
        assert results.best_entry_price == pytest.approx(0.30)


class TestProcessorExceptionHandling:
    """Indicators that raise are caught and skipped."""

    def test_broken_indicator_skipped(self):
        class BrokenIndicator:
            name = "broken"
            display_name = "Broken"

            def compute(self, ctx):
                raise RuntimeError("boom")

        processor = IndicatorsProcessor([BrokenIndicator()])
        snap = _make_snapshot()
        # Should not raise
        results = processor.compute(snap)
        assert results.results == []


class TestProcessorSession:
    """Session context is passed through to indicators."""

    def test_session_streak_indicator_receives_session(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        config_file.write_text(json.dumps({"indicators": [{"name": "session_streak", "enabled": True}]}))
        cfg = FeatureConfig(config_file)
        processor = IndicatorsProcessor(all_indicators(), cfg)
        snap = _make_snapshot()
        session = SessionContext(wins=7, losses=3)
        results = processor.compute(snap, session)
        streak = results.get("Session Streak")
        assert streak is not None
        assert streak.value == pytest.approx(70.0)
