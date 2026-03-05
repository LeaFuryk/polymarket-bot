"""Candle replay runner — deterministic offline replay of per-second orderbook data.

Replays any candle's orderbook timeline to identify optimal entry points,
simulate limit order fillability, overlay live order telemetry, and analyze
post-cancel price recovery.

Usage:
    polybot-replay --slug btc-updown-5m           # Latest candle matching slug
    polybot-replay --slug btc-updown-5m --all     # All candles for slug
    polybot-replay --slug btc-updown-5m --candle-id 15
    polybot-replay --slug btc-updown-5m --ttl 5   # Counterfactual: 5s TTL
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from polybot.analysis.constants import (
    AGG_FILL_RATE_GREEN,
    AGG_FILL_RATE_YELLOW,
    ENTRY_GAP_GREEN,
    ENTRY_GAP_YELLOW,
    FILL_RATE_GREEN,
    FILL_RATE_YELLOW,
    RECOVERY_RATE_GREEN,
    SIDE_ACCURACY_GREEN,
    SIDE_ACCURACY_YELLOW,
)
from polybot.analysis.engine import (
    build_decision_timeline,
    compute_ob_stats,
    fillability_scan,
    generate_insights,
    live_order_telemetry,
    post_cancel_recovery,
)

DB_PATH = Path.cwd() / "logs" / "polybot.db"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        print(f"Error: {db_path} not found. Run the bot first to accumulate data.")
        sys.exit(1)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _find_candles(conn: sqlite3.Connection, slug: str, candle_id: int | None) -> list[dict]:
    """Find candle(s) matching slug (partial match OK) and optional candle_id."""
    if candle_id is not None:
        rows = conn.execute(
            "SELECT * FROM candles WHERE candle_id = ? AND slug LIKE ?",
            (candle_id, f"%{slug}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM candles WHERE slug LIKE ? ORDER BY candle_id",
            (f"%{slug}%",),
        ).fetchall()
    return [dict(r) for r in rows]


def _load_snapshots(conn: sqlite3.Connection, candle_id: int) -> list[dict]:
    """Load all per-second snapshots for a candle, ordered by timestamp."""
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE candle_id = ? ORDER BY timestamp",
        (candle_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _load_decisions(conn: sqlite3.Connection, candle_id: int) -> list[dict]:
    """Load all AI decisions for a candle."""
    # Check if live_order_json column exists
    cols = [r[1] for r in conn.execute("PRAGMA table_info(decisions)").fetchall()]
    has_live_order = "live_order_json" in cols

    rows = conn.execute(
        "SELECT * FROM decisions WHERE candle_id = ? ORDER BY timestamp",
        (candle_id,),
    ).fetchall()
    decisions = [dict(r) for r in rows]

    # Parse live_order_json if present
    if has_live_order:
        for d in decisions:
            raw = d.get("live_order_json")
            if raw and raw.strip():
                try:
                    d["_live_order"] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    d["_live_order"] = None
            else:
                d["_live_order"] = None
    else:
        for d in decisions:
            d["_live_order"] = None

    return decisions


# ---------------------------------------------------------------------------
# Core replay logic
# ---------------------------------------------------------------------------


def replay_candle(
    conn: sqlite3.Connection,
    candle: dict,
    ttl: int,
    limit_price: float,
) -> dict:
    """Core replay logic for one candle.

    Returns a structured dict with all analysis sections.
    """
    candle_id = candle["candle_id"]
    snapshots = _load_snapshots(conn, candle_id)
    decisions = _load_decisions(conn, candle_id)

    if not snapshots:
        return {
            "candle": candle,
            "error": "No snapshots found for this candle.",
            "snapshots": [],
            "decisions": [],
        }

    # Determine the traded side from decisions (default to "up")
    trade_decisions = [d for d in decisions if d["action"] in ("BUY", "SELL")]
    if trade_decisions:
        side = trade_decisions[0].get("token_side", "up")
    else:
        side = "up"

    # Orderbook statistics
    ob_stats = compute_ob_stats(snapshots, side)

    # Derive a reference price for the fillability scan when none is given:
    # use the book ask at the first BUY decision (what the AI actually saw).
    scan_price = limit_price
    if scan_price == 0.0 and trade_decisions:
        prefix = "up_" if side == "up" else "down_"
        ask_key = f"{prefix}best_ask"
        first_buy = next((d for d in trade_decisions if d["action"] == "BUY"), None)
        if first_buy:
            closest = min(snapshots, key=lambda s: abs(s["timestamp"] - first_buy["timestamp"]))
            ref = closest.get(ask_key)
            if ref is not None:
                scan_price = ref

    # Fillability scan
    fill_scan = fillability_scan(snapshots, side, ttl, scan_price)

    # Decision timeline
    decision_timeline = build_decision_timeline(snapshots, decisions, side)

    # Post-cancel recovery
    post_cancel = post_cancel_recovery(snapshots, decisions, side)

    # Live order telemetry overlay
    telemetry = live_order_telemetry(decisions, snapshots, side)

    # Key insights
    insights = generate_insights(
        candle,
        snapshots,
        decisions,
        ob_stats,
        fill_scan,
        post_cancel,
        side,
        ttl,
    )

    return {
        "candle": candle,
        "side": side,
        "snapshots": snapshots,
        "decisions": decisions,
        "ob_stats": ob_stats,
        "fill_scan": fill_scan,
        "decision_timeline": decision_timeline,
        "post_cancel": post_cancel,
        "telemetry": telemetry,
        "insights": insights,
    }


# ---------------------------------------------------------------------------
# Rich report rendering
# ---------------------------------------------------------------------------


def render_report(analysis: dict, console: Console) -> None:
    """Render all report sections using Rich."""
    candle = analysis["candle"]
    side = analysis.get("side", "up")

    if analysis.get("error"):
        console.print(f"[red]{analysis['error']}[/red]")
        return

    # --- 1. Header ---
    _render_header(candle, side, analysis, console)

    # --- 2. Orderbook Summary ---
    _render_ob_stats(analysis.get("ob_stats", {}), side, console)

    # --- 3. Decision Timeline ---
    _render_decision_timeline(analysis.get("decision_timeline", []), console)

    # --- 4. Fillability Scan ---
    _render_fillability(analysis.get("fill_scan", {}), side, console)

    # --- 5. Post-Cancel Recovery ---
    _render_post_cancel(analysis.get("post_cancel"), console)

    # --- 6. Live Order Telemetry ---
    _render_telemetry(analysis.get("telemetry"), console)

    # --- 7. Key Insights ---
    _render_insights(analysis.get("insights", []), console)


def _render_header(candle: dict, side: str, analysis: dict, console: Console) -> None:
    slug = candle.get("slug", "?")
    candle_id = candle.get("candle_id", "?")
    winner = candle.get("winner", "pending")
    start_ts = candle.get("start_time", 0)
    end_ts = candle.get("end_time", 0)
    btc_open = candle.get("btc_open")
    btc_close = candle.get("btc_close")
    ob_stats = analysis.get("ob_stats", {})
    duration = ob_stats.get("duration_s", 0)
    snap_count = ob_stats.get("total_snapshots", 0)

    start_str = datetime.fromtimestamp(start_ts, tz=UTC).strftime("%H:%M:%S") if start_ts else "?"
    end_str = datetime.fromtimestamp(end_ts, tz=UTC).strftime("%H:%M:%S") if end_ts else "?"

    winner_color = "green" if winner == side else "red" if winner and winner != side else "yellow"

    lines = [
        f"[bold]Candle #{candle_id}[/bold] — {slug}",
        f"  Time:     {start_str} → {end_str} UTC ({duration:.0f}s of data, {snap_count} snapshots)",
        f"  Side:     [cyan]{side.upper()}[/cyan]",
        f"  Winner:   [{winner_color}]{(winner or 'pending').upper()}[/{winner_color}]",
    ]
    if btc_open is not None:
        btc_move = (btc_close - btc_open) if btc_close else 0
        lines.append(
            f"  BTC:      ${btc_open:,.2f} → ${btc_close:,.2f} ({btc_move:+.2f})"
            if btc_close
            else f"  BTC:      ${btc_open:,.2f} → pending"
        )

    console.print(Panel("\n".join(lines), title="Candle Replay", border_style="cyan"))


def _render_ob_stats(stats: dict, side: str, console: Console) -> None:
    if not stats or stats.get("total_snapshots", 0) == 0:
        return

    table = Table(title=f"Orderbook Summary ({side.upper()} token)", show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Min", justify="right")
    table.add_column("Max", justify="right")
    table.add_column("Mean", justify="right")
    table.add_column("StDev", justify="right")

    for label, key in [
        ("Best Bid", "best_bid"),
        ("Best Ask", "best_ask"),
        ("Mid", "mid"),
        ("Spread %", "spread_pct"),
        ("BTC Price", "btc_price"),
    ]:
        s = stats.get(key, {})
        if s.get("min") is None:
            continue
        fmt = ".3f" if key != "btc_price" else ",.2f"
        table.add_row(
            label,
            f"${s['min']:{fmt}}" if key == "btc_price" else f"{s['min']:{fmt}}",
            f"${s['max']:{fmt}}" if key == "btc_price" else f"{s['max']:{fmt}}",
            f"${s['mean']:{fmt}}" if key == "btc_price" else f"{s['mean']:{fmt}}",
            f"{s['stdev']:{fmt}}",
        )

    console.print(table)
    console.print()


def _render_decision_timeline(timeline: list[dict], console: Console) -> None:
    if not timeline:
        console.print("[dim]No AI decisions recorded for this candle.[/dim]\n")
        return

    table = Table(title="Decision Timeline", show_header=True)
    table.add_column("T+", justify="right", style="dim")
    table.add_column("Action", style="bold")
    table.add_column("Side")
    table.add_column("Conf", justify="right")
    table.add_column("Fill Price", justify="right")
    table.add_column("Book Ask", justify="right")
    table.add_column("Book Bid", justify="right")
    table.add_column("BTC", justify="right")
    table.add_column("Time Left", justify="right")

    for t in timeline:
        action = t["action"]
        action_color = "green" if action == "BUY" else "red" if action == "SELL" else "dim"

        table.add_row(
            f"{t['offset_s']:.0f}s",
            f"[{action_color}]{action}[/{action_color}]",
            t.get("token_side", "?"),
            f"{t['confidence']:.2f}" if t.get("confidence") else "—",
            f"{t['fill_price']:.3f}" if t.get("fill_price") else "—",
            f"{t['book_ask']:.3f}" if t.get("book_ask") else "—",
            f"{t['book_bid']:.3f}" if t.get("book_bid") else "—",
            f"${t['btc_price']:,.0f}" if t.get("btc_price") else "—",
            f"{t['time_remaining']:.0f}s" if t.get("time_remaining") else "—",
        )

    console.print(table)
    console.print()


def _render_fillability(scan: dict, side: str, console: Console) -> None:
    if not scan or scan.get("total_seconds", 0) == 0:
        return

    total = scan["total_seconds"]
    fillable = scan["fillable_seconds"]
    rate = scan["fill_rate"]
    ttl = scan["ttl"]

    rate_color = "green" if rate >= FILL_RATE_GREEN else "yellow" if rate >= FILL_RATE_YELLOW else "red"

    lines = [
        f"  TTL:              {ttl}s"
        + (
            f"  (reference price: {scan['reference_price']:.3f})"
            if scan.get("reference_price")
            else "  (per-second best_ask)"
        ),
        f"  Fillable seconds: [{rate_color}]{fillable}/{total} ({rate:.0%})[/{rate_color}]",
    ]
    if scan.get("best_entry") is not None:
        lines.append(f"  Best fill entry:  {scan['best_entry']:.3f}")
    if scan.get("worst_entry") is not None:
        lines.append(f"  Worst fill entry: {scan['worst_entry']:.3f}")
    if scan.get("book_best_ask") is not None:
        lines.append(f"  Book best ask:    {scan['book_best_ask']:.3f}")
    if scan.get("book_worst_ask") is not None:
        lines.append(f"  Book worst ask:   {scan['book_worst_ask']:.3f}")

    # Distribution of fill windows (first 10)
    windows = scan.get("fill_windows", [])
    if windows:
        delays = [w["fill_delay"] for w in windows if w.get("fill_delay") is not None]
        if delays:
            lines.append(f"  Avg fill delay:   {mean(delays):.1f}s")
            lines.append(f"  Instant fills:    {sum(1 for d in delays if d == 0)}")

    console.print(Panel("\n".join(lines), title=f"Fillability Scan ({side.upper()} BUY)", border_style="blue"))
    console.print()


def _render_post_cancel(post_cancel: dict | None, console: Console) -> None:
    if post_cancel is None:
        return

    recovered = post_cancel["recovered"]
    color = "green" if recovered else "red"

    lines = [
        f"  Reason:           {post_cancel.get('reason', '?')}",
        f"  Ask at decision:  {post_cancel['decision_ask']:.3f}",
        f"  Window:           {post_cancel['window_seconds']}s ({post_cancel['snapshots_in_window']} snapshots)",
        f"  Min ask after:    {post_cancel['min_ask_after']:.3f}",
        f"  Max ask after:    {post_cancel['max_ask_after']:.3f}",
        f"  Mean ask after:   {post_cancel['mean_ask_after']:.3f}",
        f"  [{color}]{'RECOVERED — price returned to fillable range' if recovered else 'NOT RECOVERED — price stayed above decision ask'}[/{color}]",
    ]

    console.print(Panel("\n".join(lines), title="Post-Cancel Recovery (30s window)", border_style="magenta"))
    console.print()


def _render_telemetry(telemetry: dict | None, console: Console) -> None:
    if telemetry is None:
        return

    orders = telemetry.get("orders", [])
    if not orders:
        return

    for order in orders:
        filled = order["filled"]
        status = "[green]FILLED[/green]" if filled else "[red]MISSED[/red]"

        lines = [
            f"  Order ID:         {order.get('order_id', '?')}",
            f"  Status:           {status}",
            f"  Limit price:      {order['limit_price']:.3f}" if order.get("limit_price") else "  Limit price:      —",
            f"  TTL:              {order.get('ttl_used', '?')}s",
            f"  Fill source:      {order.get('fill_source', '—')}",
        ]

        # Decision vs submit drift
        dec_ask = order.get("decision_ob_ask")
        sub_ask = order.get("ob_at_submit", {}).get("best_ask")
        if dec_ask and sub_ask:
            drift = (sub_ask - dec_ask) / dec_ask * 100
            drift_color = "green" if drift <= 0 else "yellow" if drift < 2 else "red"
            lines.append(f"  Decision ask:     {dec_ask:.3f}")
            lines.append(f"  Submit ask:       {sub_ask:.3f} ([{drift_color}]{drift:+.1f}% drift[/{drift_color}])")

        # Polls
        polls = order.get("polls", [])
        if polls:
            lines.append(f"  Polls:            {len(polls)} status checks")
            for p in polls[:5]:
                status_str = p.get("status", "?")
                sm = p.get("size_matched", 0)
                lines.append(f"    - {status_str} (size_matched={sm})")

        # OB at end
        ob_end = order.get("ob_at_end", {})
        if ob_end.get("best_ask"):
            lines.append(f"  Ask at end:       {ob_end['best_ask']:.3f}")

        # Post-cancel OB
        ob_pc = order.get("ob_post_cancel")
        if ob_pc and ob_pc.get("best_ask"):
            lines.append(f"  Ask post-cancel:  {ob_pc['best_ask']:.3f}")

        console.print(
            Panel(
                "\n".join(lines),
                title="Live Order Telemetry",
                border_style="yellow",
            )
        )
    console.print()


def _render_insights(insights: list[str], console: Console) -> None:
    if not insights:
        return

    text = Text()
    for i, insight in enumerate(insights):
        text.append(f"  {i + 1}. ", style="bold cyan")
        text.append(insight)
        text.append("\n")

    console.print(Panel(text, title="Key Insights", border_style="green"))
    console.print()


# ---------------------------------------------------------------------------
# Aggregate summary — used by polybot-analyze and polybot-archive
# ---------------------------------------------------------------------------


def replay_all_candles(db_path: str | Path, ttl: int = 3) -> dict:
    """Replay all candles in a DB and return aggregate statistics.

    Returns a dict suitable for both Rich rendering and JSON serialization.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return {"error": f"Database not found: {db_path}", "candles_replayed": 0}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        all_candles = conn.execute("SELECT * FROM candles ORDER BY candle_id").fetchall()
        all_candles = [dict(r) for r in all_candles]

        if not all_candles:
            return {"candles_replayed": 0}

        # Per-candle replay results (compact — no raw snapshots)
        fill_rates: list[float] = []
        entry_gaps: list[float] = []  # actual fill price - book best ask
        recovery_count = 0
        recovery_total = 0
        candles_with_trades = 0
        candles_with_fills = 0
        candles_with_missed = 0
        side_correct = 0
        side_total = 0
        best_entries: list[float] = []
        worst_entries: list[float] = []
        per_candle: list[dict] = []

        for candle in all_candles:
            analysis = replay_candle(conn, candle, ttl, 0.0)
            if analysis.get("error"):
                continue

            fill_scan = analysis.get("fill_scan", {})
            decisions = analysis.get("decisions", [])
            post_cancel = analysis.get("post_cancel")
            side = analysis.get("side", "up")
            winner = candle.get("winner")

            # Fill rate
            fr = fill_scan.get("fill_rate")
            if fr is not None and fill_scan.get("total_seconds", 0) > 0:
                fill_rates.append(fr)

            # Track best/worst entries
            if fill_scan.get("book_best_ask") is not None:
                best_entries.append(fill_scan["book_best_ask"])
            if fill_scan.get("book_worst_ask") is not None:
                worst_entries.append(fill_scan["book_worst_ask"])

            # Trade analysis
            buys = [d for d in decisions if d["action"] == "BUY"]
            fills = [d for d in buys if d.get("fill_price") is not None]
            missed = [d for d in buys if d.get("fill_price") is None and not d.get("risk_blocked")]

            if buys:
                candles_with_trades += 1
            if fills:
                candles_with_fills += 1
                # Entry gap: how far was the actual fill from the best possible?
                actual = fills[0]["fill_price"]
                book_best = fill_scan.get("book_best_ask")
                if book_best is not None and actual is not None:
                    entry_gaps.append(actual - book_best)
            if missed:
                candles_with_missed += 1

            # Post-cancel recovery
            if post_cancel is not None:
                recovery_total += 1
                if post_cancel.get("recovered"):
                    recovery_count += 1

            # Side correctness
            if winner:
                side_total += 1
                if winner == side:
                    side_correct += 1

            # Compact per-candle row
            per_candle.append(
                {
                    "candle_id": candle["candle_id"],
                    "slug": candle.get("slug", ""),
                    "winner": winner,
                    "side": side,
                    "side_correct": winner == side if winner else None,
                    "fill_rate": fr,
                    "book_best_ask": fill_scan.get("book_best_ask"),
                    "had_trade": bool(buys),
                    "had_fill": bool(fills),
                    "had_missed": bool(missed),
                    "recovered": post_cancel.get("recovered") if post_cancel else None,
                }
            )

        return {
            "candles_replayed": len(per_candle),
            "candles_with_trades": candles_with_trades,
            "candles_with_fills": candles_with_fills,
            "candles_with_missed": candles_with_missed,
            "ttl": ttl,
            "avg_fill_rate": mean(fill_rates) if fill_rates else None,
            "min_fill_rate": min(fill_rates) if fill_rates else None,
            "max_fill_rate": max(fill_rates) if fill_rates else None,
            "avg_entry_gap": mean(entry_gaps) if entry_gaps else None,
            "avg_best_ask": mean(best_entries) if best_entries else None,
            "recovery_rate": recovery_count / recovery_total if recovery_total else None,
            "recovery_count": recovery_count,
            "recovery_total": recovery_total,
            "side_accuracy": side_correct / side_total if side_total else None,
            "side_correct": side_correct,
            "side_total": side_total,
            "per_candle": per_candle,
        }
    finally:
        conn.close()


def render_aggregate_summary(stats: dict, console: Console) -> None:
    """Render a compact aggregate replay summary as a Rich table."""
    if stats.get("error"):
        console.print(f"[dim]{stats['error']}[/dim]")
        return

    total = stats.get("candles_replayed", 0)
    if total == 0:
        console.print("[dim]No candles to replay.[/dim]")
        return

    console.print()
    console.print("[bold cyan]Candle Replay Summary[/bold cyan]")

    table = Table(show_header=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Candles replayed", str(total))
    table.add_row("With BUY attempts", str(stats.get("candles_with_trades", 0)))
    table.add_row("With fills", str(stats.get("candles_with_fills", 0)))
    table.add_row("With missed orders", str(stats.get("candles_with_missed", 0)))
    table.add_row("TTL", f"{stats.get('ttl', 3)}s")

    # Fill rate
    avg_fr = stats.get("avg_fill_rate")
    if avg_fr is not None:
        fr_color = "green" if avg_fr >= AGG_FILL_RATE_GREEN else "yellow" if avg_fr >= AGG_FILL_RATE_YELLOW else "red"
        table.add_row("Avg fill rate", f"[{fr_color}]{avg_fr:.0%}[/{fr_color}]")
        table.add_row("Fill rate range", f"{stats['min_fill_rate']:.0%} – {stats['max_fill_rate']:.0%}")

    # Entry gap
    avg_gap = stats.get("avg_entry_gap")
    if avg_gap is not None:
        gap_color = "green" if avg_gap < ENTRY_GAP_GREEN else "yellow" if avg_gap < ENTRY_GAP_YELLOW else "red"
        table.add_row("Avg entry gap", f"[{gap_color}]{avg_gap:.3f}[/{gap_color}]")

    # Recovery
    rec_rate = stats.get("recovery_rate")
    if rec_rate is not None:
        rec_color = "green" if rec_rate >= RECOVERY_RATE_GREEN else "yellow"
        table.add_row(
            "Post-cancel recovery",
            f"[{rec_color}]{stats['recovery_count']}/{stats['recovery_total']} ({rec_rate:.0%})[/{rec_color}]",
        )

    # Side accuracy
    side_acc = stats.get("side_accuracy")
    if side_acc is not None:
        acc_color = (
            "green" if side_acc >= SIDE_ACCURACY_GREEN else "yellow" if side_acc >= SIDE_ACCURACY_YELLOW else "red"
        )
        table.add_row(
            "Side accuracy",
            f"[{acc_color}]{stats['side_correct']}/{stats['side_total']} ({side_acc:.0%})[/{acc_color}]",
        )

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for polybot-replay CLI."""
    parser = argparse.ArgumentParser(
        description="Replay candle orderbook data to analyze fill opportunities and entry timing."
    )
    parser.add_argument(
        "--slug",
        type=str,
        required=True,
        help="Market slug (partial match OK, e.g. 'btc-updown-5m')",
    )
    parser.add_argument(
        "--candle-id",
        type=int,
        default=None,
        help="Specific candle ID to replay (default: latest)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to polybot.db (default: logs/polybot.db)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Replay all candles matching the slug",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=3,
        help="Simulated order TTL in seconds (default: 3)",
    )
    parser.add_argument(
        "--limit-price",
        type=float,
        default=0.0,
        help="Override limit price for fillability scan (0 = use book price at each second)",
    )
    args = parser.parse_args()

    global DB_PATH
    if args.db:
        DB_PATH = Path(args.db)

    console = Console()
    conn = _connect(DB_PATH)

    try:
        candles = _find_candles(conn, args.slug, args.candle_id)

        if not candles:
            console.print(f"[red]No candles found matching slug '{args.slug}'[/red]")
            if args.candle_id:
                console.print(f"[dim]  (candle_id={args.candle_id})[/dim]")
            return

        if not args.all and args.candle_id is None:
            # Default: latest candle only
            candles = [candles[-1]]

        console.print(f"\n[bold]Replaying {len(candles)} candle(s) for slug '{args.slug}'[/bold]\n")

        for candle in candles:
            analysis = replay_candle(conn, candle, args.ttl, args.limit_price)
            render_report(analysis, console)

            if len(candles) > 1:
                console.rule(style="dim")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
