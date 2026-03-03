"""Root configuration composing all domain-specific config sections."""

from __future__ import annotations

from pydantic import BaseModel, Field

from polybot.config.agent import AgentConfig
from polybot.config.ai import AiConfig
from polybot.config.api import ApiConfig
from polybot.config.logging_config import LoggingConfig
from polybot.config.market import MarketConfig
from polybot.config.monitor import MonitorConfig
from polybot.config.risk import RiskConfig
from polybot.config.simulator import SimulatorConfig
from polybot.config.trading import TradingConfig


class AppConfig(BaseModel):
    """Root configuration composing all domain-specific config sections."""

    market: MarketConfig = Field(default_factory=MarketConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    simulator: SimulatorConfig = Field(default_factory=SimulatorConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
