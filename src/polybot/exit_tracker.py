"""Quantitative exit strategy tracker — logs exits and measures what-if outcomes.

For every SELL (exit), records:
- The exit price and time remaining
- The entry price (from portfolio avg entry)
- After resolution: what the position would have been worth if held to expiry

This builds a dataset to answer: "Is early profit-taking actually optimal,
or are we leaving money on the table?"

Data is persisted to JSONL for cross-session analysis.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ExitRecord:
    """A single exit event with what-if analysis."""

    slug: str
    token_side: str
    entry_price: float
    exit_price: float
    exit_size: float
    time_remaining: float
    # Populated after resolution
    winner: str = ""
    held_value: float = 0.0  # What position would be worth at resolution ($1 or $0 per share)
    actual_pnl: float = 0.0  # PnL from the exit
    missed_pnl: float = 0.0  # PnL difference: held_to_expiry - actual_exit


class ExitTracker:
    """Tracks exits and computes what-if outcomes for strategy optimization."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._data_path = self._data_dir / "exit_analysis.jsonl"

        # Pending exits awaiting resolution
        self._pending: dict[str, list[ExitRecord]] = {}  # slug -> exits

        # Aggregate stats
        self._total_exits = 0
        self._exits_better_than_hold = 0
        self._total_saved = 0.0  # positive = exits saved money vs holding
        self._total_missed = 0.0  # positive = exits missed upside

        # Load historical data for stats
        self._load()

    def _load(self) -> None:
        """Load historical exit data for aggregate stats."""
        if not self._data_path.exists():
            return
        try:
            for line in self._data_path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("winner"):  # Only count resolved exits
                    self._total_exits += 1
                    missed = r.get("missed_pnl", 0)
                    if missed <= 0:
                        self._exits_better_than_hold += 1
                        self._total_saved += abs(missed)
                    else:
                        self._total_missed += missed
            if self._total_exits > 0:
                logger.info(
                    "Loaded %d exit records: %d better than hold (%.0f%%), "
                    "saved $%.2f, missed $%.2f",
                    self._total_exits,
                    self._exits_better_than_hold,
                    self._exits_better_than_hold / self._total_exits * 100,
                    self._total_saved,
                    self._total_missed,
                )
        except Exception:
            logger.warning("Could not load exit analysis data", exc_info=True)

    def _save_record(self, record: ExitRecord) -> None:
        """Append an exit record to JSONL."""
        try:
            with open(self._data_path, "a") as f:
                f.write(json.dumps({
                    "slug": record.slug,
                    "token_side": record.token_side,
                    "entry_price": round(record.entry_price, 4),
                    "exit_price": round(record.exit_price, 4),
                    "exit_size": round(record.exit_size, 2),
                    "time_remaining": round(record.time_remaining, 1),
                    "winner": record.winner,
                    "held_value": round(record.held_value, 4),
                    "actual_pnl": round(record.actual_pnl, 4),
                    "missed_pnl": round(record.missed_pnl, 4),
                }) + "\n")
        except Exception:
            logger.warning("Could not save exit record", exc_info=True)

    def register_exit(
        self,
        slug: str,
        token_side: str,
        entry_price: float,
        exit_price: float,
        exit_size: float,
        time_remaining: float,
    ) -> None:
        """Register a SELL (exit) for later what-if analysis."""
        record = ExitRecord(
            slug=slug,
            token_side=token_side,
            entry_price=entry_price,
            exit_price=exit_price,
            exit_size=exit_size,
            time_remaining=time_remaining,
        )
        self._pending.setdefault(slug, []).append(record)

    def record_outcome(self, slug: str, winner: str) -> None:
        """Record candle resolution outcome for pending exits."""
        exits = self._pending.pop(slug, [])
        for record in exits:
            record.winner = winner
            # What would the position be worth at resolution?
            won = (record.token_side == winner)
            record.held_value = 1.0 if won else 0.0

            # Actual PnL from the exit
            record.actual_pnl = (record.exit_price - record.entry_price) * record.exit_size

            # What-if PnL if held to expiry
            held_pnl = (record.held_value - record.entry_price) * record.exit_size

            # Missed PnL: positive means we left money on the table
            record.missed_pnl = held_pnl - record.actual_pnl

            self._total_exits += 1
            if record.missed_pnl <= 0:
                self._exits_better_than_hold += 1
                self._total_saved += abs(record.missed_pnl)
            else:
                self._total_missed += record.missed_pnl

            self._save_record(record)

            logger.info(
                "Exit analysis: %s %s — exit@%.3f, %s won, "
                "held_value=%.2f, actual_pnl=$%.2f, missed_pnl=$%.2f (%s)",
                slug, record.token_side,
                record.exit_price,
                winner,
                record.held_value,
                record.actual_pnl,
                record.missed_pnl,
                "GOOD EXIT" if record.missed_pnl <= 0 else "MISSED UPSIDE",
            )

    def get_summary(self) -> str:
        """Generate a human-readable summary for the AI prompt."""
        if self._total_exits == 0:
            return ""
        good_pct = self._exits_better_than_hold / self._total_exits * 100
        return (
            f"Exit Analysis ({self._total_exits} exits): "
            f"{self._exits_better_than_hold}/{self._total_exits} better than hold ({good_pct:.0f}%), "
            f"saved ${self._total_saved:.2f}, missed ${self._total_missed:.2f}"
        )

    @property
    def good_exit_rate(self) -> float:
        if self._total_exits == 0:
            return 0.0
        return self._exits_better_than_hold / self._total_exits
