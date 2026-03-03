"""Per-second market state recorded by the market monitor."""

from __future__ import annotations

from dataclasses import dataclass, field

from polybot.shared_state.constants import DEFAULT_BEST_ENTRY


@dataclass
class PreFilterSnapshot:
    """Records market state every second from the market monitor."""

    timestamp: float
    time_remaining: float
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    best_entry_up: float = DEFAULT_BEST_ENTRY
    best_entry_down: float = DEFAULT_BEST_ENTRY
    rr_up: float = 0.0
    rr_down: float = 0.0
    btc_price: float = 0.0
    up_mid: float | None = None
    down_mid: float | None = None
    up_spread_pct: float | None = None
    down_spread_pct: float | None = None
    streak: int = 0
    streak_direction: str = ""
    btc_move_from_open: float = 0.0
