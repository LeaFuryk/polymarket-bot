"""Position sizing and risk management safety limits."""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from polybot.config.constants import (
    DEFAULT_DAILY_LOSS_LIMIT_PCT,
    DEFAULT_MAX_CONCENTRATION_PCT,
    DEFAULT_MAX_POSITION_PCT,
    DEFAULT_MAX_SPREAD_PCT,
    DEFAULT_MIN_LIQUIDITY,
    DEFAULT_MIN_REWARD_RISK_RATIO,
)


class RiskConfig(BaseModel):
    """Position sizing and risk management safety limits."""

    max_position_pct: float = DEFAULT_MAX_POSITION_PCT
    max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT
    min_liquidity: float = DEFAULT_MIN_LIQUIDITY
    daily_loss_limit_pct: float = DEFAULT_DAILY_LOSS_LIMIT_PCT
    max_concentration_pct: float = DEFAULT_MAX_CONCENTRATION_PCT
    min_reward_risk_ratio: float = DEFAULT_MIN_REWARD_RISK_RATIO

    @field_validator("max_position_pct", "max_concentration_pct", "daily_loss_limit_pct")
    @classmethod
    def _validate_pct_range(cls, v: float) -> float:
        """Ensure percentage fields are between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            msg = f"Percentage must be between 0 and 1, got {v}"
            raise ValueError(msg)
        return v
