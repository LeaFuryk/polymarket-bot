"""Bot agent behavior: polling intervals, cash, and confidence thresholds."""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from polybot.config.constants import (
    DEFAULT_DECISION_INTERVAL,
    DEFAULT_FAST_POLL_INTERVAL,
    DEFAULT_INITIAL_CASH,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_RESOLUTION_BUFFER_SECONDS,
)


class AgentConfig(BaseModel):
    """Bot agent behavior: polling intervals, cash, and confidence thresholds."""

    decision_interval: int = DEFAULT_DECISION_INTERVAL
    fast_poll_interval: int = DEFAULT_FAST_POLL_INTERVAL
    initial_cash: float = DEFAULT_INITIAL_CASH
    max_cycles: int = 0
    resolution_buffer_seconds: int = DEFAULT_RESOLUTION_BUFFER_SECONDS
    min_confidence: float = DEFAULT_MIN_CONFIDENCE

    @field_validator("min_confidence")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            msg = f"min_confidence must be between 0 and 1, got {v}"
            raise ValueError(msg)
        return v
