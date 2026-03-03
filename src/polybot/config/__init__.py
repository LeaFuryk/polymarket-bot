"""Configuration loading for the Polymarket bot.

Provides Pydantic-based configuration models organized by domain and a
:class:`ConfigLoader` that assembles configuration from YAML files and
``POLYBOT_*`` environment variable overrides.

Usage::

    from polybot.config import load_config
    config = load_config()  # loads config/default.yaml + POLYBOT_* env vars
"""

from polybot.config.agent import AgentConfig
from polybot.config.ai import AiConfig
from polybot.config.api import ApiConfig
from polybot.config.app import AppConfig
from polybot.config.loader import ConfigLoader, load_config
from polybot.config.logging_config import LoggingConfig
from polybot.config.market import MarketConfig
from polybot.config.monitor import MonitorConfig
from polybot.config.risk import RiskConfig
from polybot.config.simulator import SimulatorConfig
from polybot.config.trading import TradingConfig

__all__ = [
    "AgentConfig",
    "AiConfig",
    "ApiConfig",
    "AppConfig",
    "ConfigLoader",
    "load_config",
    "LoggingConfig",
    "MarketConfig",
    "MonitorConfig",
    "RiskConfig",
    "SimulatorConfig",
    "TradingConfig",
]
