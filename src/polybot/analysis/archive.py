"""Iteration archiver — snapshots all generated artifacts and computes a summary."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from polybot.analysis.report import _compute_stats, _load_records

ROOT = Path.cwd()
ARCHIVE_DIR = ROOT / "archive"
LOG_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"

# Files to archive from logs/
LOG_GLOBS = [
    "trades_*.jsonl",
    "resolutions_*.jsonl",
    "polybot.db",
    "polybot.log",
    "agent_state.json",
    "calibration_data.jsonl",
    "exit_analysis.jsonl",
    "ml_model.json",
    "dashboard_data.json",
    "adaptive_entry.jsonl",
]

# AI-written knowledge files (not the read-only base files)
KNOWLEDGE_FILES = [
    "observations.jsonl",
    "session_history.md",
]

# Feature config may have been tuned by reflection
DATA_FILES = [
    "feature_config.json",
]


def _next_iter_label() -> str:
    """Auto-generate the next iter_NNN label."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(
        d.name
        for d in ARCHIVE_DIR.iterdir()
        if d.is_dir() and d.name.startswith("iter_")
    )
    if not existing:
        return "iter_001"
    last_num = max(int(d.split("_")[1]) for d in existing)
    return f"iter_{last_num + 1:03d}"


def _copy_files(dest: Path) -> int:
    """Copy all artifact files into the archive directory. Returns count copied."""
    copied = 0

    # logs/
    logs_dest = dest / "logs"
    logs_dest.mkdir(parents=True, exist_ok=True)
    for pattern in LOG_GLOBS:
        for f in LOG_DIR.glob(pattern):
            shutil.copy2(f, logs_dest / f.name)
            copied += 1

    # data/knowledge/ (AI-written only)
    knowledge_dest = dest / "data" / "knowledge"
    knowledge_dest.mkdir(parents=True, exist_ok=True)
    for name in KNOWLEDGE_FILES:
        src = KNOWLEDGE_DIR / name
        if src.exists():
            shutil.copy2(src, knowledge_dest / name)
            copied += 1

    # data/ (feature config)
    data_dest = dest / "data"
    data_dest.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES:
        src = DATA_DIR / name
        if src.exists():
            shutil.copy2(src, data_dest / name)
            copied += 1

    return copied


def _load_resolutions(log_dir: Path) -> list[dict]:
    """Load all resolution records from JSONL files."""
    records = []
    for f in sorted(log_dir.glob("resolutions_*.jsonl")):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def _ts_to_iso(ts: float | str) -> str:
    """Convert a timestamp (epoch float or ISO string) to ISO date string."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(ts)


def _compute_summary(label: str, dest: Path) -> dict:
    """Compute iteration summary from archived artifacts.

    Uses resolutions JSONL as the source of truth for PnL and win/loss
    counts (never capped, unlike the in-memory dashboard list).
    Trade records are used only for fees, AI cost, cycle counts, and
    portfolio snapshots.
    """
    log_dir = dest / "logs"
    records = _load_records(str(log_dir))
    resolutions = _load_resolutions(log_dir)

    # Date range from trade records (timestamps may be epoch floats or ISO strings)
    raw_ts = [r.get("timestamp") for r in records if r.get("timestamp")]
    if raw_ts:
        date_start = _ts_to_iso(min(raw_ts))
        date_end = _ts_to_iso(max(raw_ts))
    else:
        date_start = None
        date_end = None

    # PnL, wins, losses from resolutions (source of truth)
    total_pnl = sum(r.get("total_pnl", 0) for r in resolutions)
    wins = sum(1 for r in resolutions if r.get("total_pnl", 0) > 0.001)
    losses = sum(1 for r in resolutions if r.get("total_pnl", 0) < -0.001)
    total_wl = wins + losses
    win_rate = wins / total_wl if total_wl > 0 else 0.0

    # Fees and AI cost from trade records
    total_fees = sum(r.get("fee_amount", 0) for r in records)
    ai_cost = sum(r.get("ai_cost", 0) for r in records)

    # Trade counts
    total_cycles = len(records)
    total_trades = sum(
        1 for r in records
        if r.get("action") != "HOLD" and r.get("fill_size", 0) > 0
    )

    # Final portfolio state from last trade record
    final_cash = records[-1].get("cash", 0) if records else 0
    final_portfolio = records[-1].get("portfolio_value", 0) if records else 0

    net_result = total_pnl - total_fees - ai_cost

    # Reflections count from observations
    observations_file = dest / "data" / "knowledge" / "observations.jsonl"
    reflections = 0
    if observations_file.exists():
        with open(observations_file) as fh:
            reflections = sum(1 for line in fh if line.strip())

    # Enabled indicators from feature config
    feature_config_file = dest / "data" / "feature_config.json"
    enabled_indicators: list[str] = []
    if feature_config_file.exists():
        with open(feature_config_file) as fh:
            fc = json.load(fh)
            if isinstance(fc, list):
                enabled_indicators = [
                    f.get("name", "") for f in fc if f.get("enabled")
                ]
            elif isinstance(fc, dict) and "indicators" in fc:
                enabled_indicators = [
                    f.get("name", "") for f in fc["indicators"] if f.get("enabled")
                ]

    # Candle count from SQLite if available
    total_candles = len(resolutions)
    db_path = log_dir / "polybot.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT COUNT(*) FROM candles").fetchone()
            if row and row[0] > total_candles:
                total_candles = row[0]
            conn.close()
        except Exception:
            pass

    from importlib.metadata import version as _pkg_version

    try:
        bot_version = "v" + _pkg_version("polybot")
    except Exception:
        bot_version = "unknown"

    summary = {
        "label": label,
        "version": bot_version,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "date_range": {"start": date_start, "end": date_end},
        "total_candles": total_candles,
        "total_trades": total_trades,
        "total_cycles": total_cycles,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "ai_cost": ai_cost,
        "net_result": net_result,
        "final_cash": final_cash,
        "final_portfolio_value": final_portfolio,
        "reflections_count": reflections,
        "enabled_indicators": enabled_indicators,
    }
    return summary


def _rebuild_iterations_json() -> int:
    """Rebuild logs/iterations.json from all archive summaries.

    This ensures the dashboard always reflects the latest archived iterations,
    even when the bot isn't running. Uses the same enrichment logic as the agent.
    """
    from polybot.agent import TradingAgent

    summaries: list[dict] = []
    if not ARCHIVE_DIR.exists():
        return 0

    for summary_path in sorted(ARCHIVE_DIR.glob("*/summary.json")):
        try:
            data = json.loads(summary_path.read_text())
            iter_dir = summary_path.parent
            dash_path = iter_dir / "logs" / "dashboard_data.json"
            if dash_path.exists():
                dd = json.loads(dash_path.read_text())
                TradingAgent._enrich_iteration_summary(data, dd, iter_dir)
            summaries.append(data)
        except Exception:
            pass

    if summaries:
        iter_path = LOG_DIR / "iterations.json"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        iter_path.write_text(json.dumps(summaries, indent=2) + "\n")

    return len(summaries)


def _clean_working_dirs() -> None:
    """Remove generated artifacts from working directories.

    NOTE: data/market_history.db is intentionally excluded — it accumulates
    market data across all iterations for statistical validation.
    """
    # Clean logs (keep the directory)
    for pattern in LOG_GLOBS:
        for f in LOG_DIR.glob(pattern):
            f.unlink()
    # Also clean WAL/SHM files
    for f in LOG_DIR.glob("polybot.db-*"):
        f.unlink()

    # Clean AI-written knowledge files
    for name in KNOWLEDGE_FILES:
        f = KNOWLEDGE_DIR / name
        if f.exists():
            f.unlink()


def main() -> None:
    """Entry point for polybot-archive CLI."""
    parser = argparse.ArgumentParser(
        description="Archive a complete iteration snapshot and optionally clean working directories."
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Custom label for the archive (default: auto-increment iter_NNN)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip cleaning working directories after archiving",
    )
    args = parser.parse_args()

    console = Console()
    label = args.name or _next_iter_label()
    dest = ARCHIVE_DIR / label

    if dest.exists():
        console.print(f"[red]Archive '{label}' already exists at {dest}[/red]")
        sys.exit(1)

    # Check there's something to archive
    has_logs = any(LOG_DIR.glob("trades_*.jsonl")) or (LOG_DIR / "polybot.db").exists()
    if not has_logs:
        console.print("[yellow]Nothing to archive — no trade logs or database found in logs/[/yellow]")
        sys.exit(0)

    # Copy files
    dest.mkdir(parents=True, exist_ok=True)
    copied = _copy_files(dest)
    console.print(f"[green]Copied {copied} files → {dest}[/green]")

    # Compute and write summary
    summary = _compute_summary(label, dest)
    summary_path = dest / "summary.json"
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    console.print(f"[green]Summary written → {summary_path}[/green]")

    # Print key metrics
    console.print()
    console.print(f"  [cyan]Label:[/cyan]      {summary['label']}")
    console.print(f"  [cyan]Candles:[/cyan]    {summary['total_candles']}")
    console.print(f"  [cyan]Trades:[/cyan]     {summary['total_trades']}")
    console.print(f"  [cyan]Win Rate:[/cyan]   {summary['win_rate']:.1%}")
    console.print(f"  [cyan]PnL:[/cyan]        ${summary['total_pnl']:+,.2f}")
    console.print(f"  [cyan]Net Result:[/cyan] ${summary['net_result']:+,.2f}")
    console.print()

    # Clean
    if not args.no_clean:
        _clean_working_dirs()
        console.print("[green]Working directories cleaned.[/green]")
    else:
        console.print("[yellow]Skipped cleaning (--no-clean).[/yellow]")

    # Rebuild iterations.json so the dashboard shows all iterations
    iter_count = _rebuild_iterations_json()
    console.print(f"[green]Rebuilt iterations.json with {iter_count} iterations.[/green]")


if __name__ == "__main__":
    main()
