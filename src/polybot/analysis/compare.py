"""Cross-iteration comparison — reads archived summaries and prints a Rich table."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

ARCHIVE_DIR = Path.cwd() / "archive"


def _load_summaries() -> list[dict]:
    """Scan archive/*/summary.json and return sorted by label."""
    if not ARCHIVE_DIR.exists():
        return []
    summaries = []
    for d in sorted(ARCHIVE_DIR.iterdir()):
        summary_file = d / "summary.json"
        if d.is_dir() and summary_file.exists():
            with open(summary_file) as fh:
                summaries.append(json.load(fh))
    return summaries


def _format_date(val: str | float | None) -> str:
    """Extract YYYY-MM-DD from an ISO string, epoch float, or return empty."""
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=UTC).strftime("%m/%d")
    return str(val)[5:10]


def _fmt_pct(val: float) -> str:
    return f"{val:.1%}"


def _fmt_dollar(val: float) -> str:
    return f"${val:+,.2f}"


def _delta_str(current: float, previous: float, is_pct: bool = False) -> str:
    """Format a delta value with color markup."""
    diff = current - previous
    if abs(diff) < 0.001:
        return ""
    if is_pct:
        text = f"{diff:+.1%}"
    else:
        text = f"{diff:+,.2f}"
    color = "green" if diff > 0 else "red"
    return f"[{color}]{text}[/{color}]"


def _delta_str_inverted(current: float, previous: float) -> str:
    """Format a delta where lower is better (fees, costs)."""
    diff = current - previous
    if abs(diff) < 0.001:
        return ""
    text = f"{diff:+,.2f}"
    color = "green" if diff < 0 else "red"
    return f"[{color}]{text}[/{color}]"


def main() -> None:
    """Entry point for polybot-compare CLI."""
    console = Console()
    summaries = _load_summaries()

    if not summaries:
        console.print("[yellow]No archived iterations found in archive/[/yellow]")
        sys.exit(0)

    table = Table(title="Iteration Comparison")
    table.add_column("Label", style="cyan", no_wrap=True)
    table.add_column("Dates", style="dim", no_wrap=True)
    table.add_column("Candles", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right", no_wrap=True)
    table.add_column("PnL", justify="right", no_wrap=True)
    table.add_column("Fees", justify="right", no_wrap=True)
    table.add_column("AI Cost", justify="right", no_wrap=True)
    table.add_column("Net", justify="right", no_wrap=True)

    prev: dict | None = None
    for s in summaries:
        # Date range
        dr = s.get("date_range", {})
        start = _format_date(dr.get("start"))
        end = _format_date(dr.get("end"))
        date_range = f"{start} → {end}" if start else "—"

        # Win rate with delta
        wr = s.get("win_rate", 0.0)
        wr_str = _fmt_pct(wr)
        if prev is not None:
            d = _delta_str(wr, prev.get("win_rate", 0.0), is_pct=True)
            if d:
                wr_str += f" {d}"

        # PnL with delta
        pnl = s.get("total_pnl", 0.0)
        pnl_str = _fmt_dollar(pnl)
        if prev is not None:
            d = _delta_str(pnl, prev.get("total_pnl", 0.0))
            if d:
                pnl_str += f" {d}"

        # Fees
        fees = s.get("total_fees", 0.0)
        fees_str = f"${fees:,.2f}"

        # AI cost
        ai_cost = s.get("ai_cost", 0.0)
        ai_str = f"${ai_cost:,.2f}"

        # Net result with delta
        net = s.get("net_result", 0.0)
        net_str = _fmt_dollar(net)
        if prev is not None:
            d = _delta_str(net, prev.get("net_result", 0.0))
            if d:
                net_str += f" {d}"

        table.add_row(
            s.get("label", "?"),
            date_range,
            str(s.get("total_candles", 0)),
            str(s.get("total_trades", 0)),
            wr_str,
            pnl_str,
            fees_str,
            ai_str,
            net_str,
        )
        prev = s

    console.print()
    console.print(table)
    console.print()


if __name__ == "__main__":
    main()
