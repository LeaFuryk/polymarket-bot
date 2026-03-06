"""Pure scorecard computation and formatting — no side effects."""

from __future__ import annotations

from polybot.knowledge.constants import PNL_THRESHOLD
from polybot.models import (
    ResolutionRecord,
    Scorecard,
    ScorecardDelta,
    TradeRecord,
)


def compute_scorecard(
    resolutions: list[ResolutionRecord],
    trades: list[TradeRecord],
) -> Scorecard:
    """Compute quantitative metrics from a batch of resolutions and trades."""
    if not resolutions:
        return Scorecard()

    # Count trades that had actual fills (not HOLDs)
    traded = [t for t in trades if t.fill_price is not None and t.action.value != "HOLD"]

    # Win/loss from resolutions (only those with positions)
    wins = [r for r in resolutions if r.total_pnl > PNL_THRESHOLD]
    losses = [r for r in resolutions if r.total_pnl < -PNL_THRESHOLD]
    total_with_position = len(wins) + len(losses)

    win_rate = len(wins) / total_with_position if total_with_position > 0 else 0.0

    # PnL stats
    win_pnls = [r.total_pnl for r in wins]
    loss_pnls = [r.total_pnl for r in losses]
    all_pnls = [r.total_pnl for r in resolutions if abs(r.total_pnl) > PNL_THRESHOLD]

    avg_pnl = sum(all_pnls) / len(all_pnls) if all_pnls else 0.0
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

    # Hold rate: fraction of resolutions where we had no position
    flat_count = len(resolutions) - total_with_position
    hold_rate = flat_count / len(resolutions) if resolutions else 0.0

    return Scorecard(
        resolutions=len(resolutions),
        trades_taken=len(traded),
        win_rate=win_rate,
        avg_pnl_per_trade=avg_pnl,
        avg_win_size=avg_win,
        avg_loss_size=avg_loss,
        hold_rate=hold_rate,
    )


def format_scorecard(delta: ScorecardDelta) -> str:
    """Format scorecard with optional delta comparison."""
    c = delta.current
    lines = [
        "### Current Batch",
        f"- Resolutions: {c.resolutions}",
        f"- Trades taken: {c.trades_taken}",
        f"- Win rate: {c.win_rate:.0%}",
        f"- Avg PnL per traded resolution: ${c.avg_pnl_per_trade:+.4f}",
        f"- Avg win size: ${c.avg_win_size:+.4f}",
        f"- Avg loss size: ${c.avg_loss_size:+.4f}",
        f"- Hold rate: {c.hold_rate:.0%}",
    ]

    p = delta.previous
    if p is not None and p.resolutions > 0:
        lines.append("")
        lines.append("### Previous Batch (for comparison)")
        wr_delta = c.win_rate - p.win_rate
        pnl_delta = c.avg_pnl_per_trade - p.avg_pnl_per_trade
        lines.append(f"- Win rate: {p.win_rate:.0%} -> {c.win_rate:.0%} ({wr_delta:+.0%})")
        lines.append(
            f"- Avg PnL: ${p.avg_pnl_per_trade:+.4f} -> ${c.avg_pnl_per_trade:+.4f} (delta: ${pnl_delta:+.4f})"
        )
        lines.append(f"- Trades taken: {p.trades_taken} -> {c.trades_taken}")
        hr_delta = c.hold_rate - p.hold_rate
        lines.append(f"- Hold rate: {p.hold_rate:.0%} -> {c.hold_rate:.0%} ({hr_delta:+.0%})")
    else:
        lines.append("")
        lines.append("### Previous Batch")
        lines.append("(no previous batch — this is the first reflection)")

    return "\n".join(lines)
