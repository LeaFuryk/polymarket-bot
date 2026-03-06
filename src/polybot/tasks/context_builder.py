"""Pure functions that build AI decision context sections.

These format ML predictions, safeguard warnings, and advisory sections
for injection into the indicators text shown to the AI.
"""

from __future__ import annotations


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


def build_stop_loss_warning(token_side: str, pnl_pct: float) -> str:
    """Return a post-stop-loss cooldown warning."""
    return (
        "## POST-STOP-LOSS WARNING\n"
        "A stop-loss exit just occurred on this candle "
        f"({token_side.upper()} at {pnl_pct:+.1%}).\n"
        "Re-entering immediately is high-risk — the price moved against you and may continue.\n"
        "If you choose to re-enter, use smaller size and higher conviction threshold."
    )
