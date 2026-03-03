"""Typed record for stop-loss exits, replacing untyped dicts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StopLossRecord:
    """Records a stop-loss exit for cooldown logic."""

    token_side: str
    pnl_pct: float
    timestamp: float
