"""Adaptive entry threshold tracker — learns optimal BTC move threshold and max entry price.

Tracks rolling candle outcomes to calibrate:
- BTC move threshold ($20–$100) based on fakeout magnitudes from recent candles
- Max entry price cap based on recent winner ask prices

Fakeout-based threshold: for each candle, measures how far BTC moved in the
*wrong direction* (peak move opposite to the eventual winner) before the winner
was decided. Sets the threshold above typical fakeouts so the bot only enters
on signals stronger than recent noise.

  threshold = P50(last 5 fakeout magnitudes), clamped to [$20, adaptive_cap]
  adaptive_cap = max($50, min($100, P75 * 1.2))

Small fakeouts [0..25] → cap=$50, threshold ~$25 (clean signals, enter early).
Large fakeouts [10..80] → cap=$94, threshold ~$57 (noisy market, wait for confirmation).

Falls back to V-shaped formula when peak data is unavailable (old JSONL records).

Data is persisted to JSONL for cross-session continuity.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Default thresholds used when insufficient history
DEFAULT_BTC_THRESHOLD = 30.0  # $30 BTC move
DEFAULT_MAX_ENTRY = 0.60  # $0.60 max ask

# Retracement-based reversal detection constants
RETRACEMENT_THRESHOLD = 0.80  # 80% of peak must be retraced
MIN_PEAK_COMMIT = 25.0  # $25 minimum peak to evaluate retracement
VELOCITY_SAMPLE_SEC = 5  # sample interval for acceleration check


@dataclass
class CandleOutcome:
    """Resolved candle outcome for adaptive learning."""

    slug: str
    winner: str  # "up" or "down"
    btc_open: float
    btc_close: float
    direction_at_20: str  # Initial BTC direction (for entry price capture)
    reversed: bool  # BTC retraced 80%+ from initial commitment or threshold-confirmed direction disagreed with winner
    winner_ask_at_20: float  # ask price for the winning side at the $20 cross
    peak_up_move: float = 0.0  # max positive btc_move_from_open during candle
    peak_down_move: float = 0.0  # max abs(negative btc_move_from_open) during candle


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

        # Fakeout statistics (computed in _recompute)
        self._fakeout_p75: float = 0.0
        self._fakeout_max: float = 0.0
        self._fakeout_median: float = 0.0
        self._using_fakeout: bool = False  # True when peak data is available
        self._adaptive_cap: float = 50.0  # Rises with P75 in wild markets, bounded [$50, $100]

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
                    peak_up_move=r.get("peak_up_move", 0.0),
                    peak_down_move=r.get("peak_down_move", 0.0),
                )
                self._history.append(outcome)

            # Keep only the last N*2 for file size, but use last N for stats
            if len(self._history) > self._window * 4:
                self._history = self._history[-(self._window * 4) :]

            if self._history:
                logger.info(
                    "Loaded %d adaptive entry records (window=%d)",
                    len(self._history),
                    self._window,
                )
        except Exception:
            logger.warning("Could not load adaptive entry data", exc_info=True)

    async def bootstrap_from_binance(self) -> None:
        """Pre-compute reversal rate from Binance 1-min klines on startup.

        Fetches recent 1-min candles, groups them into 5-min Polymarket-aligned
        buckets, and determines the reversal pattern — giving the adaptive entry
        system a warm start instead of waiting ~50 min for real data.

        Only runs if current history < window. Real Polymarket observations
        naturally push out these bootstrapped entries as the session progresses.
        """
        if len(self._history) >= self._window:
            logger.info(
                "Adaptive entry already has %d records (window=%d), skipping bootstrap",
                len(self._history),
                self._window,
            )
            return

        needed = self._window - len(self._history)
        # Fetch extra 1-min klines to cover needed 5-min buckets + 1 buffer
        fetch_1m = (needed + 2) * 5

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={
                        "symbol": "BTCUSDT",
                        "interval": "1m",
                        "limit": fetch_1m,
                    },
                )
                resp.raise_for_status()
                raw_klines = resp.json()
        except Exception:
            logger.warning("Bootstrap from Binance failed — will use defaults", exc_info=True)
            return

        if not raw_klines:
            return

        # Parse 1-min klines: (open_time_s, open, high, low, close)
        klines_1m = []
        for k in raw_klines:
            klines_1m.append(
                (
                    float(k[0]) / 1000,  # open_time in seconds
                    float(k[1]),  # open
                    float(k[2]),  # high
                    float(k[3]),  # low
                    float(k[4]),  # close
                )
            )

        # Group into 5-min buckets aligned to 300s boundaries
        buckets: dict[int, list] = {}
        for ot, o, h, low, c in klines_1m:
            bucket_key = int(ot) // 300 * 300
            buckets.setdefault(bucket_key, []).append((ot, o, h, low, c))

        # Sort buckets by time, drop the last one (likely in-progress)
        sorted_keys = sorted(buckets.keys())
        if sorted_keys:
            sorted_keys.pop()  # drop in-progress

        # Skip buckets that overlap with existing history slugs
        existing_slugs = {o.slug for o in self._history}

        bootstrapped = 0
        for bk in sorted_keys:
            if bootstrapped >= needed:
                break

            mins = sorted(buckets[bk], key=lambda x: x[0])
            if len(mins) < 3:
                continue  # incomplete bucket

            btc_open = mins[0][1]  # open of first 1-min candle
            btc_close = mins[-1][4]  # close of last 1-min candle
            final_move = btc_close - btc_open

            if abs(final_move) < 1.0:
                # Essentially flat candle — skip (no meaningful direction)
                continue

            winner = "up" if final_move > 0 else "down"

            # Initial direction from first 1-min close
            first_close = mins[0][4]
            initial_direction = "up" if first_close >= btc_open else "down"
            sign = 1.0 if initial_direction == "up" else -1.0

            # Peak and retracement from 1-min closes
            max_dir_move = 0.0
            threshold_crossed = False
            retracement_reversal = False
            retreat_closes: list[float] = []

            for _, _, hi, lo, cl in mins:
                # Check threshold from high/low (more precise)
                dir_hi = (hi - btc_open) * sign
                dir_lo = (lo - btc_open) * sign
                if max(dir_hi, dir_lo) >= self.btc_threshold:
                    threshold_crossed = True
                    break

                dir_close = (cl - btc_open) * sign
                if dir_close > max_dir_move:
                    max_dir_move = dir_close
                    retreat_closes = []
                elif max_dir_move >= MIN_PEAK_COMMIT:
                    retreat_closes.append(dir_close)
                    remaining_ratio = dir_close / max_dir_move if max_dir_move > 0 else 1.0
                    if remaining_ratio < (1.0 - RETRACEMENT_THRESHOLD):
                        if dir_close <= 0 or len(retreat_closes) >= 2:
                            retracement_reversal = True
                            break

            if threshold_crossed or retracement_reversal:
                reversed_flag = initial_direction != winner
            else:
                reversed_flag = False
            if abs(final_move) < 5.0:
                reversed_flag = False

            direction_at_20 = initial_direction

            # Estimate winner_ask_at_20 (no Polymarket data available)
            # Use conservative defaults based on observed patterns
            winner_ask_at_20 = 0.40 if reversed_flag else 0.55

            slug = f"bootstrap-{bk}"
            if slug in existing_slugs:
                continue

            # Approximate peak moves from 1-min high/low
            bucket_high = max(hi for _, _, hi, _, _ in mins)
            bucket_low = min(lo for _, _, _, lo, _ in mins)
            peak_up_move = max(0.0, bucket_high - btc_open)
            peak_down_move = max(0.0, btc_open - bucket_low)

            outcome = CandleOutcome(
                slug=slug,
                winner=winner,
                btc_open=round(btc_open, 2),
                btc_close=round(btc_close, 2),
                direction_at_20=direction_at_20,
                reversed=reversed_flag,
                winner_ask_at_20=winner_ask_at_20,
                peak_up_move=round(peak_up_move, 2),
                peak_down_move=round(peak_down_move, 2),
            )
            self._history.append(outcome)
            bootstrapped += 1

        if bootstrapped > 0:
            self._recompute()
            logger.info(
                "Bootstrapped %d candles from Binance 1-min klines → reversal_rate=%.0f%%, signal=%s, btc_thresh=$%.0f",
                bootstrapped,
                self.rolling_reversal_rate * 100,
                self._signal_type,
                self.btc_threshold,
            )
        else:
            logger.info("Binance bootstrap: no usable candles found")

    def _save_record(self, outcome: CandleOutcome) -> None:
        """Append a candle outcome to JSONL."""
        try:
            with open(self._data_path, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "slug": outcome.slug,
                            "winner": outcome.winner,
                            "btc_open": round(outcome.btc_open, 2),
                            "btc_close": round(outcome.btc_close, 2),
                            "direction_at_20": outcome.direction_at_20,
                            "reversed": outcome.reversed,
                            "winner_ask_at_20": round(outcome.winner_ask_at_20, 4),
                            "peak_up_move": round(outcome.peak_up_move, 2),
                            "peak_down_move": round(outcome.peak_down_move, 2),
                        }
                    )
                    + "\n"
                )
        except Exception:
            logger.warning("Could not save adaptive entry record", exc_info=True)

    def _recompute(self) -> None:
        """Recompute adaptive thresholds from rolling window."""
        window = self._history[-self._window :]

        if len(window) < self._window:
            # Not enough data — use conservative defaults
            self.btc_threshold = DEFAULT_BTC_THRESHOLD
            self.max_entry_price = DEFAULT_MAX_ENTRY
            logger.info(
                "Adaptive entry: insufficient history (%d/%d), using defaults (btc_thresh=$%.0f, max_entry=$%.2f)",
                len(window),
                self._window,
                self.btc_threshold,
                self.max_entry_price,
            )
            return

        # Rolling reversal rate
        reversals = sum(1 for c in window if c.reversed)
        reversal_rate = reversals / len(window)

        # Fakeout-based BTC threshold: compute per-candle fakeout magnitude
        # (peak move in the *wrong* direction before the winner was decided)
        # Use shorter window (last 5 candles) so volatile outliers age out fast,
        # while reversal rate / signal type still use the full window for smoothness.
        fakeout_window = self._history[-5:]
        fakeout_magnitudes = []
        for c in fakeout_window:
            if c.peak_up_move > 0 or c.peak_down_move > 0:
                # Fakeout = peak in wrong direction
                if c.winner == "up":
                    fakeout_magnitudes.append(c.peak_down_move)
                else:
                    fakeout_magnitudes.append(c.peak_up_move)

        if fakeout_magnitudes:
            # Percentile-based threshold from actual fakeout data
            sorted_fakeouts = sorted(fakeout_magnitudes)
            n = len(sorted_fakeouts)
            p75_idx = int(n * 0.75)
            p50_idx = int(n * 0.50)
            self._fakeout_p75 = sorted_fakeouts[min(p75_idx, n - 1)]
            self._fakeout_median = sorted_fakeouts[min(p50_idx, n - 1)]
            self._fakeout_max = sorted_fakeouts[-1]
            self._using_fakeout = True

            # Adaptive cap: rises with P75 in wild markets, bounded [$50, $100]
            self._adaptive_cap = max(50.0, min(100.0, self._fakeout_p75 * 1.2))
            # Threshold = P50, clamped to [$20, adaptive_cap]
            self.btc_threshold = max(20.0, min(self._adaptive_cap, self._fakeout_median))
        else:
            # Fallback: V-shaped formula for old records without peak data
            self._using_fakeout = False
            self._fakeout_p75 = 0.0
            self._fakeout_median = 0.0
            self._fakeout_max = 0.0
            self._adaptive_cap = 50.0
            deviation = abs(reversal_rate - 0.5)
            self.btc_threshold = max(20.0, min(50.0, 50.0 - deviation * 60.0))

        # Signal type for logging/dashboard
        if reversal_rate > 0.60:
            self._signal_type = "CONTRARIAN"
        elif reversal_rate < 0.40:
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

        method = "fakeout" if self._using_fakeout else "v-shaped"
        logger.info(
            "Adaptive entry updated: reversal_rate=%.0f%% (%d/%d) → "
            "signal=%s, btc_thresh=$%.0f (cap=$%.0f, %s, P50=$%.0f), "
            "avg_winner_ask=$%.3f → max_entry=$%.2f",
            reversal_rate * 100,
            reversals,
            len(window),
            self._signal_type,
            self.btc_threshold,
            self._adaptive_cap,
            method,
            self._fakeout_median,
            avg_winner_ask if winner_asks else 0,
            self.max_entry_price,
        )

    def should_trigger(self, abs_btc_move: float, min_ask: float) -> bool:
        """Check if conditions meet adaptive thresholds for triggering AI.

        Args:
            abs_btc_move: Absolute BTC price change from candle open
            min_ask: Minimum ask price across UP and DOWN tokens

        Returns:
            True if BTC has moved enough AND entry price is reasonable,
            OR if entry is very cheap (<=0.35) regardless of BTC move.
        """
        return abs_btc_move >= self.btc_threshold and min_ask <= self.max_entry_price

    def record_outcome(
        self,
        slug: str,
        winner: str,
        btc_open: float,
        btc_close: float,
        prefilter_history: list,
    ) -> None:
        """Record a candle resolution and update adaptive thresholds.

        Uses retracement-based reversal detection: identifies initial BTC
        direction, then checks for threshold crossing (momentum confirmed)
        or 80%+ retracement with acceleration (reversal detected).

        Args:
            slug: Candle slug
            winner: "up" or "down"
            btc_open: BTC price at candle open
            btc_close: BTC price at candle close
            prefilter_history: List of PreFilterSnapshot from the candle
        """
        # 1. Compute peak up/down moves from prefilter history
        peak_up_move = 0.0
        peak_down_move = 0.0
        for snap in prefilter_history:
            move = snap.btc_move_from_open
            if move > peak_up_move:
                peak_up_move = move
            if move < 0 and abs(move) > peak_down_move:
                peak_down_move = abs(move)

        # 2. Identify initial BTC direction (first snapshot with |move| > $5)
        initial_direction = ""
        for snap in prefilter_history:
            if abs(snap.btc_move_from_open) > 5.0:
                initial_direction = "up" if snap.btc_move_from_open > 0 else "down"
                break
        if not initial_direction:
            initial_direction = "up" if (btc_close - btc_open) >= 0 else "down"

        # Capture winner ask at threshold crossing for entry price calibration
        winner_ask_at_20 = 0.0
        for snap in prefilter_history:
            if abs(snap.btc_move_from_open) >= self.btc_threshold:
                if winner == "up":
                    winner_ask_at_20 = snap.best_entry_up
                else:
                    winner_ask_at_20 = snap.best_entry_down
                break
        if not winner_ask_at_20 and prefilter_history:
            last_snap = prefilter_history[-1]
            if winner == "up":
                winner_ask_at_20 = last_snap.best_entry_up
            else:
                winner_ask_at_20 = last_snap.best_entry_down

        # 3. Scan for threshold crossing or 80% retracement + acceleration
        sign = 1.0 if initial_direction == "up" else -1.0
        max_dir_move = 0.0
        threshold_crossed = False
        retracement_reversal = False
        # Collect directional positions for velocity calculation
        retreat_positions: list[float] = []
        peak_index = 0

        for i, snap in enumerate(prefilter_history):
            dir_move = snap.btc_move_from_open * sign

            # Track peak
            if dir_move > max_dir_move:
                max_dir_move = dir_move
                peak_index = i
                retreat_positions = []  # reset on new peak

            # Threshold crossing → momentum confirmed, stop checking retracement
            if dir_move >= self.btc_threshold:
                threshold_crossed = True
                break

            # After peak: collect retreat positions (sampled every ~5 snapshots)
            if i > peak_index and (i - peak_index) % VELOCITY_SAMPLE_SEC == 0:
                retreat_positions.append(dir_move)

            # 80% retracement check (needs meaningful peak)
            if max_dir_move >= MIN_PEAK_COMMIT and dir_move < max_dir_move:
                remaining_ratio = dir_move / max_dir_move  # <0 means crossed zero
                if remaining_ratio < (1.0 - RETRACEMENT_THRESHOLD):  # < 0.20
                    if dir_move <= 0:
                        # Crossed zero — definitive reversal
                        retracement_reversal = True
                        break
                    # Check acceleration: velocity trend over sampled positions
                    if len(retreat_positions) >= 3:
                        half = len(retreat_positions) // 2
                        avg_first = sum(retreat_positions[:half]) / half
                        avg_second = sum(retreat_positions[half:]) / (len(retreat_positions) - half)
                        if avg_second < avg_first:  # lower position = faster retreat
                            retracement_reversal = True
                            break

        # 4. Determine reversed
        if threshold_crossed or retracement_reversal:
            reversed_flag = initial_direction != winner
        else:
            reversed_flag = False  # inconclusive — not enough commitment

        # Near-zero guard
        if abs(btc_close - btc_open) < 5.0:
            reversed_flag = False

        # Keep direction_at_20 field for JSONL compat (now = initial_direction)
        direction_at_20 = initial_direction

        outcome = CandleOutcome(
            slug=slug,
            winner=winner,
            btc_open=btc_open,
            btc_close=btc_close,
            direction_at_20=direction_at_20,
            reversed=reversed_flag,
            winner_ask_at_20=winner_ask_at_20,
            peak_up_move=peak_up_move,
            peak_down_move=peak_down_move,
        )

        # Dedup — skip if this slug was already recorded
        if any(h.slug == slug for h in self._history[-self._window * 2 :]):
            logger.debug("Adaptive entry: skipping duplicate slug %s", slug)
            return

        self._history.append(outcome)
        self._save_record(outcome)
        self._recompute()

        logger.info(
            "Adaptive entry recorded: %s winner=%s, dir@$20=%s, reversed=%s, "
            "winner_ask@$20=$%.3f, peak_up=$%.0f, peak_down=$%.0f",
            slug,
            winner,
            direction_at_20,
            reversed_flag,
            winner_ask_at_20,
            peak_up_move,
            peak_down_move,
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
        """Signal type: MOMENTUM (<40%), UNCERTAIN (40-60%), CONTRARIAN (>60%)."""
        return self._signal_type

    @property
    def rolling_reversal_rate(self) -> float:
        """Current rolling reversal rate."""
        window = self._history[-self._window :]
        if not window:
            return 0.0
        return sum(1 for c in window if c.reversed) / len(window)

    @property
    def has_enough_history(self) -> bool:
        """Whether we have enough candles for adaptive thresholds."""
        return len(self._history) >= self._window

    @property
    def fakeout_stats(self) -> dict:
        """Fakeout statistics for dashboard display."""
        return {
            "using_fakeout": self._using_fakeout,
            "fakeout_p75": round(self._fakeout_p75, 1),
            "fakeout_max": round(self._fakeout_max, 1),
            "fakeout_median": round(self._fakeout_median, 1),
            "adaptive_cap": round(self._adaptive_cap, 1),
        }

    def get_summary(self) -> str:
        """Generate a human-readable summary for logging/dashboard."""
        window = self._history[-self._window :]
        if not window:
            return "Adaptive entry: no history yet"
        reversal_rate = self.rolling_reversal_rate
        method = (
            f"fakeout P50=${self._fakeout_median:.0f}, cap=${self._adaptive_cap:.0f}"
            if self._using_fakeout
            else "v-shaped fallback"
        )
        return (
            f"Adaptive entry (last {len(window)} candles): "
            f"reversal_rate={reversal_rate:.0%}, "
            f"signal={self._signal_type}, "
            f"btc_thresh=${self.btc_threshold:.0f} ({method}), "
            f"max_entry=${self.max_entry_price:.2f}"
        )

    def get_ai_context(self, abs_btc_move: float = 0.0) -> str | None:
        """Build reversal rate context for the AI prompt.

        Args:
            abs_btc_move: Absolute BTC price change from candle open.
                Used to gate UNCERTAIN cheapest-side suggestion — only
                suggest contrarian when BTC hasn't cleared the fakeout
                noise floor.

        Returns None if insufficient history. Otherwise returns a section
        with the actual reversal rate and signal interpretation.
        """
        if not self.has_enough_history:
            return None

        rate = self.rolling_reversal_rate
        window = self._history[-self._window :]
        reversals = sum(1 for c in window if c.reversed)

        lines = [
            "## Reversal Rate Context (Adaptive Entry)",
            f"- Rolling reversal rate: **{rate:.0%}** "
            f"({reversals} of last {len(window)} candles showed 80%+ retracement from initial commitment)",
            f"- Signal type: **{self._signal_type}**",
            f"- BTC move threshold: ${self.btc_threshold:.0f}",
        ]

        if self._using_fakeout:
            lines.append(
                f"- Fakeout noise: P75=${self._fakeout_p75:.0f}, "
                f"max=${self._fakeout_max:.0f}, median=${self._fakeout_median:.0f} "
                f"(adaptive cap=${self._adaptive_cap:.0f}, threshold=${self.btc_threshold:.0f})"
            )

        # Wild market advisory: fires when recent fakeouts far exceed threshold
        if self._using_fakeout and self._fakeout_max > self.btc_threshold * 1.5:
            pct_above = ((self._fakeout_max / self.btc_threshold) - 1) * 100
            lines.extend(
                [
                    "",
                    f"\U0001f30a **HIGH-VOLATILITY MARKET**: Recent fakeouts reached "
                    f"${self._fakeout_max:.0f} — {pct_above:.0f}% above the "
                    f"${self.btc_threshold:.0f} threshold. "
                    f"Even moves that clear the threshold may reverse. Wait for sustained "
                    f"confirmation (15-20s above threshold) rather than entering immediately. "
                    f"The 150-200s window has historically outperformed early entries in wild markets.",
                ]
            )

        if rate > 0.60:
            lines.extend(
                [
                    "",
                    f"⚠ **High reversal rate ({rate:.0%})**: The initial commitment "
                    f"has been WRONG {rate:.0%} of the time recently. The cheap (contrarian) side — "
                    f"opposite to the current BTC move — may be the better entry. "
                    f"When reversals dominated, the winning side's average ask was "
                    f"${self._avg_reversal_winner_ask():.2f} at the $20 cross.",
                ]
            )
        elif rate >= 0.40:
            if abs_btc_move >= self.btc_threshold:
                # BTC has cleared the fakeout noise floor — momentum is real
                lines.extend(
                    [
                        "",
                        f"⚠ **Uncertain reversal history ({rate:.0%} at initial cross)** but BTC has moved "
                        f"**${abs_btc_move:.0f}** — past the fakeout threshold (${self.btc_threshold:.0f}). "
                        f"The reversal rate was measured at the initial cross; moves beyond "
                        f"${self.btc_threshold:.0f} have cleared typical fakeout noise. "
                        f"Momentum entries are favored over contrarian.",
                        "",
                        "⏳ **Entry timing**: BTC has cleared fakeout noise, but uncertain regimes still show elevated "
                        "reversal risk on very early entries (>200s). Size down or wait for brief confirmation if "
                        "confidence is marginal.",
                    ]
                )
            else:
                # Below fakeout threshold — could still be noise, cheapest-side guidance applies
                lines.extend(
                    [
                        "",
                        f"⚠ **Uncertain market ({rate:.0%} reversal)**: Direction has been unreliable. "
                        f"When both sides are priced near even (both asks $0.35–$0.65), "
                        f"**lean toward the cheaper side** — at ~50% accuracy, only cheap entries are profitable. "
                        f"An entry at $0.35 profits +$0.15/trade at 50%; $0.60 loses -$0.10/trade at 50%. "
                        f"However, if one side is clearly confirmed by price (e.g., $0.90 vs $0.10), "
                        f"trust the market signal — the cheap side is cheap for a reason. "
                        f"This applies mainly to early-candle balanced prices, not late confirmations.",
                        "",
                        "⏳ **Entry timing**: Early entries (>200s remaining) in uncertain regimes have historically "
                        "underperformed. The 150-200s window offers better directional clarity. If the current move "
                        "is marginal, consider waiting for stronger confirmation.",
                    ]
                )
        elif rate < 0.25:
            lines.extend(
                [
                    "",
                    f"✓ **Low reversal rate ({rate:.0%})**: BTC rarely retraces from initial commitment. "
                    f"The initial move is continuing {1 - rate:.0%} of the time. "
                    f"Momentum entries aligned with the current BTC direction are favored.",
                ]
            )

        return "\n".join(lines)

    def _avg_reversal_winner_ask(self) -> float:
        """Average winner ask price on reversed candles in the window."""
        window = self._history[-self._window :]
        asks = [c.winner_ask_at_20 for c in window if c.reversed and c.winner_ask_at_20 > 0]
        return sum(asks) / len(asks) if asks else 0.0
