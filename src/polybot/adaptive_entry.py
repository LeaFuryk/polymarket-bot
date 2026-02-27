"""Adaptive entry threshold tracker — learns optimal BTC move threshold and max entry price.

Tracks rolling candle outcomes to calibrate:
- BTC move threshold ($20–$50, V-shaped) based on rolling reversal rate
- Max entry price cap based on recent winner ask prices

V-shaped threshold formula: peaks at 50% reversal (max uncertainty → $50),
low at extremes (strong signal either momentum or contrarian → $20).
  threshold = max(20, min(50, 50 - abs(rate - 0.5) * 60))

At 0% reversals → $20 (strong momentum, direction reliable).
At 50% → $50 (coin flip, need big BTC moves for any signal).
At 80% → $32 (strong reversal, contrarian edge — enter early, bet opposite).

Data is persisted to JSONL for cross-session continuity.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Default thresholds used when insufficient history
DEFAULT_BTC_THRESHOLD = 30.0  # $30 BTC move
DEFAULT_MAX_ENTRY = 0.60  # $0.60 max ask


@dataclass
class CandleOutcome:
    """Resolved candle outcome for adaptive learning."""

    slug: str
    winner: str  # "up" or "down"
    btc_open: float
    btc_close: float
    direction_at_20: str  # BTC direction when move first crossed $20
    reversed: bool  # did the $20 direction disagree with the winner?
    winner_ask_at_20: float  # ask price for the winning side at the $20 cross


class AdaptiveEntryTracker:
    """Learns optimal entry thresholds from rolling candle history."""

    def __init__(self, data_dir: str | Path, window: int = 10) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._data_path = self._data_dir / "adaptive_entry.jsonl"
        self._window = window

        # Rolling history of resolved candle outcomes
        self._history: list[CandleOutcome] = []

        # Computed adaptive thresholds
        self.btc_threshold: float = DEFAULT_BTC_THRESHOLD
        self.max_entry_price: float = DEFAULT_MAX_ENTRY
        self._signal_type: str = "UNCERTAIN"  # MOMENTUM / CONTRARIAN / UNCERTAIN

        # Load persisted data
        self._load()
        self._recompute()

    def _load(self) -> None:
        """Load historical candle outcomes from JSONL."""
        if not self._data_path.exists():
            return
        try:
            for line in self._data_path.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                r = json.loads(line)
                outcome = CandleOutcome(
                    slug=r["slug"],
                    winner=r["winner"],
                    btc_open=r["btc_open"],
                    btc_close=r["btc_close"],
                    direction_at_20=r["direction_at_20"],
                    reversed=r["reversed"],
                    winner_ask_at_20=r["winner_ask_at_20"],
                )
                self._history.append(outcome)

            # Keep only the last N*2 for file size, but use last N for stats
            if len(self._history) > self._window * 4:
                self._history = self._history[-(self._window * 4):]

            if self._history:
                logger.info(
                    "Loaded %d adaptive entry records (window=%d)",
                    len(self._history), self._window,
                )
        except Exception:
            logger.warning("Could not load adaptive entry data", exc_info=True)

    def _save_record(self, outcome: CandleOutcome) -> None:
        """Append a candle outcome to JSONL."""
        try:
            with open(self._data_path, "a") as f:
                f.write(json.dumps({
                    "slug": outcome.slug,
                    "winner": outcome.winner,
                    "btc_open": round(outcome.btc_open, 2),
                    "btc_close": round(outcome.btc_close, 2),
                    "direction_at_20": outcome.direction_at_20,
                    "reversed": outcome.reversed,
                    "winner_ask_at_20": round(outcome.winner_ask_at_20, 4),
                }) + "\n")
        except Exception:
            logger.warning("Could not save adaptive entry record", exc_info=True)

    def _recompute(self) -> None:
        """Recompute adaptive thresholds from rolling window."""
        window = self._history[-self._window:]

        if len(window) < self._window:
            # Not enough data — use conservative defaults
            self.btc_threshold = DEFAULT_BTC_THRESHOLD
            self.max_entry_price = DEFAULT_MAX_ENTRY
            logger.info(
                "Adaptive entry: insufficient history (%d/%d), using defaults "
                "(btc_thresh=$%.0f, max_entry=$%.2f)",
                len(window), self._window,
                self.btc_threshold, self.max_entry_price,
            )
            return

        # Rolling reversal rate
        reversals = sum(1 for c in window if c.reversed)
        reversal_rate = reversals / len(window)

        # V-shaped BTC threshold: peaks at 50% reversal (max uncertainty),
        # low at extremes (momentum or contrarian edge).
        # deviation=0 at 50% → threshold=$50 (coin flip, need big moves)
        # deviation=0.5 at 0% or 100% → threshold=$20 (predictable, enter early)
        deviation = abs(reversal_rate - 0.5)
        self.btc_threshold = max(20.0, min(50.0, 50.0 - deviation * 60.0))

        # Signal type for logging/dashboard
        if reversal_rate > 0.55:
            self._signal_type = "CONTRARIAN"
        elif reversal_rate < 0.35:
            self._signal_type = "MOMENTUM"
        else:
            self._signal_type = "UNCERTAIN"

        # Adaptive max entry price: avg winner ask + $0.10, capped at $0.65
        winner_asks = [c.winner_ask_at_20 for c in window if c.winner_ask_at_20 > 0]
        if winner_asks:
            avg_winner_ask = sum(winner_asks) / len(winner_asks)
            self.max_entry_price = min(avg_winner_ask + 0.10, 0.65)
        else:
            self.max_entry_price = DEFAULT_MAX_ENTRY

        logger.info(
            "Adaptive entry updated: reversal_rate=%.0f%% (%d/%d) → "
            "signal=%s, btc_thresh=$%.0f (dev=%.2f), "
            "avg_winner_ask=$%.3f → max_entry=$%.2f",
            reversal_rate * 100, reversals, len(window),
            self._signal_type, self.btc_threshold, deviation,
            avg_winner_ask if winner_asks else 0,
            self.max_entry_price,
        )

    def should_trigger(self, abs_btc_move: float, min_ask: float) -> bool:
        """Check if conditions meet adaptive thresholds for triggering AI.

        Args:
            abs_btc_move: Absolute BTC price change from candle open
            min_ask: Minimum ask price across UP and DOWN tokens

        Returns:
            True if BTC has moved enough AND entry price is reasonable
        """
        return (
            abs_btc_move >= self.btc_threshold
            and min_ask <= self.max_entry_price
        )

    def record_outcome(
        self,
        slug: str,
        winner: str,
        btc_open: float,
        btc_close: float,
        prefilter_history: list,
    ) -> None:
        """Record a candle resolution and update adaptive thresholds.

        Retroactively determines the BTC direction at the $20 cross point
        and what the winner-side ask was at that moment.

        Args:
            slug: Candle slug
            winner: "up" or "down"
            btc_open: BTC price at candle open
            btc_close: BTC price at candle close
            prefilter_history: List of PreFilterSnapshot from the candle
        """
        # Find the first snapshot where BTC moved >= $20 from open
        direction_at_20 = ""
        winner_ask_at_20 = 0.0

        for snap in prefilter_history:
            btc_move = snap.btc_move_from_open
            if abs(btc_move) >= 20.0:
                direction_at_20 = "up" if btc_move > 0 else "down"
                # Get the winner-side ask at this point
                if winner == "up":
                    winner_ask_at_20 = snap.best_entry_up
                else:
                    winner_ask_at_20 = snap.best_entry_down
                break

        # If BTC never moved $20, use final direction
        if not direction_at_20:
            final_move = btc_close - btc_open
            direction_at_20 = "up" if final_move >= 0 else "down"
            # Use the last snapshot's ask if available
            if prefilter_history:
                last_snap = prefilter_history[-1]
                if winner == "up":
                    winner_ask_at_20 = last_snap.best_entry_up
                else:
                    winner_ask_at_20 = last_snap.best_entry_down

        reversed_flag = direction_at_20 != winner

        outcome = CandleOutcome(
            slug=slug,
            winner=winner,
            btc_open=btc_open,
            btc_close=btc_close,
            direction_at_20=direction_at_20,
            reversed=reversed_flag,
            winner_ask_at_20=winner_ask_at_20,
        )

        self._history.append(outcome)
        self._save_record(outcome)
        self._recompute()

        logger.info(
            "Adaptive entry recorded: %s winner=%s, dir@$20=%s, reversed=%s, "
            "winner_ask@$20=$%.3f",
            slug, winner, direction_at_20, reversed_flag, winner_ask_at_20,
        )

    @property
    def regime(self) -> str:
        """Market regime label derived from continuous reversal rate."""
        rate = self.rolling_reversal_rate
        if rate < 0.20:
            return "CALM"
        elif rate < 0.40:
            return "MODERATE"
        else:
            return "CHOPPY"

    @property
    def signal_type(self) -> str:
        """Signal type: MOMENTUM (<35%), UNCERTAIN (35-55%), CONTRARIAN (>55%)."""
        return self._signal_type

    @property
    def rolling_reversal_rate(self) -> float:
        """Current rolling reversal rate."""
        window = self._history[-self._window:]
        if not window:
            return 0.0
        return sum(1 for c in window if c.reversed) / len(window)

    @property
    def has_enough_history(self) -> bool:
        """Whether we have enough candles for adaptive thresholds."""
        return len(self._history) >= self._window

    def get_summary(self) -> str:
        """Generate a human-readable summary for logging/dashboard."""
        window = self._history[-self._window:]
        if not window:
            return "Adaptive entry: no history yet"
        reversal_rate = self.rolling_reversal_rate
        return (
            f"Adaptive entry (last {len(window)} candles): "
            f"reversal_rate={reversal_rate:.0%}, "
            f"signal={self._signal_type}, "
            f"btc_thresh=${self.btc_threshold:.0f}, "
            f"max_entry=${self.max_entry_price:.2f}"
        )

    def get_ai_context(self) -> str | None:
        """Build reversal rate context for the AI prompt.

        Returns None if insufficient history. Otherwise returns a section
        with the actual reversal rate and signal interpretation.
        """
        if not self.has_enough_history:
            return None

        rate = self.rolling_reversal_rate
        window = self._history[-self._window:]
        reversals = sum(1 for c in window if c.reversed)

        lines = [
            "## Reversal Rate Context (Adaptive Entry)",
            f"- Rolling reversal rate: **{rate:.0%}** "
            f"({reversals} of last {len(window)} candles reversed from initial BTC direction)",
            f"- Signal type: **{self._signal_type}**",
            f"- BTC move threshold: ${self.btc_threshold:.0f}",
        ]

        if rate > 0.55:
            lines.extend([
                "",
                f"⚠ **High reversal rate ({rate:.0%})**: The initial BTC direction (first $20 move) "
                f"has been WRONG {rate:.0%} of the time recently. The cheap (contrarian) side — "
                f"opposite to the current BTC move — may be the better entry. "
                f"When reversals dominated, the winning side's average ask was "
                f"${self._avg_reversal_winner_ask():.2f} at the $20 cross.",
            ])
        elif rate < 0.25:
            lines.extend([
                "",
                f"✓ **Low reversal rate ({rate:.0%})**: BTC direction has been reliable. "
                f"The initial move is continuing {1-rate:.0%} of the time. "
                f"Momentum entries aligned with the current BTC direction are favored.",
            ])

        return "\n".join(lines)

    def _avg_reversal_winner_ask(self) -> float:
        """Average winner ask price on reversed candles in the window."""
        window = self._history[-self._window:]
        asks = [c.winner_ask_at_20 for c in window if c.reversed and c.winner_ask_at_20 > 0]
        return sum(asks) / len(asks) if asks else 0.0
