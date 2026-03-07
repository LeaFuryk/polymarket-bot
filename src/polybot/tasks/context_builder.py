"""Pure functions that build AI decision context sections.

These format ML predictions, safeguard warnings, and advisory sections
for injection into the indicators text shown to the AI.
"""

from __future__ import annotations

from polybot.tasks.prompt_context import VelocityConflict


def append_section(base: str, section: str | None) -> str:
    """Append a context *section* to *base*, separated by blank line."""
    if not section:
        return base
    if base:
        return base + "\n\n" + section
    return section


def format_ml_line(
    *,
    model_trained: bool,
    up_probability: float = 0.0,
    confidence: str = "",
    feature_contributions: dict[str, float] | None = None,
    scorer_summary: str = "",
) -> str:
    """Format a one-line ML prediction summary for the indicators block."""
    if model_trained:
        contributions = feature_contributions or {}
        top_feats = sorted(
            contributions.items(),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:3]
        drivers = ", ".join(f"{n}: {v:+.2f}" for n, v in top_feats)
        return f"- ML Baseline: {up_probability:.0%} UP probability ({confidence}) — drivers: {drivers}"
    return f"- ML Baseline: {scorer_summary}"


def build_chainlink_warning(divergence: float) -> str | None:
    """Return a chainlink divergence warning if |divergence| > $100, else None."""
    if abs(divergence) <= 100:
        return None
    return (
        "## CHAINLINK DIVERGENCE WARNING\n"
        f"Chainlink vs Binance divergence: ${divergence:+.0f} — "
        "resolution source may differ significantly.\n"
        "Consider reducing confidence. Trades near candle boundaries are especially risky."
    )


def build_counter_trend_advisory(trend_value: float) -> str | None:
    """Return a counter-trend advisory if |trend_value| >= 0.3, else None."""
    if abs(trend_value) < 0.3:
        return None
    weak_side = "DOWN" if trend_value > 0 else "UP"
    trend_label = "BULLISH" if trend_value > 0 else "BEARISH"
    return (
        "## Counter-Trend Advisory\n"
        f"Strong {trend_label} trend detected (score={trend_value:+.2f}). "
        f"{weak_side} trades are counter-trend.\n"
        "Historical counter-trend accuracy: ~55-60% (vs ~75% trend-aligned).\n"
        "If going counter-trend, require higher conviction and use smaller size."
    )


def build_velocity_conflict_warning(conflict: VelocityConflict) -> str | None:
    """Return a velocity-magnitude conflict warning if severity >= 0.3, else None."""
    if conflict.severity < 0.3:
        return None

    if conflict.severity >= 0.7:
        return (
            "## VELOCITY-MAGNITUDE CONFLICT WARNING\n"
            f"BTC magnitude says {conflict.magnitude_direction} (${conflict.btc_move:+,.0f}) "
            f"but velocity is ${conflict.velocity_rate:+.1f}/s ({conflict.velocity_direction}).\n"
            f"Drawback: {conflict.drawback_pct:.0%} of peak recovered | "
            f"Severity: {conflict.severity:.0%} | {conflict.time_remaining:.0f}s left\n"
            "The magnitude signal is STALE — do NOT trust magnitude alone. "
            "Reduce size or skip this entry."
        )

    return (
        "## Velocity-Magnitude Conflict\n"
        f"BTC magnitude says {conflict.magnitude_direction} (${conflict.btc_move:+,.0f}) "
        f"but velocity is ${conflict.velocity_rate:+.1f}/s ({conflict.velocity_direction}).\n"
        f"Drawback: {conflict.drawback_pct:.0%} of peak | "
        f"Severity: {conflict.severity:.0%} | {conflict.time_remaining:.0f}s left\n"
        "Reduce confidence and size — magnitude may not hold through resolution."
    )


def build_stop_loss_warning(token_side: str, pnl_pct: float) -> str:
    """Return a post-stop-loss cooldown warning."""
    return (
        "## POST-STOP-LOSS WARNING\n"
        "A stop-loss exit just occurred on this candle "
        f"({token_side.upper()} at {pnl_pct:+.1%}).\n"
        "Re-entering immediately is high-risk — the price moved against you and may continue.\n"
        "If you choose to re-enter, use smaller size and higher conviction threshold."
    )
