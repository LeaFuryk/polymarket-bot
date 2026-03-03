"""Pure resolution logic — no side effects, no I/O.

Determines candle winner from BTC prices and Polymarket token prices.
"""

from __future__ import annotations

from polybot.resolution.constants import (
    LOSER_HIGH_CONFIDENCE,
    LOSER_LOW_CONFIDENCE,
    WINNER_HIGH_CONFIDENCE,
    WINNER_LOW_CONFIDENCE,
)


def determine_btc_winner(btc_open: float, btc_close: float) -> str:
    """Determine winner from BTC open/close price comparison.

    Polymarket rule: "greater than or equal to" means UP wins on tie.
    """
    return "up" if btc_close >= btc_open else "down"


def determine_polymarket_winner(
    up_price: float | None,
    down_price: float | None,
) -> str | None:
    """Determine winner from Polymarket token prices after resolution.

    Returns "up", "down", or None if prices are ambiguous.
    After resolution, the winning token trades at ~$1 and the loser at ~$0.
    """
    if up_price is None or down_price is None:
        return None

    # Strong signal: winner > 0.85, loser < 0.15
    if up_price > WINNER_HIGH_CONFIDENCE and down_price < LOSER_HIGH_CONFIDENCE:
        return "up"
    if down_price > WINNER_HIGH_CONFIDENCE and up_price < LOSER_HIGH_CONFIDENCE:
        return "down"

    # Weaker but still clear signal
    if up_price > WINNER_LOW_CONFIDENCE and down_price < LOSER_LOW_CONFIDENCE:
        return "up"
    if down_price > WINNER_LOW_CONFIDENCE and up_price < LOSER_LOW_CONFIDENCE:
        return "down"

    return None
