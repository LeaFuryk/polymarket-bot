"""Tests for polybot.config — model validation, constants, and ConfigLoader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from polybot.config import (
    AgentConfig,
    AppConfig,
    ConfigLoader,
    RiskConfig,
    load_config,
)
from polybot.config.constants import (
    DEFAULT_CLOB_API_URL,
    DEFAULT_DECISION_INTERVAL,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_POLYMARKET_HOST,
)

# -- Constants -----------------------------------------------------------------


class TestConstants:
    """Default constants are used by config models."""

    def test_market_defaults(self):
        from polybot.config import MarketConfig

        cfg = MarketConfig()
        assert cfg.clob_api_url == DEFAULT_CLOB_API_URL

    def test_api_defaults(self):
        from polybot.config import ApiConfig

        cfg = ApiConfig()
        assert cfg.polymarket_host == DEFAULT_POLYMARKET_HOST

    def test_agent_defaults(self):
        cfg = AgentConfig()
        assert cfg.decision_interval == DEFAULT_DECISION_INTERVAL
        assert cfg.min_confidence == DEFAULT_MIN_CONFIDENCE


# -- Model validation ----------------------------------------------------------


class TestAgentConfigValidation:
    """min_confidence must be in [0, 1]."""

    def test_valid_confidence(self):
        cfg = AgentConfig(min_confidence=0.7)
        assert cfg.min_confidence == 0.7

    def test_confidence_zero_and_one(self):
        assert AgentConfig(min_confidence=0.0).min_confidence == 0.0
        assert AgentConfig(min_confidence=1.0).min_confidence == 1.0

    def test_confidence_too_high(self):
        with pytest.raises(ValueError, match="between 0 and 1"):
            AgentConfig(min_confidence=1.5)

    def test_confidence_negative(self):
        with pytest.raises(ValueError, match="between 0 and 1"):
            AgentConfig(min_confidence=-0.1)


class TestRiskConfigValidation:
    """Percentage fields must be in [0, 1]."""

    def test_valid_defaults(self):
        cfg = RiskConfig()
        assert 0 <= cfg.max_position_pct <= 1
        assert 0 <= cfg.daily_loss_limit_pct <= 1

    def test_position_pct_too_high(self):
        with pytest.raises(ValueError, match="between 0 and 1"):
            RiskConfig(max_position_pct=2.0)

    def test_concentration_pct_negative(self):
        with pytest.raises(ValueError, match="between 0 and 1"):
            RiskConfig(max_concentration_pct=-0.5)


# -- ConfigLoader --------------------------------------------------------------


class TestConfigLoader:
    """ConfigLoader reads YAML and applies env overrides."""

    def test_defaults_without_yaml(self, tmp_path: Path):
        """Missing YAML file returns defaults."""
        loader = ConfigLoader(tmp_path / "nonexistent.yaml")
        cfg = loader.load()
        assert isinstance(cfg, AppConfig)
        assert cfg.agent.decision_interval == DEFAULT_DECISION_INTERVAL

    def test_yaml_overrides_defaults(self, tmp_path: Path):
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text(yaml.dump({"agent": {"decision_interval": 120}}))
        cfg = ConfigLoader(yaml_path).load()
        assert cfg.agent.decision_interval == 120

    def test_env_overrides_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text(yaml.dump({"agent": {"initial_cash": 5000.0}}))
        monkeypatch.setenv("POLYBOT_AGENT_INITIAL_CASH", "9999.0")
        cfg = ConfigLoader(yaml_path).load()
        assert cfg.agent.initial_cash == 9999.0

    def test_env_bool_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("POLYBOT_TRADING_DRY_RUN", "true")
        cfg = ConfigLoader(tmp_path / "nope.yaml").load()
        assert cfg.trading.dry_run is True

    def test_env_bool_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("POLYBOT_TRADING_DRY_RUN", "no")
        cfg = ConfigLoader(tmp_path / "nope.yaml").load()
        assert cfg.trading.dry_run is False

    def test_env_string_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("POLYBOT_AI_API_KEY", "sk-test-123")
        cfg = ConfigLoader(tmp_path / "nope.yaml").load()
        assert cfg.ai.api_key == "sk-test-123"


# -- Backward-compat load_config wrapper --------------------------------------


def test_load_config_returns_app_config(tmp_path: Path):
    """load_config() wrapper delegates to ConfigLoader."""
    cfg = load_config(tmp_path / "missing.yaml")
    assert isinstance(cfg, AppConfig)
