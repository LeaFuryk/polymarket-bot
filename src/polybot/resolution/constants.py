"""Thresholds and defaults for resolution logic."""

from __future__ import annotations

# Polymarket winner-determination thresholds
# After resolution: winning token → ~$1, losing → ~$0
WINNER_HIGH_CONFIDENCE: float = 0.85  # price above this → strong winner signal
WINNER_LOW_CONFIDENCE: float = 0.65  # price above this → weaker but clear signal
LOSER_HIGH_CONFIDENCE: float = 0.15  # price below this → strong loser signal
LOSER_LOW_CONFIDENCE: float = 0.35  # price below this → weaker loser signal

# Delay before checking Polymarket prices (seconds)
VERIFICATION_DELAY: float = 3.0
