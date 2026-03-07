"""Data models for the adaptive_entry package."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CandleOutcome:
    """Resolved candle outcome for adaptive learning."""

    slug: str
    winner: str  # "up" or "down"
    btc_open: float
    btc_close: float
    direction_at_20: str  # Initial BTC direction (for entry price capture)
    reversed: bool  # BTC retraced 80%+ from initial commitment
    winner_ask_at_20: float  # ask price for the winning side at the $20 cross
    peak_up_move: float = 0.0  # max positive btc_move_from_open during candle
    peak_down_move: float = 0.0  # max abs(negative btc_move_from_open) during candle
