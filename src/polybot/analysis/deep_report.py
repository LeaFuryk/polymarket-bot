"""Deep analysis report builder and CLI command.

Composes all deep analysis functions into a structured report,
renders via Rich, and optionally saves JSON output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polybot.analysis.deep import (
    analyze_entry_quality,
    analyze_flips,
    analyze_losses,
    analyze_missed_opportunities,
    analyze_side_accuracy,
    analyze_timing,
    analyze_trends,
    generate_recommendations,
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict]:
    """Load records from a JSONL file."""
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _find_file(directory: Path, pattern: str) -> Path | None:
    """Find the first file matching a glob pattern."""
    matches = sorted(directory.glob(pattern))
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_deep_report(
    iter_dir: Path,
    iterations: list[dict] | None = None,
) -> dict:
    """Build a complete deep analysis report from an archive directory.

    Args:
        iter_dir: Path to an ``archive/iter_NNN/`` directory.
        iterations: Optional list of all iteration summaries for trend
            analysis.  If *None*, trends are computed from this iteration only.

    Returns:
        Full report dict with all analysis sections.
    """
    logs_dir = iter_dir / "logs"

    # Load trades
    trades_file = _find_file(logs_dir, "trades_*.jsonl")
    trades = _load_jsonl(trades_file) if trades_file else []

    # Load resolutions
    res_file = _find_file(logs_dir, "resolutions_*.jsonl")
    resolutions = _load_jsonl(res_file) if res_file else []

    # Load summary
    summary = _load_json(iter_dir / "summary.json")

    # Run all analysis functions
    entry_quality = analyze_entry_quality(trades)
    side_accuracy = analyze_side_accuracy(trades, resolutions)
    losses = analyze_losses(trades, resolutions)
    flips = analyze_flips(trades)
    missed = analyze_missed_opportunities(trades, resolutions)
    timing = analyze_timing(trades, resolutions)

    iter_list = iterations or ([summary] if summary else [])
    trends = analyze_trends(iter_list)
    recommendations = generate_recommendations(
        entry_quality=entry_quality,
        side_accuracy=side_accuracy,
        losses=losses,
        flips=flips,
        missed=missed,
        trends=trends,
    )

    return {
        "iteration": summary.get("label", iter_dir.name),
        "summary": {
            "total_trades": len(trades),
            "total_resolutions": len(resolutions),
            "win_rate": summary.get("win_rate", 0),
            "total_pnl": summary.get("total_pnl", 0),
        },
        "entry_quality": entry_quality,
        "side_accuracy": side_accuracy,
        "losses": losses,
        "flips": flips,
        "missed_opportunities": missed,
        "timing": timing,
        "trends": trends,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# Rich rendering
# ---------------------------------------------------------------------------

_SEVERITY_COLORS = {"high": "red", "medium": "yellow", "low": "blue"}


def render_deep_report(report: dict, console: Console) -> None:
    """Render a deep analysis report to the console using Rich."""
    label = report.get("iteration", "unknown")
    summary = report.get("summary", {})

    # Header
    console.print(
        Panel(
            f"[bold]{label}[/bold]  |  "
            f"Trades: {summary.get('total_trades', 0)}  |  "
            f"Resolutions: {summary.get('total_resolutions', 0)}  |  "
            f"Win rate: {summary.get('win_rate', 0):.0%}  |  "
            f"PnL: {summary.get('total_pnl', 0):.4f}",
            title="Deep Analysis Report",
        )
    )

    # Entry quality
    eq = report.get("entry_quality", {})
    if eq.get("total_fills", 0) > 0:
        table = Table(title="Entry Quality", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Avg fill price", f"{eq.get('avg_fill_price', 0):.4f}")
        table.add_row("Avg confidence", f"{eq.get('avg_confidence', 0):.4f}")
        table.add_row("Avg entry gap", f"{eq.get('avg_entry_gap', 0):.4f}")
        table.add_row(
            "Distribution",
            f"cheap={eq.get('cheap', 0)} ok={eq.get('ok', 0)} "
            f"exp={eq.get('expensive', 0)} v.exp={eq.get('very_expensive', 0)}",
        )
        console.print(table)

    # Side accuracy
    sa = report.get("side_accuracy", {})
    if sa:
        table = Table(title="Side Accuracy", show_header=True)
        table.add_column("Side", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("W/L", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("PnL", justify="right")
        for side, data in sa.items():
            table.add_row(
                side,
                str(data.get("trades", 0)),
                f"{data.get('wins', 0)}/{data.get('losses', 0)}",
                f"{data.get('win_rate', 0):.0%}",
                f"{data.get('total_pnl', 0):.4f}",
            )
        console.print(table)

    # Timing
    timing = report.get("timing", {})
    if any(b.get("trades", 0) > 0 for b in timing.values()):
        table = Table(title="Entry Timing", show_header=True)
        table.add_column("Bucket", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        for bucket, data in timing.items():
            if data.get("trades", 0) > 0:
                table.add_row(bucket, str(data["trades"]), f"{data.get('win_rate', 0):.0%}")
        console.print(table)

    # Losses
    losses = report.get("losses", [])
    if losses:
        table = Table(title=f"Losses ({len(losses)})", show_header=True)
        table.add_column("Candle", style="cyan")
        table.add_column("Side")
        table.add_column("PnL", justify="right")
        table.add_column("BTC Move", justify="right")
        table.add_column("Predictable")
        for loss in losses:
            table.add_row(
                loss.get("slug", ""),
                loss.get("side", ""),
                f"{loss.get('pnl', 0):.4f}",
                f"${loss.get('btc_move', 0):.1f}",
                "YES" if loss.get("predictable") else "no",
            )
        console.print(table)

    # Flips
    flips = report.get("flips", [])
    if flips:
        total_fees = sum(f.get("total_fees", 0) for f in flips)
        console.print(f"\n[yellow]Position Flips:[/yellow] {len(flips)} candles, total fees: {total_fees:.4f}")

    # Missed opportunities
    missed = report.get("missed_opportunities", {})
    if missed.get("missed_candles", 0) > 0:
        console.print(
            f"\n[yellow]Missed:[/yellow] {missed.get('high_move_missed', 0)} high-move, "
            f"{missed.get('low_move_skipped', 0)} low-move "
            f"(biggest: ${missed.get('biggest_missed_move', 0):.1f})"
        )

    # Recommendations
    recs = report.get("recommendations", [])
    if recs:
        console.print()
        for rec in recs:
            color = _SEVERITY_COLORS.get(rec.get("severity", "low"), "white")
            severity_text = Text(f"[{rec.get('severity', 'low').upper()}]", style=f"bold {color}")
            console.print(severity_text, f" {rec.get('message', '')}")
            console.print(f"         {rec.get('evidence', '')}", style="dim")
    else:
        console.print("\n[green]No recommendations — performance looks healthy.[/green]")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for ``polybot-analyze-deep``."""
    parser = argparse.ArgumentParser(description="Deep post-run analysis for a Polymarket bot iteration.")
    parser.add_argument("iter_dir", type=Path, help="Path to archive/iter_NNN directory")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Save analysis.json to iter_dir")
    parser.add_argument("--no-render", action="store_true", help="Skip Rich terminal output")
    args = parser.parse_args()

    if not args.iter_dir.is_dir():
        print(f"Error: {args.iter_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    report = build_deep_report(args.iter_dir)

    if not args.no_render:
        console = Console()
        render_deep_report(report, console)

    if args.json_output:
        out_path = args.iter_dir / "analysis.json"
        out_path.write_text(json.dumps(report, indent=2))
        print(f"\nSaved: {out_path}")
