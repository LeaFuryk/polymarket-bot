"""Domain model for trading strategy configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TradingStrategy:
    """Immutable strategy config loaded from optimal_strategy_*.json."""

    name: str
    entry_points: tuple[tuple[float, int], ...]
    min_confidence: float

    @classmethod
    def from_json(cls, path: str, name: str) -> TradingStrategy:
        with open(path) as f:
            config = json.load(f)
        return cls(
            name=name,
            entry_points=tuple((float(ep[0]), int(ep[1])) for ep in config["entry_points"]),
            min_confidence=float(config.get("min_confidence", 0.0)),
        )
