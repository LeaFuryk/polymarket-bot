"""Assumption validation CLI — queries persistent market history DB.

Reads data/market_history.db (accumulated across all iterations) and prints
statistical reports on momentum continuation, reversal rates, optimal entry
timing, and move distribution.

Usage:
    polybot-validate                        # All reports
    polybot-validate --report momentum      # Specific report
    polybot-validate --min-candles 50       # Require minimum sample
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

DB_PATH = Path.cwd() / "data" / "market_history.db"

# Time-remaining buckets (seconds)
TIME_BUCKETS = [
    (">240s", 240, 999),
    ("180-240s", 180, 240),
    ("120-180s", 120, 180),
    ("60-120s", 60, 120),
    ("<60s", 0, 60),
]

# BTC move buckets (absolute $)
MOVE_BUCKETS = [
    ("$0-10", 0, 10),
    ("$10-20", 10, 20),
    ("$20-30", 20, 30),
    ("$30-50", 30, 50),
    ("$50+", 50, 99999),
]


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found. Run the bot first to accumulate data.")
        sys.exit(1)
    return sqlite3.connect(str(DB_PATH))


def _load_candle_data(conn: sqlite3.Connection) -> list[dict]:
    """Load resolved candles with their snapshot data."""
    rows = conn.execute("""
        SELECT
            c.candle_id, c.slug, c.iteration, c.btc_open, c.btc_close, c.winner,
            c.start_time, c.end_time
        FROM market_candles c
        WHERE c.winner IS NOT NULL AND c.btc_open IS NOT NULL AND c.btc_close IS NOT NULL
        ORDER BY c.start_time
    """).fetchall()

    candles = []
    for r in rows:
        candle_id, slug, iteration, btc_open, btc_close, winner, start_time, end_time = r
        candles.append(
            {
                "candle_id": candle_id,
                "slug": slug,
                "iteration": iteration,
                "btc_open": btc_open,
                "btc_close": btc_close,
                "winner": winner,
                "start_time": start_time,
                "end_time": end_time,
                "btc_move": btc_close - btc_open,
                "abs_move": abs(btc_close - btc_open),
            }
        )
    return candles


def _load_snapshot_data(conn: sqlite3.Connection, candle_id: int) -> list[dict]:
    """Load snapshots for a candle."""
    rows = conn.execute(
        """
        SELECT time_remaining, btc_price, btc_move_from_open,
               up_best_ask, down_best_ask, up_mid, down_mid
        FROM market_snapshots
        WHERE candle_id = ?
        ORDER BY timestamp
    """,
        (candle_id,),
    ).fetchall()

    return [
        {
            "time_remaining": r[0],
            "btc_price": r[1],
            "btc_move_from_open": r[2],
            "up_best_ask": r[3],
            "down_best_ask": r[4],
            "up_mid": r[5],
            "down_mid": r[6],
        }
        for r in rows
    ]


def _confidence_label(n: int) -> str:
    if n < 30:
        return f"[yellow]{n}[/yellow]"
    return f"[green]{n}[/green]"


def report_summary(conn: sqlite3.Connection, console: Console, candles: list[dict]) -> None:
    """Print summary header."""
    if not candles:
        console.print("[red]No resolved candles found in market history.[/red]")
        return

    iterations = sorted(set(c["iteration"] for c in candles if c["iteration"]))
    start = datetime.fromtimestamp(candles[0]["start_time"], tz=UTC)
    end = datetime.fromtimestamp(candles[-1]["end_time"], tz=UTC)

    up_wins = sum(1 for c in candles if c["winner"] == "up")
    down_wins = len(candles) - up_wins

    console.print()
    console.print("[bold cyan]Market History Summary[/bold cyan]")
    console.print(f"  Total candles:  {len(candles)}")
    console.print(f"  Date range:     {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC")
    console.print(f"  Iterations:     {', '.join(iterations) if iterations else 'unknown'}")
    console.print(f"  UP wins:        {up_wins} ({up_wins / len(candles):.1%})")
    console.print(f"  DOWN wins:      {down_wins} ({down_wins / len(candles):.1%})")
    console.print(f"  Avg BTC move:   ${sum(c['abs_move'] for c in candles) / len(candles):.1f}")

    data_quality = []
    if len(candles) < 50:
        data_quality.append("[yellow]< 50 candles — low confidence[/yellow]")
    if len(candles) < 100:
        data_quality.append("[yellow]< 100 candles — moderate confidence[/yellow]")

    # Check for snapshots
    snap_count = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
    avg_snaps = snap_count / len(candles) if candles else 0
    console.print(f"  Snapshots:      {snap_count:,} ({avg_snaps:.0f}/candle avg)")

    if data_quality:
        console.print(f"  Data quality:   {'; '.join(data_quality)}")
    else:
        console.print("  Data quality:   [green]Good (100+ candles)[/green]")
    console.print()


def report_momentum(conn: sqlite3.Connection, console: Console, candles: list[dict], min_candles: int) -> None:
    """Momentum continuation report: for each move+time bucket, % where mid-candle direction = final winner."""
    console.print("[bold cyan]Momentum Continuation[/bold cyan]")
    console.print("  % of candles where mid-candle BTC direction matches final winner\n")

    table = Table(show_header=True)
    table.add_column("Move Bucket", style="bold")
    for label, _, _ in TIME_BUCKETS:
        table.add_column(label, justify="center")

    for move_label, move_lo, move_hi in MOVE_BUCKETS:
        row_values = [move_label]
        for _, time_lo, time_hi in TIME_BUCKETS:
            total = 0
            continuation = 0
            for c in candles:
                snapshots = _load_snapshot_data(conn, c["candle_id"])
                for s in snapshots:
                    tr = s["time_remaining"]
                    abs_move = abs(s["btc_move_from_open"])
                    if time_lo <= tr < time_hi and move_lo <= abs_move < move_hi:
                        total += 1
                        # Mid-candle direction
                        mid_dir = "up" if s["btc_move_from_open"] >= 0 else "down"
                        if mid_dir == c["winner"]:
                            continuation += 1
                        break  # One sample per candle per bucket

            if total == 0:
                row_values.append("—")
            elif total < min_candles:
                pct = continuation / total * 100
                row_values.append(f"[dim]{pct:.0f}% (n={total})[/dim]")
            else:
                pct = continuation / total * 100
                color = "green" if pct >= 70 else "yellow" if pct >= 50 else "red"
                row_values.append(f"[{color}]{pct:.0f}%[/{color}] (n={total})")

        table.add_row(*row_values)

    console.print(table)
    console.print()


def report_reversals(conn: sqlite3.Connection, console: Console, candles: list[dict], min_candles: int) -> None:
    """Reversal rate report: % of candles where mid-candle direction != final winner."""
    console.print("[bold cyan]Reversal Rates[/bold cyan]")
    console.print("  % of candles where mid-candle BTC direction does NOT match final winner\n")

    table = Table(show_header=True)
    table.add_column("Move Bucket", style="bold")
    for label, _, _ in TIME_BUCKETS:
        table.add_column(label, justify="center")

    for move_label, move_lo, move_hi in MOVE_BUCKETS:
        row_values = [move_label]
        for _, time_lo, time_hi in TIME_BUCKETS:
            total = 0
            reversals = 0
            for c in candles:
                snapshots = _load_snapshot_data(conn, c["candle_id"])
                for s in snapshots:
                    tr = s["time_remaining"]
                    abs_move = abs(s["btc_move_from_open"])
                    if time_lo <= tr < time_hi and move_lo <= abs_move < move_hi:
                        total += 1
                        mid_dir = "up" if s["btc_move_from_open"] >= 0 else "down"
                        if mid_dir != c["winner"]:
                            reversals += 1
                        break

            if total == 0:
                row_values.append("—")
            elif total < min_candles:
                pct = reversals / total * 100
                row_values.append(f"[dim]{pct:.0f}% (n={total})[/dim]")
            else:
                pct = reversals / total * 100
                color = "green" if pct <= 10 else "yellow" if pct <= 30 else "red"
                row_values.append(f"[{color}]{pct:.0f}%[/{color}] (n={total})")

        table.add_row(*row_values)

    console.print(table)
    console.print()


def report_optimal_entry(conn: sqlite3.Connection, console: Console, candles: list[dict]) -> None:
    """Optimal entry timing: average best ask price for the winning side at each time bucket."""
    console.print("[bold cyan]Optimal Entry Timing[/bold cyan]")
    console.print("  Average best ask price for the winning side at each time point\n")

    table = Table(show_header=True)
    table.add_column("Time Bucket", style="bold")
    table.add_column("Avg Winner Ask", justify="center")
    table.add_column("Min Winner Ask", justify="center")
    table.add_column("Sample", justify="center")

    for label, time_lo, time_hi in TIME_BUCKETS:
        prices = []
        for c in candles:
            snapshots = _load_snapshot_data(conn, c["candle_id"])
            for s in snapshots:
                tr = s["time_remaining"]
                if time_lo <= tr < time_hi:
                    if c["winner"] == "up" and s["up_best_ask"] is not None:
                        prices.append(s["up_best_ask"])
                    elif c["winner"] == "down" and s["down_best_ask"] is not None:
                        prices.append(s["down_best_ask"])
                    break

        if not prices:
            table.add_row(label, "—", "—", "0")
        else:
            avg_price = sum(prices) / len(prices)
            min_price = min(prices)
            color = "green" if avg_price < 0.40 else "yellow" if avg_price < 0.55 else "white"
            table.add_row(
                label,
                f"[{color}]${avg_price:.3f}[/{color}]",
                f"${min_price:.3f}",
                _confidence_label(len(prices)),
            )

    console.print(table)
    console.print()


def report_move_distribution(console: Console, candles: list[dict]) -> None:
    """Move distribution: percentiles of absolute BTC moves."""
    console.print("[bold cyan]BTC Move Distribution[/bold cyan]")
    console.print("  Percentiles of absolute BTC moves at candle close\n")

    if not candles:
        console.print("  No data.\n")
        return

    moves = sorted(c["abs_move"] for c in candles)

    def percentile(data: list[float], pct: float) -> float:
        idx = int(len(data) * pct / 100)
        return data[min(idx, len(data) - 1)]

    table = Table(show_header=True)
    table.add_column("Percentile", style="bold")
    table.add_column("BTC Move ($)", justify="center")

    for p in [10, 25, 50, 75, 90, 95]:
        val = percentile(moves, p)
        table.add_row(f"{p}th", f"${val:.1f}")

    table.add_row("Mean", f"${sum(moves) / len(moves):.1f}")

    console.print(table)
    console.print()


REPORT_FUNCS = {
    "summary": "summary",
    "momentum": "momentum",
    "reversals": "reversals",
    "entry": "entry",
    "distribution": "distribution",
}


def main() -> None:
    """Entry point for polybot-validate CLI."""
    parser = argparse.ArgumentParser(description="Validate trading assumptions against accumulated market data.")
    parser.add_argument(
        "--report",
        choices=list(REPORT_FUNCS.keys()),
        default=None,
        help="Run a specific report (default: all)",
    )
    parser.add_argument(
        "--min-candles",
        type=int,
        default=10,
        help="Minimum sample size before showing full confidence (default: 10)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to market_history.db (default: data/market_history.db)",
    )
    args = parser.parse_args()

    global DB_PATH
    if args.db:
        DB_PATH = Path(args.db)

    console = Console()
    conn = _connect()

    try:
        candles = _load_candle_data(conn)

        if not candles:
            console.print("[red]No resolved candles in market history. Run the bot to accumulate data.[/red]")
            return

        reports = [args.report] if args.report else list(REPORT_FUNCS.keys())

        for report in reports:
            if report == "summary":
                report_summary(conn, console, candles)
            elif report == "momentum":
                report_momentum(conn, console, candles, args.min_candles)
            elif report == "reversals":
                report_reversals(conn, console, candles, args.min_candles)
            elif report == "entry":
                report_optimal_entry(conn, console, candles)
            elif report == "distribution":
                report_move_distribution(console, candles)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
