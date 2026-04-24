"""Tests for TradingStrategy domain model."""

import json

import pytest
from polybot.domain.trading_strategy import TradingStrategy


class TestTradingStrategy:
    def test_from_json_loads_fields(self, tmp_path):
        config = {
            "model": "xgb",
            "min_edge": 0.08,
            "max_entries": 3,
            "min_btc_move": 0.0005,
        }
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="XGBoost")
        assert s.name == "XGBoost"
        assert s.min_edge == 0.08
        assert s.max_entries == 3
        assert s.min_btc_move == 0.0005

    def test_from_json_defaults(self, tmp_path):
        config = {"model": "lr"}
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="LR")
        assert s.min_edge == 0.0
        assert s.max_entries == 1
        assert s.min_btc_move == 0.0003

    def test_old_format_raises(self, tmp_path):
        config = {"entry_points": [[0.05, 3], [0.50, 3]], "min_confidence": 0.6}
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        with pytest.raises(ValueError, match="old format"):
            TradingStrategy.from_json(str(path), name="XGBoost")

    def test_frozen(self, tmp_path):
        config = {"min_edge": 0.05, "max_entries": 2}
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="LR")
        with pytest.raises(AttributeError):
            s.name = "changed"
