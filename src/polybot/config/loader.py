"""ConfigLoader — assembles AppConfig from YAML + env overrides."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from polybot.config.app import AppConfig


class ConfigLoader:
    """Assembles :class:`AppConfig` from a YAML file and environment overrides.

    Precedence (highest wins): ``POLYBOT_*`` env vars > YAML file > model defaults.
    """

    # Maps POLYBOT_* env vars to (section_name, attribute, type).
    _ENV_MAP: dict[str, tuple[str, str, type]] = {
        "POLYBOT_MARKET_CONDITION_ID": ("market", "condition_id", str),
        "POLYBOT_MARKET_TOKEN_ID": ("market", "token_id", str),
        "POLYBOT_AI_API_KEY": ("ai", "api_key", str),
        "POLYBOT_AI_MODEL": ("ai", "model", str),
        "POLYBOT_AGENT_DECISION_INTERVAL": ("agent", "decision_interval", int),
        "POLYBOT_AGENT_INITIAL_CASH": ("agent", "initial_cash", float),
        "POLYBOT_AGENT_MAX_CYCLES": ("agent", "max_cycles", int),
        "POLYBOT_AGENT_MIN_CONFIDENCE": ("agent", "min_confidence", float),
        "POLYBOT_RISK_DAILY_LOSS_LIMIT_PCT": ("risk", "daily_loss_limit_pct", float),
        "POLYBOT_KNOWLEDGE_DIR": ("logging", "knowledge_dir", str),
        "POLYBOT_ETHEREUM_RPC_URL": ("api", "ethereum_rpc_url", str),
        "POLYBOT_TRADING_MODE": ("trading", "mode", str),
        "POLYBOT_TRADING_PRIVATE_KEY": ("trading", "private_key", str),
        "POLYBOT_TRADING_API_KEY": ("trading", "api_key", str),
        "POLYBOT_TRADING_API_SECRET": ("trading", "api_secret", str),
        "POLYBOT_TRADING_API_PASSPHRASE": ("trading", "api_passphrase", str),
        "POLYBOT_TRADING_DRY_RUN": ("trading", "dry_run", bool),
        "POLYBOT_TRADING_PROXY_WALLET_ADDRESS": ("trading", "proxy_wallet_address", str),
        "POLYBOT_TRADING_MAX_ORDER_SIZE_USD": ("trading", "max_order_size_usd", float),
        "POLYBOT_TRADING_MAX_SESSION_LOSS_USD": ("trading", "max_session_loss_usd", float),
    }

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._path = Path(config_path) if config_path else Path("config/default.yaml")

    def load(self) -> AppConfig:
        """Load YAML, apply env overrides, and return validated config."""
        load_dotenv()
        data: dict = {}
        if self._path.exists():
            with open(self._path) as f:
                data = yaml.safe_load(f) or {}
        config = AppConfig(**data)
        self._apply_env_overrides(config)
        return config

    @classmethod
    def _apply_env_overrides(cls, config: AppConfig) -> None:
        """Apply POLYBOT_* environment variable overrides to *config*."""
        for env_key, (section_name, attr, typ) in cls._ENV_MAP.items():
            val = os.environ.get(env_key)
            if val is not None:
                section = getattr(config, section_name)
                if typ is bool:
                    setattr(section, attr, val.lower() in ("true", "1", "yes"))
                else:
                    setattr(section, attr, typ(val))


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config from YAML file with env var overrides.

    Convenience wrapper around :class:`ConfigLoader` for backward compatibility.
    """
    return ConfigLoader(config_path).load()
