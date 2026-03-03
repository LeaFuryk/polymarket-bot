"""Monitoring intervals, thresholds, and adaptive entry/exit toggles."""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    DEFAULT_ADAPTIVE_ENTRY_WINDOW,
    DEFAULT_AI_COOLDOWN_SECONDS,
    DEFAULT_BTC_PRICE_CACHE_TTL,
    DEFAULT_MARKET_MONITOR_INTERVAL,
    DEFAULT_POSITION_MONITOR_INTERVAL,
    DEFAULT_RR_TRIGGER_THRESHOLD,
    DEFAULT_SL_CEILING,
    DEFAULT_SL_FLOOR,
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TAKE_PROFIT_PCT,
    DEFAULT_TP_CEILING,
    DEFAULT_TP_FLOOR,
)


class MonitorConfig(BaseModel):
    """Monitoring intervals, thresholds, and adaptive entry/exit toggles."""

    market_monitor_interval: float = DEFAULT_MARKET_MONITOR_INTERVAL
    position_monitor_interval: float = DEFAULT_POSITION_MONITOR_INTERVAL
    ai_cooldown_seconds: float = DEFAULT_AI_COOLDOWN_SECONDS
    rr_trigger_threshold: float = DEFAULT_RR_TRIGGER_THRESHOLD
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT
    take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT
    btc_price_cache_ttl: float = DEFAULT_BTC_PRICE_CACHE_TTL
    adaptive_entry_enabled: bool = True
    adaptive_entry_window: int = DEFAULT_ADAPTIVE_ENTRY_WINDOW
    dynamic_sl_enabled: bool = True
    dynamic_tp_enabled: bool = True
    sl_floor: float = DEFAULT_SL_FLOOR
    sl_ceiling: float = DEFAULT_SL_CEILING
    tp_floor: float = DEFAULT_TP_FLOOR
    tp_ceiling: float = DEFAULT_TP_CEILING
