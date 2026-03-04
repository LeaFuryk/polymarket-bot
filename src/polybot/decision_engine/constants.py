"""Constants for the decision_engine package."""

from __future__ import annotations

from polybot.models import Action, OrderType, TradingDecision

# --- Fallback decision (returned when AI call fails) ---
HOLD_FALLBACK = TradingDecision(
    action=Action.HOLD,
    order_type=OrderType.MARKET,
    size=0.0,
    confidence=0.0,
    reasoning="Fallback: AI decision unavailable",
    market_view="neutral — unable to assess",
)

# --- Screening pass (Haiku) ---
SCREEN_MAX_TOKENS: int = 200
SCREEN_TEMPERATURE: float = 0.0
