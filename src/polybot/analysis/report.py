"""Trade log analysis — reads JSONL logs and prints performance stats."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from polybot.models import Action


def _load_records(log_dir: str) -> list[dict]:
    """Load all trade records from JSONL files in the log directory."""
    log_path = Path(log_dir)
    if not log_path.exists():
        return []

    records = []
    for f in sorted(log_path.glob("trades_*.jsonl")):
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def _compute_stats(records: list[dict]) -> dict:
    """Compute performance statistics from trade records."""
    if not records:
        return {}

    # Filter to cycles with actual trades (non-HOLD with fills)
    trades = [r for r in records if r.get("action") != Action.HOLD.value and r.get("fill_size", 0) > 0]
    total_cycles = len(records)
    total_trades = len(trades)

    if not trades:
        return {
            "total_cycles": total_cycles,
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "avg_trade_size": 0.0,
            "total_fees": 0.0,
            "final_portfolio_value": records[-1].get("portfolio_value", 0),
            "final_cash": records[-1].get("cash", 0),
        }

    # PnL series from each cycle's portfolio value changes
    portfolio_values = [r.get("portfolio_value", 0) for r in records if r.get("portfolio_value")]
    returns = []
    for i in range(1, len(portfolio_values)):
        prev = portfolio_values[i - 1]
        if prev > 0:
            returns.append((portfolio_values[i] - prev) / prev)

    # Win rate: count sells with positive realized PnL
    sells = [r for r in trades if r.get("action") == Action.SELL.value]
    wins = sum(1 for r in sells if r.get("realized_pnl", 0) > 0) if sells else 0
    win_rate = wins / len(sells) if sells else 0.0

    # Total PnL
    total_pnl = records[-1].get("realized_pnl", 0) + records[-1].get("unrealized_pnl", 0)

    # Sharpe ratio (annualized, assuming ~1440 cycles/day for 1-min intervals)
    if len(returns) > 1:
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std_ret = math.sqrt(variance) if variance > 0 else 0.0
        sharpe_ratio = (mean_ret / std_ret * math.sqrt(1440)) if std_ret > 0 else 0.0
    else:
        sharpe_ratio = 0.0

    # Max drawdown
    peak = 0.0
    max_dd = 0.0
    for v in portfolio_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Average trade size and fees
    avg_size = sum(r.get("fill_size", 0) for r in trades) / total_trades
    total_fees = sum(r.get("fee_amount", 0) for r in trades)

    return {
        "total_cycles": total_cycles,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_dd,
        "avg_trade_size": avg_size,
        "total_fees": total_fees,
        "final_portfolio_value": records[-1].get("portfolio_value", 0),
        "final_cash": records[-1].get("cash", 0),
    }


def main() -> None:
    """Entry point for polybot-analyze CLI."""
    log_dir = sys.argv[1] if len(sys.argv) > 1 else "logs"

    console = Console()
    records = _load_records(log_dir)

    if not records:
        console.print(f"[yellow]No trade logs found in {log_dir}/[/yellow]")
        sys.exit(0)

    stats = _compute_stats(records)
    if not stats:
        console.print("[yellow]No data to analyze[/yellow]")
        sys.exit(0)

    table = Table(title="Polybot Performance Report")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")

    table.add_row("Total Cycles", str(stats["total_cycles"]))
    table.add_row("Total Trades", str(stats["total_trades"]))
    table.add_row("Win Rate", f"{stats['win_rate']:.1%}")
    table.add_row("Total PnL", f"${stats['total_pnl']:+,.2f}")
    table.add_row("Sharpe Ratio", f"{stats['sharpe_ratio']:.2f}")
    table.add_row("Max Drawdown", f"{stats['max_drawdown']:.2%}")
    table.add_row("Avg Trade Size", f"{stats['avg_trade_size']:.2f} shares")
    table.add_row("Total Fees Paid", f"${stats['total_fees']:.2f}")
    table.add_row("Final Portfolio", f"${stats['final_portfolio_value']:,.2f}")
    table.add_row("Final Cash", f"${stats['final_cash']:,.2f}")

    console.print()
    console.print(table)
    console.print()


if __name__ == "__main__":
    main()
