"""Confidence calibration tracker — maps stated confidence to actual win rates.

Tracks every trade's stated confidence vs actual outcome. Builds a calibration
curve from historical data and provides a calibrated win probability that can
be used to gate trades (reject when calibrated probability < break-even).

Data is persisted to a JSONL file so calibration improves across sessions.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Confidence is bucketed into bins of this width
BIN_WIDTH = 0.10
# Minimum samples in a bin before we trust the calibration
MIN_SAMPLES = 10
# Default break-even threshold (price + fees)
DEFAULT_BREAK_EVEN = 0.55


@dataclass
class CalibrationBin:
    """A single confidence bin with win/loss tracking."""

    bin_lower: float
    bin_upper: float
    wins: int = 0
    losses: int = 0

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.wins / self.total

    @property
    def is_reliable(self) -> bool:
        return self.total >= MIN_SAMPLES


@dataclass
class CalibrationResult:
    """Result of checking a confidence value against calibration data."""

    stated_confidence: float
    calibrated_win_rate: float
    sample_count: int
    is_reliable: bool  # enough samples to trust
    should_trade: bool  # calibrated win rate > break-even
    reason: str = ""


class ConfidenceCalibrator:
    """Tracks and calibrates AI confidence vs actual outcomes.

    Maintains bins of confidence ranges and their actual win rates.
    Persists data to JSONL for cross-session learning.
    """

    def __init__(self, data_dir: str | Path, break_even: float = DEFAULT_BREAK_EVEN) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._data_path = self._data_dir / "calibration_data.jsonl"
        self._break_even = break_even

        # Build bins from 0.0 to 1.0
        self._bins: dict[float, CalibrationBin] = {}
        lower = 0.0
        while lower < 1.0:
            upper = min(lower + BIN_WIDTH, 1.0)
            self._bins[lower] = CalibrationBin(bin_lower=lower, bin_upper=upper)
            lower = round(lower + BIN_WIDTH, 2)

        # Load historical data
        self._load()

        # Session tracking
        self._pending: dict[str, tuple[float, str, float]] = {}
        # Maps candle_slug → (confidence, token_side, entry_price)

        # Shadow prediction tracking (HOLD cycles — no capital at risk)
        self._shadow_pending: dict[str, tuple[str, float]] = {}
        # Maps candle_slug → (direction, confidence)
        self._shadow_correct: int = 0
        self._shadow_total: int = 0

    def _bin_key(self, confidence: float) -> float:
        """Get the bin lower bound for a confidence value."""
        return round(math.floor(confidence / BIN_WIDTH) * BIN_WIDTH, 2)

    def _load(self) -> None:
        """Load calibration data from JSONL file."""
        if not self._data_path.exists():
            return
        try:
            for line in self._data_path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                record = json.loads(line)
                conf = record.get("confidence", 0.5)
                won = record.get("won", False)
                key = self._bin_key(conf)
                if key in self._bins:
                    if won:
                        self._bins[key].wins += 1
                    else:
                        self._bins[key].losses += 1
            total = sum(b.total for b in self._bins.values())
            if total > 0:
                logger.info("Loaded %d calibration records from %s", total, self._data_path)
        except Exception:
            logger.warning("Could not load calibration data", exc_info=True)

    def _save_record(self, confidence: float, won: bool, token_side: str, entry_price: float, slug: str) -> None:
        """Append a single calibration record to the JSONL file."""
        try:
            record = {
                "confidence": round(confidence, 4),
                "won": won,
                "token_side": token_side,
                "entry_price": round(entry_price, 4),
                "slug": slug,
            }
            with open(self._data_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            logger.warning("Could not save calibration record", exc_info=True)

    def register_trade(self, slug: str, confidence: float, token_side: str, entry_price: float) -> None:
        """Register a new trade for calibration tracking.

        Called when AI makes a BUY/SELL decision.
        The outcome will be recorded when the candle resolves.
        """
        self._pending[slug] = (confidence, token_side, entry_price)

    def register_shadow(self, slug: str, direction: str, confidence: float) -> None:
        """Register a shadow prediction (HOLD cycle — no capital at risk).

        Called when AI returns HOLD but still predicts a direction.
        Outcome recorded when the candle resolves.
        """
        if direction in ("up", "down"):
            self._shadow_pending[slug] = (direction, confidence)

    def record_outcome(self, slug: str, winner: str) -> None:
        """Record the outcome of a candle resolution for calibration.

        Called when a candle resolves. Matches pending trades and shadow
        predictions to outcomes.
        """
        # Score actual trades
        if slug in self._pending:
            confidence, token_side, entry_price = self._pending.pop(slug)
            won = (token_side == winner)

            # Update bin
            key = self._bin_key(confidence)
            if key in self._bins:
                if won:
                    self._bins[key].wins += 1
                else:
                    self._bins[key].losses += 1

            # Persist
            self._save_record(confidence, won, token_side, entry_price, slug)

            logger.info(
                "Calibration: conf=%.2f side=%s winner=%s → %s (bin %s: %d/%d = %.0f%%)",
                confidence, token_side, winner,
                "WIN" if won else "LOSS",
                f"{key:.2f}-{key + BIN_WIDTH:.2f}",
                self._bins[key].wins, self._bins[key].total,
                self._bins[key].win_rate * 100,
            )

        # Score shadow predictions (HOLD cycles)
        if slug in self._shadow_pending:
            shadow_dir, shadow_conf = self._shadow_pending.pop(slug)
            self._shadow_total += 1
            shadow_correct = (shadow_dir == winner)
            if shadow_correct:
                self._shadow_correct += 1
            logger.info(
                "Shadow prediction: predicted=%s winner=%s → %s (accuracy: %d/%d = %.0f%%)",
                shadow_dir, winner,
                "CORRECT" if shadow_correct else "WRONG",
                self._shadow_correct, self._shadow_total,
                (self._shadow_correct / self._shadow_total * 100) if self._shadow_total > 0 else 0,
            )

    def check(self, confidence: float) -> CalibrationResult:
        """Check if a given confidence level should be trusted for trading.

        Returns calibration data including whether the trade should proceed.
        """
        key = self._bin_key(confidence)
        b = self._bins.get(key)

        if b is None or not b.is_reliable:
            # Not enough data — allow trade but flag as uncalibrated
            return CalibrationResult(
                stated_confidence=confidence,
                calibrated_win_rate=confidence,  # use stated as best guess
                sample_count=b.total if b else 0,
                is_reliable=False,
                should_trade=True,
                reason=f"Insufficient calibration data ({b.total if b else 0}/{MIN_SAMPLES} samples)",
            )

        should_trade = b.win_rate >= self._break_even
        reason = (
            f"Calibrated: {b.win_rate:.0%} win rate from {b.total} trades "
            f"(need {self._break_even:.0%} break-even)"
        )

        return CalibrationResult(
            stated_confidence=confidence,
            calibrated_win_rate=b.win_rate,
            sample_count=b.total,
            is_reliable=True,
            should_trade=should_trade,
            reason=reason,
        )

    def get_calibration_summary(self) -> str:
        """Generate a human-readable calibration summary for the AI prompt."""
        lines = []
        for key in sorted(self._bins.keys()):
            b = self._bins[key]
            if b.total == 0:
                continue
            reliability = "reliable" if b.is_reliable else "insufficient data"
            # Overconfidence warning: actual win rate significantly below stated confidence range
            if b.is_reliable and b.win_rate < b.bin_lower:
                lines.append(
                    f"  {b.bin_lower:.2f}-{b.bin_upper:.2f}: "
                    f"OVERCONFIDENT — actual {b.win_rate:.0%} win rate but you state "
                    f"{b.bin_lower:.0%}-{b.bin_upper:.0%} confidence "
                    f"({b.wins}W/{b.losses}L from {b.total} trades)"
                )
            else:
                lines.append(
                    f"  {b.bin_lower:.2f}-{b.bin_upper:.2f}: "
                    f"{b.win_rate:.0%} win rate ({b.wins}W/{b.losses}L, {reliability})"
                )
        if not lines and self._shadow_total == 0:
            return "No calibration data yet."
        parts = []
        if lines:
            parts.append("Confidence Calibration (stated → actual win rate):\n" + "\n".join(lines))
        if self._shadow_total > 0:
            shadow_acc = self._shadow_correct / self._shadow_total * 100
            parts.append(
                f"Shadow Predictions (HOLD cycles): {self._shadow_correct}/{self._shadow_total} "
                f"correct ({shadow_acc:.0f}% accuracy)"
            )
        return "\n".join(parts) if parts else "No calibration data yet."

    @property
    def total_records(self) -> int:
        return sum(b.total for b in self._bins.values())
