"""YAML + environment variable configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class MarketConfig(BaseModel):
    condition_id: str = "0x"
    clob_api_url: str = "https://clob.polymarket.com"
    token_id: str = ""
    series_slug: str = "btc-updown-5m"


class ApiConfig(BaseModel):
    polymarket_host: str = "https://clob.polymarket.com"
    coingecko_url: str = "https://api.coingecko.com/api/v3"
    polymarket_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    ethereum_rpc_url: str = "https://ethereum.publicnode.com"
    chainlink_btcusd_address: str = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"
    polymarket_rtds_url: str = "wss://ws-live-data.polymarket.com"


class AgentConfig(BaseModel):
    decision_interval: int = 60
    fast_poll_interval: int = 10
    initial_cash: float = 10000.0
    max_cycles: int = 0
    resolution_buffer_seconds: int = 10
    min_confidence: float = 0.55


class AiConfig(BaseModel):
    model: str = "claude-sonnet-4-5-20250929"
    screen_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 1024
    temperature: float = 0.0
    api_key: str = ""
    input_cost_per_mtok: float = 3.0
    output_cost_per_mtok: float = 8.0
    screen_input_cost_per_mtok: float = 0.80
    screen_output_cost_per_mtok: float = 4.0
    two_pass_enabled: bool = True


class SimulatorConfig(BaseModel):
    base_slippage_bps: float = 5.0
    proportional_factor: float = 0.5
    fee_bps: float = 20.0
    limit_order_ttl: int = 300


class RiskConfig(BaseModel):
    max_position_pct: float = 0.25
    max_spread_pct: float = 0.05
    min_liquidity: float = 100.0
    daily_loss_limit_pct: float = 0.10
    max_concentration_pct: float = 0.50
    min_reward_risk_ratio: float = 1.3  # (1 - entry_price) / entry_price must exceed this


class MonitorConfig(BaseModel):
    market_monitor_interval: float = 1.0     # seconds between market data fetches
    position_monitor_interval: float = 1.0   # seconds between P&L checks
    ai_cooldown_seconds: float = 60.0        # min seconds between AI calls
    rr_trigger_threshold: float = 1.0        # R/R to trigger AI (entry <= $0.50)
    stop_loss_pct: float = -0.35             # -35% triggers exit evaluation
    take_profit_pct: float = 0.50            # +50% triggers exit evaluation
    btc_price_cache_ttl: float = 2.0         # seconds (was 30s)
    adaptive_entry_enabled: bool = True      # use adaptive BTC threshold + max entry
    adaptive_entry_window: int = 10          # rolling candle window for adaptive stats
    dynamic_sl_enabled: bool = True          # adaptive stop-loss using 5 factors
    dynamic_tp_enabled: bool = True          # adaptive take-profit using 3 factors
    sl_floor: float = -0.75                  # never wider than -75%
    sl_ceiling: float = -0.15               # never tighter than -15%
    tp_floor: float = 0.20                   # never below +20%
    tp_ceiling: float = 1.20                 # never above +120%


class LoggingConfig(BaseModel):
    log_dir: str = "logs"
    knowledge_dir: str = "data/knowledge"
    jsonl_enabled: bool = True
    sqlite_enabled: bool = True
    sqlite_db_path: str = "logs/polybot.db"
    market_history_db_path: str = "data/market_history.db"
    dashboard_enabled: bool = True
    dashboard_refresh_rate: int = 2


class AppConfig(BaseModel):
    market: MarketConfig = Field(default_factory=MarketConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    simulator: SimulatorConfig = Field(default_factory=SimulatorConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _apply_env_overrides(config: AppConfig) -> None:
    """Apply POLYBOT_* environment variable overrides."""
    env_map: dict[str, tuple[object, str, type]] = {
        "POLYBOT_MARKET_CONDITION_ID": (config.market, "condition_id", str),
        "POLYBOT_MARKET_TOKEN_ID": (config.market, "token_id", str),
        "POLYBOT_AI_API_KEY": (config.ai, "api_key", str),
        "POLYBOT_AI_MODEL": (config.ai, "model", str),
        "POLYBOT_AGENT_DECISION_INTERVAL": (config.agent, "decision_interval", int),
        "POLYBOT_AGENT_INITIAL_CASH": (config.agent, "initial_cash", float),
        "POLYBOT_AGENT_MAX_CYCLES": (config.agent, "max_cycles", int),
        "POLYBOT_AGENT_MIN_CONFIDENCE": (config.agent, "min_confidence", float),
        "POLYBOT_RISK_DAILY_LOSS_LIMIT_PCT": (config.risk, "daily_loss_limit_pct", float),
        "POLYBOT_KNOWLEDGE_DIR": (config.logging, "knowledge_dir", str),
        "POLYBOT_ETHEREUM_RPC_URL": (config.api, "ethereum_rpc_url", str),
    }
    for env_key, (section, attr, typ) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            setattr(section, attr, typ(val))


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config from YAML file with env var overrides."""
    load_dotenv()

    data: dict = {}
    if config_path is None:
        config_path = Path("config/default.yaml")
    config_path = Path(config_path)

    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

    config = AppConfig(**data)
    _apply_env_overrides(config)
    return config
