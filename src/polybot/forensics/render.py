"""Rich CLI rendering for forensics report sections."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .types import (
    AggregateMetrics,
    BlockedAggregate,
    BlockedOrder,
    CostAggregate,
    CostBreakdown,
    DecisionContext,
    ForensicsReport,
    OrderMetrics,
    RoundTrip,
    TTLAggregate,
    TTLCounterfactual,
)


def render_report(report: ForensicsReport, features: set[str] | None = None) -> None:
    """Render the complete forensics report to the terminal."""
    console = Console()
    console.print()
    console.print(Panel(
        f"[bold cyan]Polybot Forensics Report[/]\n"
        f"[dim]Generated: {report.generated_at}[/]\n"
        f"[dim]DB: {report.db_path}[/]",
        border_style="cyan",
    ))

    show_all = features is None

    if show_all or "A" in features:
        _render_execution(console, report.order_metrics, report.aggregate_metrics)

    if show_all or "B" in features:
        _render_ttl(console, report.ttl_counterfactuals, report.ttl_aggregate)

    if show_all or "C" in features:
        _render_costs(console, report.cost_breakdowns, report.cost_aggregate)

    if show_all or "D" in features:
        _render_blocked(console, report.blocked_orders, report.blocked_aggregate)

    if show_all or "E" in features:
        _render_roundtrips(console, report.round_trips)

    if show_all or "F" in features:
        _render_context(console, report.decision_contexts)


# ---------------------------------------------------------------------------
# Feature A: Execution
# ---------------------------------------------------------------------------


def _render_execution(
    console: Console,
    metrics: list[OrderMetrics],
    agg: AggregateMetrics,
) -> None:
    console.print()
    # Summary panel
    fill_pct = f"{agg.fill_rate * 100:.0f}%"
    summary = (
        f"[bold]{agg.total_orders}[/] orders | "
        f"[bold green]{agg.filled_count}[/] filled ({fill_pct}) | "
        f"p50 latency: [cyan]{_fmt_ms(agg.p50_latency_ms)}[/] | "
        f"p95 latency: [cyan]{_fmt_ms(agg.p95_latency_ms)}[/] | "
        f"max: [cyan]{_fmt_ms(agg.max_latency_ms)}[/]"
    )
    console.print(Panel(summary, title="[bold]A: Execution Overview[/]", border_style="green"))

    if not metrics:
        console.print("  [dim]No order data found.[/]")
        return

    # Fill source breakdown
    if agg.by_fill_source:
        src_parts = [f"{src}: [bold]{cnt}[/]" for src, cnt in sorted(agg.by_fill_source.items())]
        console.print(f"  Fill sources: {' | '.join(src_parts)}")

    # Drift summary
    if agg.p50_drift_bps is not None:
        console.print(
            f"  Ask drift: p50 [yellow]{agg.p50_drift_bps:+.1f}bps[/] | "
            f"p95 [yellow]{agg.p95_drift_bps:+.1f}bps[/]"
        )

    # Per-order table
    table = Table(title="Per-Order Metrics", show_lines=False, padding=(0, 1))
    table.add_column("Order", style="dim", max_width=12)
    table.add_column("Side", justify="center")
    table.add_column("Candle", justify="right")
    table.add_column("D→S ms", justify="right")
    table.add_column("Drift bps", justify="right")
    table.add_column("Filled", justify="center")
    table.add_column("Source", justify="center")
    table.add_column("Latency ms", justify="right")
    table.add_column("TTL", justify="right")

    for m in metrics:
        filled_style = "green" if m.filled else "red"
        table.add_row(
            m.order_id[:12],
            Text(m.side, style="green" if m.side == "BUY" else "red"),
            str(m.candle_id),
            f"{m.decision_to_submit_ms:.0f}",
            f"{m.ask_drift_bps:+.1f}" if m.ask_drift_bps is not None else "--",
            Text("YES" if m.filled else "NO", style=filled_style),
            m.fill_source or "timeout",
            f"{m.fill_latency_ms:.0f}" if m.fill_latency_ms is not None else "--",
            str(m.ttl_used),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Feature B: TTL
# ---------------------------------------------------------------------------


def _render_ttl(
    console: Console,
    cfs: list[TTLCounterfactual],
    agg: TTLAggregate,
) -> None:
    console.print()
    console.print(Panel(
        f"[bold]{agg.total_timeouts}[/] timed-out orders analyzed",
        title="[bold]B: TTL Counterfactuals[/]",
        border_style="yellow",
    ))

    if not agg.grid_ttls:
        console.print("  [dim]No TTL data.[/]")
        return

    # Rescue curve table
    table = Table(title="TTL Rescue Curve", show_lines=False, padding=(0, 1))
    table.add_column("TTL (s)", justify="right", style="bold")
    table.add_column("Rescued", justify="right")
    table.add_column("Cumulative %", justify="right")

    for ttl in agg.grid_ttls:
        rescued = agg.rescued_at.get(ttl, 0)
        pct = f"{rescued / agg.total_timeouts * 100:.0f}%" if agg.total_timeouts > 0 else "--"
        bar = "[green]" + "|" * min(rescued * 2, 40) + "[/]"
        table.add_row(str(ttl), f"{rescued} {bar}", pct)

    console.print(table)

    # Per-order details
    if cfs:
        table2 = Table(title="Per-Order TTL Analysis", show_lines=False, padding=(0, 1))
        table2.add_column("Order", style="dim", max_width=12)
        table2.add_column("Candle", justify="right")
        table2.add_column("Actual TTL", justify="right")
        table2.add_column("Rescue TTL", justify="right")
        for ttl in agg.grid_ttls:
            table2.add_column(f"{ttl}s", justify="center")

        for cf in cfs:
            row = [cf.order_id[:12], str(cf.candle_id), str(cf.actual_ttl)]
            row.append(
                Text(str(cf.rescue_ttl), style="green") if cf.rescue_ttl else Text("--", style="red")
            )
            for ttl in agg.grid_ttls:
                filled = cf.grid.get(ttl, False)
                row.append(Text("Y", style="green") if filled else Text(".", style="dim"))
            table2.add_row(*row)

        console.print(table2)


# ---------------------------------------------------------------------------
# Feature C: Costs
# ---------------------------------------------------------------------------


def _render_costs(
    console: Console,
    breakdowns: list[CostBreakdown],
    agg: CostAggregate,
) -> None:
    console.print()
    summary = (
        f"Fees: [bold]${agg.total_fees:.4f}[/] | "
        f"Slippage cost: [bold]${agg.total_slippage_cost:.4f}[/] | "
        f"Drift cost: [bold]${agg.total_drift_cost:.4f}[/]"
    )
    console.print(Panel(summary, title="[bold]C: Cost Breakdown[/]", border_style="magenta"))

    # By outcome
    if agg.by_outcome:
        parts = [f"{k}: ${v:.4f}" for k, v in sorted(agg.by_outcome.items())]
        console.print(f"  By outcome: {' | '.join(parts)}")
    if agg.by_side:
        parts = [f"{k}: ${v:.4f}" for k, v in sorted(agg.by_side.items())]
        console.print(f"  By side: {' | '.join(parts)}")

    if not breakdowns:
        return

    table = Table(title="Per-Order Costs", show_lines=False, padding=(0, 1))
    table.add_column("Order", style="dim", max_width=12)
    table.add_column("Fee", justify="right")
    table.add_column("Slippage bps", justify="right")
    table.add_column("Drift $", justify="right")
    table.add_column("Total $", justify="right", style="bold")

    for bd in breakdowns:
        table.add_row(
            bd.order_id[:12],
            f"${bd.fee_amount:.4f}",
            f"{bd.slippage_bps:.1f}",
            f"${bd.drift_cost:+.4f}",
            f"${bd.total_cost:.4f}",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Feature D: Blocked
# ---------------------------------------------------------------------------


def _render_blocked(
    console: Console,
    blocked: list[BlockedOrder],
    agg: BlockedAggregate,
) -> None:
    console.print()
    summary = (
        f"[bold]{agg.total_blocked}[/] blocked | "
        f"TTL-rescuable: [green]{agg.rescuable_ttl}[/] | "
        f"Reprice-rescuable: [green]{agg.rescuable_reprice}[/]"
    )
    console.print(Panel(summary, title="[bold]D: Blocked Orders[/]", border_style="red"))

    if agg.by_category:
        table = Table(title="By Category", show_lines=False, padding=(0, 1))
        table.add_column("Category", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Bar")
        for cat, cnt in sorted(agg.by_category.items(), key=lambda x: -x[1]):
            bar = "[red]" + "|" * min(cnt * 3, 40) + "[/]"
            table.add_row(cat, str(cnt), bar)
        console.print(table)

    if blocked:
        table2 = Table(title="Blocked Details", show_lines=False, padding=(0, 1))
        table2.add_column("Candle", justify="right")
        table2.add_column("Action", justify="center")
        table2.add_column("Category", style="bold")
        table2.add_column("Reason", style="dim", max_width=40)
        table2.add_column("TTL?", justify="center")
        table2.add_column("Reprice?", justify="center")

        for b in blocked:
            table2.add_row(
                str(b.candle_id),
                b.action,
                b.category,
                b.risk_reason[:40],
                Text("Y", style="green") if b.ttl_rescuable else Text(".", style="dim"),
                Text("Y", style="green") if b.reprice_rescuable else Text(".", style="dim"),
            )
        console.print(table2)


# ---------------------------------------------------------------------------
# Feature E: Round-trips
# ---------------------------------------------------------------------------


def _render_roundtrips(console: Console, trips: list[RoundTrip]) -> None:
    console.print()
    if not trips:
        console.print(Panel("[dim]No round-trips found.[/]", title="[bold]E: Round-Trips[/]", border_style="blue"))
        return

    total_pnl = sum(t.realized_pnl for t in trips)
    avg_eff = sum(t.exit_efficiency for t in trips) / len(trips) if trips else 0
    summary = (
        f"[bold]{len(trips)}[/] round-trips | "
        f"Total PnL: [{'green' if total_pnl >= 0 else 'red'}]${total_pnl:+.4f}[/] | "
        f"Avg exit efficiency: [cyan]{avg_eff:.0%}[/]"
    )
    console.print(Panel(summary, title="[bold]E: Round-Trips[/]", border_style="blue"))

    table = Table(show_lines=False, padding=(0, 1))
    table.add_column("Side", justify="center")
    table.add_column("Entry C#", justify="right")
    table.add_column("Exit C#", justify="right")
    table.add_column("Entry $", justify="right")
    table.add_column("Exit $", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Hold (s)", justify="right")
    table.add_column("PnL $", justify="right")
    table.add_column("MFE", justify="right")
    table.add_column("MAE", justify="right")
    table.add_column("Eff %", justify="right")

    for t in trips:
        pnl_style = "green" if t.realized_pnl >= 0 else "red"
        table.add_row(
            t.side,
            str(t.entry_candle_id),
            str(t.exit_candle_id),
            f"{t.entry_price:.4f}",
            f"{t.exit_price:.4f}",
            f"{t.size:.1f}",
            f"{t.hold_duration_s:.0f}",
            Text(f"${t.realized_pnl:+.4f}", style=pnl_style),
            f"{t.mfe:.4f}",
            f"{t.mae:.4f}",
            f"{t.exit_efficiency:.0%}",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Feature F: Context
# ---------------------------------------------------------------------------


def _render_context(console: Console, contexts: list[DecisionContext]) -> None:
    console.print()
    if not contexts:
        console.print(Panel("[dim]No decision contexts.[/]", title="[bold]F: Decision Context[/]", border_style="cyan"))
        return

    wins = sum(1 for c in contexts if c.outcome == "win")
    losses = sum(1 for c in contexts if c.outcome == "loss")
    console.print(Panel(
        f"[bold]{len(contexts)}[/] decisions | "
        f"[green]{wins}W[/] / [red]{losses}L[/]",
        title="[bold]F: Decision Context[/]",
        border_style="cyan",
    ))

    table = Table(show_lines=False, padding=(0, 1))
    table.add_column("Candle", justify="right")
    table.add_column("Action", justify="center")
    table.add_column("Conf", justify="right")
    table.add_column("R/R", justify="right")
    table.add_column("ML", justify="right")
    table.add_column("Outcome", justify="center")
    table.add_column("Key Indicators", style="dim", max_width=50)

    for c in contexts:
        outcome_style = "green" if c.outcome == "win" else ("red" if c.outcome == "loss" else "dim")
        # Top 3 indicators by absolute value
        top_inds = sorted(c.indicators.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        ind_str = ", ".join(f"{k}={v:.2f}" for k, v in top_inds) if top_inds else "--"

        table.add_row(
            str(c.candle_id),
            Text(c.action, style="green" if c.action == "BUY" else "red"),
            f"{c.confidence:.2f}",
            f"{c.rr_ratio:.2f}",
            f"{c.ml_score:.3f}" if c.ml_score is not None else "--",
            Text(c.outcome or "--", style=outcome_style),
            ind_str,
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ms(val: float | None) -> str:
    if val is None:
        return "--"
    return f"{val:.0f}ms"
