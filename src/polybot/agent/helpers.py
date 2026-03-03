"""Agent helper functions — logging setup and PnL reconstruction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.config import AppConfig


def setup_logging(config: AppConfig) -> None:
    """Configure structured logging with console + file output."""
    log_dir = Path(config.logging.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    fh = logging.FileHandler(log_dir / "polybot.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler (only if dashboard is off — dashboard replaces stdout)
    if not config.logging.dashboard_enabled:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)


def compute_pnl_from_trades(trades: list[dict], winner: str) -> float:
    """Reconstruct PnL for an unresolved candle from its logged trades."""
    up_shares = 0.0
    up_cost = 0.0
    down_shares = 0.0
    down_cost = 0.0

    for t in trades:
        if t.get("risk_blocked") or not t.get("fill_price"):
            continue
        size = t.get("fill_size") or t.get("size") or t.get("decision_size") or 0
        price = t["fill_price"]
        side = t.get("token_side", "up")
        action = t.get("action", "HOLD")

        if action == "BUY":
            if side == "up":
                up_shares += size
                up_cost += size * price
            else:
                down_shares += size
                down_cost += size * price
        elif action == "SELL":
            if side == "up":
                up_shares -= size
                up_cost -= size * price
            else:
                down_shares -= size
                down_cost -= size * price

    # Settlement: winning token pays $1, losing pays $0
    if winner == "up":
        pnl = (up_shares * 1.0 - up_cost) + (0 - down_cost)
    else:
        pnl = (0 - up_cost) + (down_shares * 1.0 - down_cost)

    return pnl
