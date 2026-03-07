"""Retracement-based reversal detection.

Identifies whether a candle's initial BTC commitment was reversed by
checking for threshold crossing (momentum confirmed) or 80%+ retracement
with acceleration (reversal detected).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from polybot.adaptive_entry.constants import (
    INITIAL_DIRECTION_MIN_MOVE,
    MIN_PEAK_COMMIT,
    NEAR_ZERO_GUARD,
    RETRACEMENT_THRESHOLD,
    VELOCITY_SAMPLE_SEC,
)


@dataclass
class ReversalResult:
    """Output of reversal detection for a single candle."""

    initial_direction: str  # "up" or "down"
    reversed: bool
    threshold_crossed: bool
    retracement_reversal: bool
    peak_up_move: float
    peak_down_move: float
    winner_ask_at_20: float


def detect_reversal(
    winner: str,
    btc_open: float,
    btc_close: float,
    prefilter_history: list[Any],
    btc_threshold: float,
) -> ReversalResult:
    """Detect whether a candle reversed from its initial BTC commitment.

    Args:
        winner: "up" or "down" — the resolved winner.
        btc_open: BTC price at candle open.
        btc_close: BTC price at candle close.
        prefilter_history: List of PreFilterSnapshot objects with
            `btc_move_from_open`, `best_entry_up`, `best_entry_down`.
        btc_threshold: Current adaptive BTC threshold for momentum confirmation.

    Returns:
        ReversalResult with all detection outputs.
    """
    # 1. Compute peak up/down moves
    peak_up_move = 0.0
    peak_down_move = 0.0
    for snap in prefilter_history:
        move = snap.btc_move_from_open
        if move > peak_up_move:
            peak_up_move = move
        if move < 0 and abs(move) > peak_down_move:
            peak_down_move = abs(move)

    # 2. Identify initial BTC direction
    initial_direction = ""
    for snap in prefilter_history:
        if abs(snap.btc_move_from_open) > INITIAL_DIRECTION_MIN_MOVE:
            initial_direction = "up" if snap.btc_move_from_open > 0 else "down"
            break
    if not initial_direction:
        initial_direction = "up" if (btc_close - btc_open) >= 0 else "down"

    # 3. Capture winner ask at threshold crossing
    winner_ask_at_20 = 0.0
    for snap in prefilter_history:
        if abs(snap.btc_move_from_open) >= btc_threshold:
            winner_ask_at_20 = snap.best_entry_up if winner == "up" else snap.best_entry_down
            break
    if not winner_ask_at_20 and prefilter_history:
        last_snap = prefilter_history[-1]
        winner_ask_at_20 = last_snap.best_entry_up if winner == "up" else last_snap.best_entry_down

    # 4. Scan for threshold crossing or 80% retracement + acceleration
    sign = 1.0 if initial_direction == "up" else -1.0
    max_dir_move = 0.0
    threshold_crossed = False
    retracement_reversal = False
    retreat_positions: list[float] = []
    peak_index = 0

    for i, snap in enumerate(prefilter_history):
        dir_move = snap.btc_move_from_open * sign

        if dir_move > max_dir_move:
            max_dir_move = dir_move
            peak_index = i
            retreat_positions = []

        if dir_move >= btc_threshold:
            threshold_crossed = True
            break

        if i > peak_index and (i - peak_index) % VELOCITY_SAMPLE_SEC == 0:
            retreat_positions.append(dir_move)

        if max_dir_move >= MIN_PEAK_COMMIT and dir_move < max_dir_move:
            remaining_ratio = dir_move / max_dir_move
            if remaining_ratio < (1.0 - RETRACEMENT_THRESHOLD):
                if dir_move <= 0:
                    retracement_reversal = True
                    break
                if len(retreat_positions) >= 3:
                    half = len(retreat_positions) // 2
                    avg_first = sum(retreat_positions[:half]) / half
                    avg_second = sum(retreat_positions[half:]) / (len(retreat_positions) - half)
                    if avg_second < avg_first:
                        retracement_reversal = True
                        break

    # 5. Determine reversed flag
    if threshold_crossed or retracement_reversal:
        reversed_flag = initial_direction != winner
    else:
        reversed_flag = False

    # Near-zero guard
    if abs(btc_close - btc_open) < NEAR_ZERO_GUARD:
        reversed_flag = False

    return ReversalResult(
        initial_direction=initial_direction,
        reversed=reversed_flag,
        threshold_crossed=threshold_crossed,
        retracement_reversal=retracement_reversal,
        peak_up_move=peak_up_move,
        peak_down_move=peak_down_move,
        winner_ask_at_20=winner_ask_at_20,
    )
