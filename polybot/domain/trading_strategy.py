"""Domain model for trading strategy configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TradingStrategy:
    """Immutable strategy config loaded from optimal_strategy_*.json.

    Dual-mode strategy:
    - Signal mode: BTC has moved >= min_btc_move from open → use model prediction
    - Noise mode: BTC hasn't moved enough → bet the cheap side (better R/R on coin flips)
    """

    name: str
    entry_points: tuple[tuple[float, int], ...]
    min_confidence: float
    min_btc_move: float  # minimum BTC move from open to use model (e.g., 0.0003 = 0.03%)
    noise_entry_elapsed: float  # when to enter cheap side on noise candles (e.g., 0.30)

    @classmethod
    def from_json(cls, path: str, name: str) -> TradingStrategy:
        with open(path) as f:
            config = json.load(f)
        return cls(
            name=name,
            entry_points=tuple((float(ep[0]), int(ep[1])) for ep in config["entry_points"]),
            min_confidence=float(config.get("min_confidence", 0.0)),
            min_btc_move=float(config.get("min_btc_move", 0.0003)),
            noise_entry_elapsed=float(config.get("noise_entry_elapsed", 0.30)),
        )
