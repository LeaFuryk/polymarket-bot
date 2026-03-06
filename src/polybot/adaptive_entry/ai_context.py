"""AI prompt context generation for adaptive entry.

Builds the reversal rate / signal interpretation section that gets
injected into the Claude prompt.
"""

from __future__ import annotations

from polybot.adaptive_entry.constants import WILD_MARKET_FAKEOUT_FACTOR
from polybot.adaptive_entry.models import CandleOutcome


def build_ai_context(
    history: list[CandleOutcome],
    window: int,
    signal_type: str,
    btc_threshold: float,
    using_fakeout: bool,
    fakeout_p75: float,
    fakeout_max: float,
    fakeout_median: float,
    adaptive_cap: float,
    abs_btc_move: float = 0.0,
) -> str | None:
    """Build reversal rate context for the AI prompt.

    Returns None if insufficient history.
    """
    recent = history[-window:]
    if len(recent) < window:
        return None

    reversals = sum(1 for c in recent if c.reversed)
    rate = reversals / len(recent)

    lines = [
        "## Reversal Rate Context (Adaptive Entry)",
        f"- Rolling reversal rate: **{rate:.0%}** "
        f"({reversals} of last {len(recent)} candles showed 80%+ retracement from initial commitment)",
        f"- Signal type: **{signal_type}**",
        f"- BTC move threshold: ${btc_threshold:.0f}",
    ]

    if using_fakeout:
        lines.append(
            f"- Fakeout noise: P75=${fakeout_p75:.0f}, "
            f"max=${fakeout_max:.0f}, median=${fakeout_median:.0f} "
            f"(adaptive cap=${adaptive_cap:.0f}, threshold=${btc_threshold:.0f})"
        )

    # Wild market advisory
    if using_fakeout and fakeout_max > btc_threshold * WILD_MARKET_FAKEOUT_FACTOR:
        pct_above = ((fakeout_max / btc_threshold) - 1) * 100
        lines.extend(
            [
                "",
                f"\U0001f30a **HIGH-VOLATILITY MARKET**: Recent fakeouts reached "
                f"${fakeout_max:.0f} — {pct_above:.0f}% above the "
                f"${btc_threshold:.0f} threshold. "
                f"Even moves that clear the threshold may reverse. Wait for sustained "
                f"confirmation (15-20s above threshold) rather than entering immediately. "
                f"The 150-200s window has historically outperformed early entries in wild markets.",
            ]
        )

    if rate > 0.60:
        avg_ask = _avg_reversal_winner_ask(recent)
        lines.extend(
            [
                "",
                f"\u26a0 **High reversal rate ({rate:.0%})**: The initial commitment "
                f"has been WRONG {rate:.0%} of the time recently. The cheap (contrarian) side — "
                f"opposite to the current BTC move — may be the better entry. "
                f"When reversals dominated, the winning side's average ask was "
                f"${avg_ask:.2f} at the $20 cross.",
            ]
        )
    elif rate >= 0.40:
        if abs_btc_move >= btc_threshold:
            lines.extend(
                [
                    "",
                    f"\u26a0 **Uncertain reversal history ({rate:.0%} at initial cross)** but BTC has moved "
                    f"**${abs_btc_move:.0f}** — past the fakeout threshold (${btc_threshold:.0f}). "
                    f"The reversal rate was measured at the initial cross; moves beyond "
                    f"${btc_threshold:.0f} have cleared typical fakeout noise. "
                    f"Momentum entries are favored over contrarian.",
                    "",
                    "\u23f3 **Entry timing**: BTC has cleared fakeout noise, but uncertain regimes still show elevated "
                    "reversal risk on very early entries (>200s). Size down or wait for brief confirmation if "
                    "confidence is marginal.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    f"\u26a0 **Uncertain market ({rate:.0%} reversal)**: Direction has been unreliable. "
                    f"When both sides are priced near even (both asks $0.35\u2013$0.65), "
                    f"**lean toward the cheaper side** \u2014 at ~50% accuracy, only cheap entries are profitable. "
                    f"An entry at $0.35 profits +$0.15/trade at 50%; $0.60 loses -$0.10/trade at 50%. "
                    f"However, if one side is clearly confirmed by price (e.g., $0.90 vs $0.10), "
                    f"trust the market signal \u2014 the cheap side is cheap for a reason. "
                    f"This applies mainly to early-candle balanced prices, not late confirmations.",
                    "",
                    "\u23f3 **Entry timing**: Early entries (>200s remaining) in uncertain regimes have historically "
                    "underperformed. The 150-200s window offers better directional clarity. If the current move "
                    "is marginal, consider waiting for stronger confirmation.",
                ]
            )
    elif rate < 0.25:
        lines.extend(
            [
                "",
                f"\u2713 **Low reversal rate ({rate:.0%})**: BTC rarely retraces from initial commitment. "
                f"The initial move is continuing {1 - rate:.0%} of the time. "
                f"Momentum entries aligned with the current BTC direction are favored.",
            ]
        )

    return "\n".join(lines)


def _avg_reversal_winner_ask(window: list[CandleOutcome]) -> float:
    """Average winner ask price on reversed candles in the window."""
    asks = [c.winner_ask_at_20 for c in window if c.reversed and c.winner_ask_at_20 > 0]
    return sum(asks) / len(asks) if asks else 0.0
