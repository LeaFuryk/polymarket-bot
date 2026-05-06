"""Domain model for trading strategy configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TradingStrategy:
    """Immutable edge-based strategy config loaded from optimal_strategy_*.json.

    Edge = model_confidence - ask_price.  A bet is placed when the edge
    exceeds *min_edge* and BTC has moved >= *min_btc_move* from candle open.
    Up to *max_entries* scaling-in entries are allowed per candle.
    """

    name: str
    min_edge: float  # minimum edge (confidence - ask) to enter (e.g. 0.05)
    max_entries: int  # max scaling-in entries per candle (e.g. 2)
    min_btc_move: float  # minimum BTC move from open to use model (e.g. 0.0003 = 0.03%)
    edge_threshold: float = 0.05  # consensus: minimum edge for agreement threshold
    min_agreement: int = 2  # consensus: minimum number of models that must agree

    @classmethod
    def from_json(cls, path: str, name: str) -> TradingStrategy:
        with open(path) as f:
            config = json.load(f)

        if "entry_points" in config:
            raise ValueError(
                "Strategy uses old format (entry_points). Re-run the strategy notebook to generate edge-based config."
            )

        return cls(
            name=name,
            min_edge=float(config.get("min_edge", 0.05)),
            max_entries=int(config.get("max_entries", 1)),
            min_btc_move=float(config.get("min_btc_move", 0.0003)),
            edge_threshold=float(config.get("edge_threshold", 0.05)),
            min_agreement=int(config.get("min_agreement", 2)),
        )
