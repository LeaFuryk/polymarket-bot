"""Domain model for bet tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BetEntry:
    """Single entry within a candle bet."""

    price: float
    amount_usd: float
    elapsed_pct: float
    confidence: float
    checkpoint: int  # 1-indexed entry number


@dataclass
class BetRecord:
    """Complete record of a bet on one candle."""

    candle_id: str
    direction: str  # "UP" | "DOWN"
    outcome: str  # "UP" | "DOWN"
    won: bool
    entries: list[BetEntry] = field(default_factory=list)
    pnl: float = 0.0  # realized PnL from this bet
    timestamp: float = 0.0  # candle close timestamp
