"""Paper trading simulation: slippage, fees, and order TTL."""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    DEFAULT_BASE_SLIPPAGE_BPS,
    DEFAULT_FEE_BPS,
    DEFAULT_LIMIT_ORDER_TTL,
    DEFAULT_PROPORTIONAL_FACTOR,
)


class SimulatorConfig(BaseModel):
    """Paper trading simulation: slippage, fees, and order TTL."""

    base_slippage_bps: float = DEFAULT_BASE_SLIPPAGE_BPS
    proportional_factor: float = DEFAULT_PROPORTIONAL_FACTOR
    fee_bps: float = DEFAULT_FEE_BPS
    limit_order_ttl: int = DEFAULT_LIMIT_ORDER_TTL
