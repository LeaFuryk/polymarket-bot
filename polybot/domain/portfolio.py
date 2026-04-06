"""Domain models for portfolio tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    """Shares held in one side of a binary market."""

    side: str  # "UP" | "DOWN"
    shares: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class PortfolioState:
    """Complete portfolio snapshot."""

    cash: float
    up_position: Position = field(default_factory=lambda: Position(side="UP"))
    down_position: Position = field(default_factory=lambda: Position(side="DOWN"))
    wins: int = 0
    losses: int = 0

    def total_value(self, up_price: float, down_price: float) -> float:
        return self.cash + self.up_position.shares * up_price + self.down_position.shares * down_price

    def unrealized_pnl(self, up_price: float, down_price: float) -> float:
        up_unreal = self.up_position.shares * (up_price - self.up_position.avg_entry_price)
        down_unreal = self.down_position.shares * (down_price - self.down_position.avg_entry_price)
        return up_unreal + down_unreal

    def net_pnl(self, up_price: float, down_price: float) -> float:
        realized = self.up_position.realized_pnl + self.down_position.realized_pnl
        return realized + self.unrealized_pnl(up_price, down_price)
