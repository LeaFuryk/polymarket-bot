"""Tests for TradingStrategy domain model."""

import json

import pytest

from polybot.domain.trading_strategy import TradingStrategy


class TestTradingStrategy:
    def test_from_json_loads_fields(self, tmp_path):
        config = {
            "model": "xgb",
            "strategy": "2x e5%+e50%",
            "entry_points": [[0.05, 3], [0.50, 3]],
            "min_confidence": 0.6,
            "win_rate": 0.70,
            "return_pct": 27.1,
        }
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="XGBoost")
        assert s.name == "XGBoost"
        assert s.entry_points == ((0.05, 3), (0.50, 3))
        assert s.min_confidence == 0.6

    def test_from_json_defaults_min_confidence(self, tmp_path):
        config = {"entry_points": [[0.05, 3]], "strategy": "1x e5%"}
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="LR")
        assert s.min_confidence == 0.0

    def test_frozen(self, tmp_path):
        config = {"entry_points": [[0.05, 3]], "min_confidence": 0.0, "strategy": "1x"}
        path = tmp_path / "strategy.json"
        path.write_text(json.dumps(config))

        s = TradingStrategy.from_json(str(path), name="LR")
        with pytest.raises(AttributeError):
            s.name = "changed"
