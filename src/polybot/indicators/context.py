"""IndicatorContext — frozen dataclass bundling all inputs for indicator computation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polybot.indicators.core import SessionContext
    from polybot.models import MarketSnapshot


@dataclass(frozen=True)
class IndicatorContext:
    """All inputs needed to compute a single indicator."""

    snapshot: MarketSnapshot
    params: dict[str, Any] = field(default_factory=dict)
    session: SessionContext | None = None
    candle_open_btc: float | None = None
    has_open_position: bool = False
    time_remaining: float = 0.0
    position_side: str = ""
    btc_candles: tuple = ()
    microstructure_history: tuple = ()
    session_trades: tuple = ()
    session_resolutions: tuple = ()
