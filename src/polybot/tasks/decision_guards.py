"""Pure decision guard functions — validate and adjust AI decisions.

Each guard takes a TradingDecision (and relevant context) and returns
a possibly-modified TradingDecision.  No side effects, no class state.
"""

from __future__ import annotations

import logging

from polybot.models import Action, OrderType, TokenSide, TradingDecision
from polybot.tasks.prompt_context import VelocityConflict

logger = logging.getLogger(__name__)


def override_to_hold(
    decision: TradingDecision,
    reason: str,
) -> TradingDecision:
    """Replace *decision* with a HOLD, preserving metadata."""
    return TradingDecision(
        action=Action.HOLD,
        order_type=OrderType.MARKET,
        size=0.0,
        confidence=decision.confidence,
        reasoning=reason,
        market_view=decision.market_view,
        token_side=decision.token_side,
        hypothetical_direction=decision.hypothetical_direction,
        confidence_drivers=decision.confidence_drivers,
    )


def clamp_sell_size(
    decision: TradingDecision,
    held_shares: float,
    *,
    log: logging.Logger | None = None,
) -> TradingDecision:
    """Clamp a SELL decision's size to the actually held shares."""
    if decision.action != Action.SELL:
        return decision
    if decision.size <= held_shares or held_shares <= 0:
        return decision

    _log = log or logger
    _log.info(
        "Clamping sell size: %.2f → %.2f (held) for %s",
        decision.size,
        held_shares,
        decision.token_side.value,
    )
    return TradingDecision(
        action=decision.action,
        order_type=decision.order_type,
        size=held_shares,
        confidence=decision.confidence,
        reasoning=decision.reasoning,
        market_view=decision.market_view,
        token_side=decision.token_side,
        hypothetical_direction=decision.hypothetical_direction,
        confidence_drivers=decision.confidence_drivers,
    )


def force_exit_side(
    decision: TradingDecision,
    forced_side: str | None,
    *,
    log: logging.Logger | None = None,
) -> TradingDecision:
    """Force the token_side on exit-trigger SELLs to match the trigger."""
    if not forced_side or decision.action != Action.SELL:
        return decision

    correct_side = TokenSide(forced_side.lower())
    if decision.token_side == correct_side:
        return decision

    _log = log or logger
    _log.warning(
        "Forcing exit token_side: AI said %s but exit trigger is %s",
        decision.token_side.value,
        correct_side.value,
    )
    return TradingDecision(
        action=decision.action,
        order_type=decision.order_type,
        size=decision.size,
        confidence=decision.confidence,
        reasoning=decision.reasoning,
        market_view=decision.market_view,
        token_side=correct_side,
        hypothetical_direction=decision.hypothetical_direction,
        confidence_drivers=decision.confidence_drivers,
    )


def apply_confidence_gate(
    decision: TradingDecision,
    min_confidence: float,
    *,
    log: logging.Logger | None = None,
) -> TradingDecision:
    """Override BUY to HOLD if confidence is below the minimum threshold."""
    if decision.action != Action.BUY:
        return decision
    if decision.confidence >= min_confidence:
        return decision

    _log = log or logger
    _log.info(
        "Overriding %s to HOLD — confidence %.2f < %.2f",
        decision.action.value,
        decision.confidence,
        min_confidence,
    )
    return override_to_hold(
        decision,
        f"Overridden: confidence {decision.confidence:.2f} below {min_confidence}. "
        f"Original: {decision.reasoning[:100]}",
    )


def apply_entry_price_cap(
    decision: TradingDecision,
    ask_price: float,
    *,
    cap: float = 0.85,
    log: logging.Logger | None = None,
) -> TradingDecision:
    """Block BUY entries when the ask price exceeds *cap* (R/R too low)."""
    if decision.action != Action.BUY:
        return decision
    if ask_price < cap:
        return decision

    rr = (1.0 - ask_price) / ask_price if ask_price > 0 else 0
    _log = log or logger
    _log.info(
        "Entry price cap: %s ask $%.2f >= $%.2f (R/R=%.2f), overriding to HOLD",
        decision.token_side.value,
        ask_price,
        cap,
        rr,
    )
    return override_to_hold(
        decision,
        f"Entry price cap: ${ask_price:.2f} >= ${cap:.2f} (R/R too low). Original: {decision.reasoning[:80]}",
    )


def apply_anti_flip(
    decision: TradingDecision,
    sold_sides: set[str],
    *,
    log: logging.Logger | None = None,
    slug: str = "",
) -> TradingDecision:
    """Block BUY of opposite side after selling on the same candle."""
    if decision.action != Action.BUY:
        return decision
    opposite = "UP" if decision.token_side == TokenSide.DOWN else "DOWN"
    if opposite not in sold_sides:
        return decision

    _log = log or logger
    _log.info(
        "Anti-flip block: already sold %s on %s, blocking %s buy",
        opposite,
        slug,
        decision.token_side.value,
    )
    return override_to_hold(
        decision,
        f"Anti-flip: sold {opposite} on this candle, blocked {decision.token_side.value} buy. "
        f"Original: {decision.reasoning[:80]}",
    )


def apply_single_entry(
    decision: TradingDecision,
    bought_sides: set[str],
    *,
    log: logging.Logger | None = None,
    slug: str = "",
) -> TradingDecision:
    """Block buying the same side twice on the same candle."""
    if decision.action != Action.BUY:
        return decision
    side_key = decision.token_side.value.upper()
    if side_key not in bought_sides:
        return decision

    _log = log or logger
    _log.info(
        "Single-entry block: already bought %s on %s, overriding to HOLD",
        side_key,
        slug,
    )
    return override_to_hold(
        decision,
        f"Single-entry: already bought {side_key} on this candle. Original: {decision.reasoning[:80]}",
    )


def compute_position_scale(
    rr_ratio: float,
    btc_move: float,
    trend_score: float | None,
    decision_side: TokenSide,
) -> tuple[float, float]:
    """Compute combined position sizing scale and counter-trend scale.

    Returns (combined_scale, trend_scale).
    """
    # R/R scale — gentle nudge (0.75-1.0)
    if rr_ratio >= 1.0:
        rr_scale = 1.0
    elif rr_ratio >= 0.3:
        rr_scale = 0.75 + 0.25 * (rr_ratio - 0.3) / 0.7
    else:
        rr_scale = 0.75

    # Move-magnitude scaling
    if btc_move < 10:
        move_scale = 0.80
    elif btc_move < 30:
        move_scale = 0.90
    elif btc_move < 60:
        move_scale = 1.0
    else:
        move_scale = 1.0

    # Counter-trend scaling
    trend_scale = 1.0
    if trend_score is not None:
        is_counter = (decision_side == TokenSide.DOWN and trend_score > 0.3) or (
            decision_side == TokenSide.UP and trend_score < -0.3
        )
        if is_counter:
            abs_score = abs(trend_score)
            trend_scale = 0.50 if abs_score >= 0.7 else 0.70

    combined = rr_scale * move_scale * trend_scale
    return combined, trend_scale


def apply_position_sizing(
    decision: TradingDecision,
    scale: float,
    trend_scale: float,
    *,
    log: logging.Logger | None = None,
) -> TradingDecision:
    """Apply combined position scale and enforce minimum size."""
    if decision.action != Action.BUY:
        return decision

    _log = log or logger
    min_shares = 20 if trend_scale < 1.0 else 40

    if scale < 1.0:
        scaled_size = round(decision.size * scale, 1)
        if scaled_size >= 1.0:
            _log.info(
                "Position sizing: %.1f → %.1f (scale=%.2f)",
                decision.size,
                scaled_size,
                scale,
            )
            decision = TradingDecision(
                action=decision.action,
                order_type=decision.order_type,
                size=scaled_size,
                confidence=decision.confidence,
                reasoning=decision.reasoning,
                market_view=decision.market_view,
                token_side=decision.token_side,
                limit_price=decision.limit_price,
            )

    if decision.size < min_shares:
        _log.info(
            "Min size floor: %.1f → %d shares%s",
            decision.size,
            min_shares,
            " (counter-trend)" if trend_scale < 1.0 else "",
        )
        decision = TradingDecision(
            action=decision.action,
            order_type=decision.order_type,
            size=min_shares,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            market_view=decision.market_view,
            token_side=decision.token_side,
            limit_price=decision.limit_price,
        )

    return decision


def apply_velocity_conflict_scaling(
    decision: TradingDecision,
    conflict: VelocityConflict,
    *,
    log: logging.Logger | None = None,
) -> TradingDecision:
    """Scale BUY size down when velocity conflicts with magnitude.

    Only affects BUYs that align with the magnitude direction — i.e.,
    the trade is going with magnitude but against velocity.

    Strong conflict (>=0.7): scale to 50%.
    Moderate conflict (>=0.4): scale to 75%.
    """
    if decision.action != Action.BUY:
        return decision
    if not conflict.has_conflict or conflict.severity < 0.4:
        return decision

    # Only scale when the BUY direction aligns with magnitude (trading against velocity)
    buy_dir = "UP" if decision.token_side == TokenSide.UP else "DOWN"
    if buy_dir != conflict.magnitude_direction:
        return decision

    scale = 0.50 if conflict.severity >= 0.7 else 0.75
    scaled_size = round(decision.size * scale, 1)
    if scaled_size < 1.0:
        scaled_size = 1.0

    _log = log or logger
    _log.info(
        "Velocity conflict scaling: %.1f → %.1f (scale=%.2f, severity=%.0f%%)",
        decision.size,
        scaled_size,
        scale,
        conflict.severity * 100,
    )
    return TradingDecision(
        action=decision.action,
        order_type=decision.order_type,
        size=scaled_size,
        confidence=decision.confidence,
        reasoning=decision.reasoning,
        market_view=decision.market_view,
        token_side=decision.token_side,
        hypothetical_direction=decision.hypothetical_direction,
        confidence_drivers=decision.confidence_drivers,
    )


def apply_reversal_regime_scaling(
    decision: TradingDecision,
    reversal_score: float,
    *,
    log: logging.Logger | None = None,
) -> TradingDecision:
    """Scale BUY size down when in a reversal regime.

    HIGH_REVERSAL (>=0.6): scale to 50%.
    MODERATE_REVERSAL (>=0.35): scale to 75%.
    Below 0.35: no-op.
    """
    if decision.action != Action.BUY:
        return decision
    if reversal_score < 0.35:
        return decision

    scale = 0.50 if reversal_score >= 0.6 else 0.75
    scaled_size = round(decision.size * scale, 1)
    if scaled_size < 1.0:
        scaled_size = 1.0

    _log = log or logger
    _log.info(
        "Reversal regime scaling: %.1f → %.1f (scale=%.2f, score=%.2f)",
        decision.size,
        scaled_size,
        scale,
        reversal_score,
    )
    return TradingDecision(
        action=decision.action,
        order_type=decision.order_type,
        size=scaled_size,
        confidence=decision.confidence,
        reasoning=decision.reasoning,
        market_view=decision.market_view,
        token_side=decision.token_side,
        hypothetical_direction=decision.hypothetical_direction,
        confidence_drivers=decision.confidence_drivers,
    )
