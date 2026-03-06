"""Tests for the indicators package — constants, registry, core functions, and selected indicators."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polybot.indicators import (
    _ema,
    compute_indicators,
    format_indicators,
    get_registry,
    register,
)
from polybot.indicators.constants import (
    IMBALANCE_STRONG_BUY,
    NEAR_ZERO,
    TOKEN_VOL_HIGH,
    TREND_STRONG_THRESHOLD,
)
from polybot.indicators.core import (
    FeatureConfig,
    FeatureConfigEntry,
    IndicatorResult,
    SessionContext,
)

# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_near_zero_is_positive_and_small(self):
        assert NEAR_ZERO > 0
        assert NEAR_ZERO < 1e-6

    def test_threshold_ordering(self):
        assert IMBALANCE_STRONG_BUY > 1.0
        assert TOKEN_VOL_HIGH > 0
        assert TREND_STRONG_THRESHOLD > 0

    def test_all_constants_importable_from_package(self):
        from polybot.indicators import (
            BTC_VOL_HIGH,
            MAGNITUDE_EXHAUSTION,
            NEAR_ZERO,
            SPREAD_VERY_WIDE,
            Z_OVEREXTENDED,
        )

        assert NEAR_ZERO > 0
        assert SPREAD_VERY_WIDE > 0
        assert BTC_VOL_HIGH > 0
        assert MAGNITUDE_EXHAUSTION > 0
        assert Z_OVEREXTENDED > 0


# ---------------------------------------------------------------------------
# Data type tests
# ---------------------------------------------------------------------------


class TestDataTypes:
    def test_indicator_result_fields(self):
        r = IndicatorResult(name="test", value=1.5, label="foo")
        assert r.name == "test"
        assert r.value == 1.5
        assert r.label == "foo"

    def test_session_context_defaults(self):
        ctx = SessionContext()
        assert ctx.wins == 0
        assert ctx.losses == 0
        assert ctx.avg_win_confidence == 0.0
        assert ctx.avg_loss_confidence == 0.0
        assert ctx.candle_open_btc is None

    def test_session_context_custom(self):
        ctx = SessionContext(wins=5, losses=3, candle_open_btc=85000.0)
        assert ctx.wins == 5
        assert ctx.candle_open_btc == 85000.0

    def test_feature_config_entry_defaults(self):
        e = FeatureConfigEntry(name="test_ind")
        assert e.enabled is True
        assert e.params == {}

    def test_feature_config_entry_custom(self):
        e = FeatureConfigEntry(name="x", enabled=False, params={"window": 5})
        assert e.enabled is False
        assert e.params["window"] == 5


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_get_registry_returns_dict(self):
        reg = get_registry()
        assert isinstance(reg, dict)

    def test_all_24_indicators_registered(self):
        reg = get_registry()
        assert len(reg) >= 24

    def test_known_indicators_in_registry(self):
        reg = get_registry()
        expected = [
            "market_trend",
            "token_momentum",
            "token_volatility",
            "orderbook_imbalance",
            "spread_trend",
            "btc_momentum",
            "btc_volatility",
            "session_streak",
            "consecutive_streak",
            "volume_trend",
            "chainlink_divergence",
            "flat_market_edge",
        ]
        for name in expected:
            assert name in reg, f"{name} missing from registry"

    def test_register_decorator_adds_function(self):
        """Custom indicator can be registered."""
        # Use a unique name to not pollute shared state
        name = "_test_custom_indicator_42"

        @register(name)
        def _custom(snap, params, session):
            return IndicatorResult(name="custom", value=0, label="test")

        assert name in get_registry()
        # Cleanup
        get_registry().pop(name, None)


# ---------------------------------------------------------------------------
# FeatureConfig tests
# ---------------------------------------------------------------------------


class TestFeatureConfig:
    def test_load_missing_file(self, tmp_path: Path):
        cfg = FeatureConfig(tmp_path / "nonexistent.json")
        cfg.load()
        assert cfg.enabled_indicators() == []

    def test_load_valid_config(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        config_file.write_text(
            json.dumps(
                {
                    "indicators": [
                        {"name": "token_momentum", "enabled": True, "params": {"window": 10}},
                        {"name": "btc_volatility", "enabled": False},
                        {"name": "session_streak", "enabled": True},
                    ]
                }
            )
        )
        cfg = FeatureConfig(config_file)
        cfg.load()
        enabled = cfg.enabled_indicators()
        assert len(enabled) == 2
        assert enabled[0] == ("token_momentum", {"window": 10})
        assert enabled[1] == ("session_streak", {})

    def test_load_malformed_json(self, tmp_path: Path):
        config_file = tmp_path / "bad.json"
        config_file.write_text("not valid json{{{")
        cfg = FeatureConfig(config_file)
        cfg.load()
        assert cfg.enabled_indicators() == []

    def test_to_dict_roundtrip(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        original = {
            "indicators": [
                {"name": "btc_momentum", "enabled": True, "params": {"window": 10}},
            ]
        }
        config_file.write_text(json.dumps(original))
        cfg = FeatureConfig(config_file)
        cfg.load()
        result = cfg.to_dict()
        assert result == original

    def test_injectable_logger(self, tmp_path: Path):
        custom_logger = logging.getLogger("test.indicators.config")
        config_file = tmp_path / "bad.json"
        config_file.write_text("invalid")
        cfg = FeatureConfig(config_file, logger=custom_logger)
        with pytest.raises(Exception) if False else _no_raise():
            cfg.load()
        assert cfg.enabled_indicators() == []


# ---------------------------------------------------------------------------
# EMA tests
# ---------------------------------------------------------------------------


class TestEma:
    def test_ema_single_value(self):
        assert _ema([100.0], 5) == 100.0

    def test_ema_fewer_than_period(self):
        """Falls back to simple mean when fewer values than period."""
        result = _ema([10.0, 20.0, 30.0], 5)
        assert result == pytest.approx(20.0)

    def test_ema_exact_period(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _ema(values, 5)
        # EMA seeded at first value (1.0), then iterates through 2,3,4,5
        assert isinstance(result, float)
        # EMA should be pulled toward recent values
        assert result > 2.5

    def test_ema_longer_than_period(self):
        values = list(range(1, 11))  # 1..10
        result = _ema(values, 5)
        # Should use only last 5 values (6,7,8,9,10)
        assert result > 7.0

    def test_ema_constant_values(self):
        values = [50.0] * 10
        result = _ema(values, 5)
        assert result == pytest.approx(50.0)

    def test_ema_increasing_trend(self):
        values = [float(i) for i in range(20)]
        result = _ema(values, 10)
        # EMA of increasing values should be close to but below the last value
        assert result < 19.0
        assert result > 14.0


# ---------------------------------------------------------------------------
# compute_indicators tests
# ---------------------------------------------------------------------------


def _make_snapshot(**kwargs):
    """Create a minimal MagicMock snapshot with required attributes."""
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


class TestComputeIndicators:
    def test_no_enabled_indicators(self, tmp_path: Path):
        config_file = tmp_path / "empty.json"
        config_file.write_text(json.dumps({"indicators": []}))
        cfg = FeatureConfig(config_file)
        cfg.load()
        snap = _make_snapshot()
        results = compute_indicators(snap, cfg)
        assert results == []

    def test_unknown_indicator_skipped(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        config_file.write_text(json.dumps({"indicators": [{"name": "nonexistent_indicator_xyz", "enabled": True}]}))
        cfg = FeatureConfig(config_file)
        cfg.load()
        snap = _make_snapshot()
        results = compute_indicators(snap, cfg)
        assert results == []

    def test_indicator_returning_none_excluded(self, tmp_path: Path):
        """Indicators that return None (e.g. insufficient data) are excluded."""
        config_file = tmp_path / "features.json"
        config_file.write_text(json.dumps({"indicators": [{"name": "token_momentum", "enabled": True}]}))
        cfg = FeatureConfig(config_file)
        cfg.load()
        snap = _make_snapshot(price_history=[0.5])  # too few for default window=10
        results = compute_indicators(snap, cfg)
        assert results == []

    def test_indicator_success(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        config_file.write_text(
            json.dumps(
                {
                    "indicators": [
                        {"name": "token_momentum", "enabled": True, "params": {"window": 3}},
                    ]
                }
            )
        )
        cfg = FeatureConfig(config_file)
        cfg.load()
        snap = _make_snapshot(price_history=[0.40, 0.42, 0.45, 0.48])
        results = compute_indicators(snap, cfg)
        assert len(results) == 1
        assert results[0].name == "Token Momentum (3pt)"
        assert results[0].value == pytest.approx(0.06)

    def test_injectable_logger(self, tmp_path: Path):
        config_file = tmp_path / "features.json"
        config_file.write_text(json.dumps({"indicators": [{"name": "nonexistent_xyz", "enabled": True}]}))
        cfg = FeatureConfig(config_file)
        cfg.load()
        custom_logger = logging.getLogger("test.compute")
        snap = _make_snapshot()
        results = compute_indicators(snap, cfg, logger=custom_logger)
        assert results == []

    def test_indicator_exception_handled(self, tmp_path: Path):
        """Indicator that raises is caught and skipped."""
        name = "_test_raising_indicator"

        @register(name)
        def _raising(snap, params, session):
            raise RuntimeError("boom")

        config_file = tmp_path / "features.json"
        config_file.write_text(json.dumps({"indicators": [{"name": name, "enabled": True}]}))
        cfg = FeatureConfig(config_file)
        cfg.load()
        snap = _make_snapshot()
        results = compute_indicators(snap, cfg)
        assert results == []
        # Cleanup
        get_registry().pop(name, None)


# ---------------------------------------------------------------------------
# format_indicators tests
# ---------------------------------------------------------------------------


class TestFormatIndicators:
    def test_empty_list(self):
        assert format_indicators([]) == ""

    def test_single_result(self):
        results = [IndicatorResult(name="Test", value=1.0, label="good")]
        text = format_indicators(results)
        assert "## Computed Indicators" in text
        assert "- Test: good" in text

    def test_multiple_results(self):
        results = [
            IndicatorResult(name="A", value=1.0, label="a_label"),
            IndicatorResult(name="B", value=2.0, label="b_label"),
        ]
        text = format_indicators(results)
        assert "- A: a_label" in text
        assert "- B: b_label" in text


# ---------------------------------------------------------------------------
# Selected indicator function tests
# ---------------------------------------------------------------------------


class TestTokenMomentum:
    def test_bullish(self):
        snap = _make_snapshot(price_history=[0.40, 0.42, 0.44, 0.46, 0.48])
        fn = get_registry()["token_momentum"]
        result = fn(snap, {"window": 3}, None)
        assert result is not None
        assert result.value > 0
        assert "bullish" in result.label

    def test_bearish(self):
        snap = _make_snapshot(price_history=[0.48, 0.46, 0.44, 0.42, 0.40])
        fn = get_registry()["token_momentum"]
        result = fn(snap, {"window": 3}, None)
        assert result is not None
        assert result.value < 0
        assert "bearish" in result.label

    def test_insufficient_data(self):
        snap = _make_snapshot(price_history=[0.50])
        fn = get_registry()["token_momentum"]
        assert fn(snap, {"window": 10}, None) is None


class TestOrderbookImbalance:
    def test_strong_buy_pressure(self):
        snap = _make_snapshot(bid_depth=200.0, ask_depth=100.0)
        fn = get_registry()["orderbook_imbalance"]
        result = fn(snap, {}, None)
        assert result is not None
        assert result.value == pytest.approx(2.0)
        assert "strong buy pressure" in result.label

    def test_balanced(self):
        snap = _make_snapshot(bid_depth=100.0, ask_depth=100.0)
        fn = get_registry()["orderbook_imbalance"]
        result = fn(snap, {}, None)
        assert result is not None
        assert "balanced" in result.label

    def test_zero_ask_depth(self):
        snap = _make_snapshot(bid_depth=100.0, ask_depth=0.0)
        fn = get_registry()["orderbook_imbalance"]
        assert fn(snap, {}, None) is None


class TestSessionStreak:
    def test_with_session(self):
        snap = _make_snapshot()
        session = SessionContext(wins=7, losses=3)
        fn = get_registry()["session_streak"]
        result = fn(snap, {}, session)
        assert result is not None
        assert result.value == pytest.approx(70.0)
        assert "7W/3L" in result.label

    def test_no_session(self):
        snap = _make_snapshot()
        fn = get_registry()["session_streak"]
        assert fn(snap, {}, None) is None

    def test_zero_trades(self):
        snap = _make_snapshot()
        session = SessionContext(wins=0, losses=0)
        fn = get_registry()["session_streak"]
        assert fn(snap, {}, session) is None


class TestConsecutiveStreak:
    def _make_candles(self, directions: list[str]):
        candles = []
        for d in directions:
            c = MagicMock()
            c.direction = d
            candles.append(c)
        return candles

    def test_strong_streak(self):
        snap = _make_snapshot()
        snap.btc_candles = self._make_candles(["up", "up", "up", "up", "up"])
        fn = get_registry()["consecutive_streak"]
        result = fn(snap, {}, None)
        assert result is not None
        assert result.value == 5.0
        assert "strong up streak" in result.label

    def test_no_streak(self):
        snap = _make_snapshot()
        snap.btc_candles = self._make_candles(["up", "down", "up"])
        fn = get_registry()["consecutive_streak"]
        result = fn(snap, {}, None)
        assert result is not None
        assert result.value == 1.0
        assert "no streak" in result.label

    def test_empty_candles(self):
        snap = _make_snapshot()
        snap.btc_candles = []
        fn = get_registry()["consecutive_streak"]
        assert fn(snap, {}, None) is None


class TestSpreadTrend:
    def test_very_wide(self):
        snap = _make_snapshot(spread_pct=0.06)
        fn = get_registry()["spread_trend"]
        result = fn(snap, {}, None)
        assert result is not None
        assert "very wide" in result.label

    def test_tight(self):
        snap = _make_snapshot(spread_pct=0.001)
        fn = get_registry()["spread_trend"]
        result = fn(snap, {}, None)
        assert result is not None
        assert "tight" in result.label

    def test_none_spread(self):
        snap = _make_snapshot()
        snap.orderbook.spread_pct = None
        fn = get_registry()["spread_trend"]
        assert fn(snap, {}, None) is None


class TestTokenVolatility:
    def test_high_vol(self):
        prices = [0.50 + i * 0.01 * ((-1) ** i) for i in range(20)]
        snap = _make_snapshot(price_history=prices)
        fn = get_registry()["token_volatility"]
        result = fn(snap, {"window": 20}, None)
        assert result is not None

    def test_insufficient_data(self):
        snap = _make_snapshot(price_history=[0.5])
        fn = get_registry()["token_volatility"]
        assert fn(snap, {"window": 20}, None) is None


class TestConfidenceCalibration:
    def test_well_calibrated(self):
        snap = _make_snapshot()
        session = SessionContext(wins=5, losses=5, avg_win_confidence=0.70, avg_loss_confidence=0.70)
        fn = get_registry()["confidence_calibration"]
        result = fn(snap, {}, session)
        assert result is not None
        assert "well calibrated" in result.label

    def test_higher_on_wins(self):
        snap = _make_snapshot()
        session = SessionContext(wins=5, losses=5, avg_win_confidence=0.80, avg_loss_confidence=0.60)
        fn = get_registry()["confidence_calibration"]
        result = fn(snap, {}, session)
        assert result is not None
        assert "higher confidence on wins" in result.label


class TestBestEntryAnalysis:
    def test_up_cheaper(self):
        snap = _make_snapshot(up_ask=0.40, down_ask=0.60)
        fn = get_registry()["best_entry_analysis"]
        result = fn(snap, {}, None)
        assert result is not None
        assert "UP" in result.label
        assert "significantly cheaper" in result.label

    def test_similar_pricing(self):
        snap = _make_snapshot(up_ask=0.50, down_ask=0.51)
        fn = get_registry()["best_entry_analysis"]
        result = fn(snap, {}, None)
        assert result is not None
        assert "similar pricing" in result.label

    def test_none_ask(self):
        snap = _make_snapshot()
        snap.orderbook.best_ask = None
        fn = get_registry()["best_entry_analysis"]
        assert fn(snap, {}, None) is None


class TestTokenPriceDivergence:
    def test_well_priced(self):
        snap = _make_snapshot(up_mid=0.50, down_mid=0.50)
        fn = get_registry()["token_price_divergence"]
        result = fn(snap, {}, None)
        assert result is not None
        assert "well-priced" in result.label

    def test_significant_divergence(self):
        snap = _make_snapshot(up_mid=0.55, down_mid=0.50)
        fn = get_registry()["token_price_divergence"]
        result = fn(snap, {}, None)
        assert result is not None
        assert "significant divergence" in result.label


# ---------------------------------------------------------------------------
# Re-export tests
# ---------------------------------------------------------------------------


class TestReExports:
    def test_core_types_importable(self):
        from polybot.indicators import (
            FeatureConfig,
            FeatureConfigEntry,
            IndicatorResult,
            SessionContext,
        )

        assert IndicatorResult is not None
        assert SessionContext is not None
        assert FeatureConfigEntry is not None
        assert FeatureConfig is not None

    def test_functions_importable(self):
        from polybot.indicators import (
            _ema,
            compute_indicators,
            format_indicators,
            get_registry,
            register,
        )

        assert callable(compute_indicators)
        assert callable(format_indicators)
        assert callable(_ema)
        assert callable(register)
        assert callable(get_registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _no_raise:
    """Context manager that does nothing — used as a no-op alternative to pytest.raises."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
