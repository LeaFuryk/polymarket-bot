"""Market conditions at entry (fill) time — used by dynamic SL/TP."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.shared_state.constants import DEFAULT_ML_CONFIDENCE, DEFAULT_ML_UP_PROBABILITY


@dataclass
class EntryContext:
    """Market conditions at entry (fill) time — used by dynamic SL/TP."""

    entry_price: float = 0.0
    entry_time: float = 0.0
    ml_up_probability: float = DEFAULT_ML_UP_PROBABILITY
    ml_confidence: str = DEFAULT_ML_CONFIDENCE
    btc_move_at_entry: float = 0.0
    reversal_rate_at_entry: float = 0.0
    confidence_at_entry: float = 0.0
