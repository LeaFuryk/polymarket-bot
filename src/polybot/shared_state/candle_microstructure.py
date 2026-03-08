"""End-of-candle microstructure summary for cross-candle memory."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.shared_state.constants import DEFAULT_AVG_IMBALANCE


@dataclass
class CandleMicrostructure:
    """End-of-candle microstructure summary for cross-candle memory."""

    timestamp: float = 0.0
    avg_spread_up: float = 0.0
    avg_spread_down: float = 0.0
    avg_depth: float = 0.0
    avg_imbalance: float = DEFAULT_AVG_IMBALANCE
    btc_range: float = 0.0  # high - low of BTC move within candle
    btc_final_move: float = 0.0
    zero_crossings: int = 0  # times BTC move_from_open crossed zero
    reversal_intensity: float = 0.0  # 1 - |final_move| / range (0=directional, 1=whipsaw)
