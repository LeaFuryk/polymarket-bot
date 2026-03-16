"""Adaptive entry tracker — learns optimal BTC move threshold and max entry price.

Orchestrates reversal detection, threshold computation, and persistence.
See ``README.md`` for architecture overview.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from polybot.adaptive_entry.ai_context import build_ai_context
from polybot.adaptive_entry.constants import (
    BOOTSTRAP_CONSERVATIVE_MOMENTUM_ASK,
    BOOTSTRAP_CONSERVATIVE_REVERSED_ASK,
    BOOTSTRAP_FLAT_THRESHOLD,
    DATA_FILE_NAME,
    DEFAULT_BTC_THRESHOLD,
    DEFAULT_MAX_ENTRY,
    HISTORY_MAX_FACTOR,
    MIN_PEAK_COMMIT,
    REGIME_CALM_UPPER,
    REGIME_MODERATE_UPPER,
    RETRACEMENT_THRESHOLD,
)
from polybot.adaptive_entry.models import CandleOutcome
from polybot.adaptive_entry.reversal_detector import detect_reversal
from polybot.adaptive_entry.threshold_calculator import ThresholdResult, compute_thresholds


class AdaptiveEntryTracker:
    """Learns optimal entry thresholds from rolling candle history.

    Args:
        data_dir: Directory for JSONL persistence.
        window: Number of candles for rolling statistics.
        logger: Optional logger; defaults to module-level logger.
    """

    def __init__(
        self,
        data_dir: str | Path,
        window: int = 10,
        logger: logging.Logger | None = None,
    ) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._data_path = self._data_dir / DATA_FILE_NAME
        self._window = window

        self._history: list[CandleOutcome] = []

        # Computed adaptive thresholds
        self.btc_threshold: float = DEFAULT_BTC_THRESHOLD
        self.max_entry_price: float = DEFAULT_MAX_ENTRY
        self._thresholds: ThresholdResult | None = None

        self._load()
        self._recompute()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_trigger(self, abs_btc_move: float, min_ask: float) -> tuple[bool, str]:
        """Check if conditions meet adaptive thresholds for triggering AI.

        Returns (passed, reason) — reason is empty on pass, describes
        which threshold(s) failed otherwise.
        """
        btc_ok = abs_btc_move >= self.btc_threshold
        ask_ok = min_ask <= self.max_entry_price
        if btc_ok and ask_ok:
            return True, ""
        parts = []
        if not btc_ok:
            parts.append(f"BTC move ${abs_btc_move:.0f} < ${self.btc_threshold:.0f} threshold")
        if not ask_ok:
            parts.append(f"min ask ${min_ask:.2f} > ${self.max_entry_price:.2f} max entry")
        return False, "; ".join(parts)

    def record_outcome(
        self,
        slug: str,
        winner: str,
        btc_open: float,
        btc_close: float,
        btc_moves: list[float] | None = None,
        best_entry_up: float = 1.0,
        best_entry_down: float = 1.0,
    ) -> None:
        """Record a candle resolution and update adaptive thresholds."""
        result = detect_reversal(
            winner=winner,
            btc_open=btc_open,
            btc_close=btc_close,
            btc_moves=btc_moves or [],
            best_entry_up=best_entry_up,
            best_entry_down=best_entry_down,
            btc_threshold=self.btc_threshold,
        )

        outcome = CandleOutcome(
            slug=slug,
            winner=winner,
            btc_open=btc_open,
            btc_close=btc_close,
            direction_at_20=result.initial_direction,
            reversed=result.reversed,
            winner_ask_at_20=result.winner_ask_at_20,
            peak_up_move=result.peak_up_move,
            peak_down_move=result.peak_down_move,
        )

        # Dedup
        if any(h.slug == slug for h in self._history[-self._window * 2 :]):
            self._log.debug("Adaptive entry: skipping duplicate slug %s", slug)
            return

        self._history.append(outcome)
        self._save_record(outcome)
        self._recompute()

        self._log.info(
            "Adaptive entry recorded: %s winner=%s, dir@$20=%s, reversed=%s, "
            "winner_ask@$20=$%.3f, peak_up=$%.0f, peak_down=$%.0f",
            slug,
            winner,
            result.initial_direction,
            result.reversed,
            result.winner_ask_at_20,
            result.peak_up_move,
            result.peak_down_move,
        )

    async def bootstrap_from_binance(self) -> None:
        """Pre-compute reversal rate from Binance 1-min klines on startup."""
        if len(self._history) >= self._window:
            self._log.info(
                "Adaptive entry already has %d records (window=%d), skipping bootstrap",
                len(self._history),
                self._window,
            )
            return

        needed = self._window - len(self._history)
        fetch_1m = (needed + 2) * 5

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": "BTCUSDT", "interval": "1m", "limit": fetch_1m},
                )
                resp.raise_for_status()
                raw_klines = resp.json()
        except Exception:
            self._log.warning("Bootstrap from Binance failed — will use defaults", exc_info=True)
            return

        if not raw_klines:
            return

        klines_1m = [(float(k[0]) / 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in raw_klines]

        buckets: dict[int, list] = {}
        for ot, o, h, low, c in klines_1m:
            bucket_key = int(ot) // 300 * 300
            buckets.setdefault(bucket_key, []).append((ot, o, h, low, c))

        sorted_keys = sorted(buckets.keys())
        if sorted_keys:
            sorted_keys.pop()

        existing_slugs = {o.slug for o in self._history}
        bootstrapped = 0

        for bk in sorted_keys:
            if bootstrapped >= needed:
                break

            mins = sorted(buckets[bk], key=lambda x: x[0])
            if len(mins) < 3:
                continue

            btc_open = mins[0][1]
            btc_close = mins[-1][4]
            final_move = btc_close - btc_open

            if abs(final_move) < BOOTSTRAP_FLAT_THRESHOLD:
                continue

            winner = "up" if final_move > 0 else "down"
            first_close = mins[0][4]
            initial_direction = "up" if first_close >= btc_open else "down"
            sign = 1.0 if initial_direction == "up" else -1.0

            max_dir_move = 0.0
            threshold_crossed = False
            retracement_reversal = False
            retreat_closes: list[float] = []

            for _, _, hi, lo, cl in mins:
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

            winner_ask_at_20 = (
                BOOTSTRAP_CONSERVATIVE_REVERSED_ASK if reversed_flag else BOOTSTRAP_CONSERVATIVE_MOMENTUM_ASK
            )

            slug = f"bootstrap-{bk}"
            if slug in existing_slugs:
                continue

            bucket_high = max(hi for _, _, hi, _, _ in mins)
            bucket_low = min(lo for _, _, _, lo, _ in mins)

            outcome = CandleOutcome(
                slug=slug,
                winner=winner,
                btc_open=round(btc_open, 2),
                btc_close=round(btc_close, 2),
                direction_at_20=initial_direction,
                reversed=reversed_flag,
                winner_ask_at_20=winner_ask_at_20,
                peak_up_move=round(max(0.0, bucket_high - btc_open), 2),
                peak_down_move=round(max(0.0, btc_open - bucket_low), 2),
            )
            self._history.append(outcome)
            bootstrapped += 1

        if bootstrapped > 0:
            self._recompute()
            self._log.info(
                "Bootstrapped %d candles from Binance 1-min klines → reversal_rate=%.0f%%, signal=%s, btc_thresh=$%.0f",
                bootstrapped,
                self.rolling_reversal_rate * 100,
                self.signal_type,
                self.btc_threshold,
            )
        else:
            self._log.info("Binance bootstrap: no usable candles found")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def regime(self) -> str:
        """Market regime label derived from continuous reversal rate."""
        rate = self.rolling_reversal_rate
        if rate < REGIME_CALM_UPPER:
            return "CALM"
        elif rate < REGIME_MODERATE_UPPER:
            return "MODERATE"
        else:
            return "CHOPPY"

    @property
    def signal_type(self) -> str:
        """Signal type: MOMENTUM (<40%), UNCERTAIN (40-60%), CONTRARIAN (>60%)."""
        return self._thresholds.signal_type if self._thresholds else "UNCERTAIN"

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
    def window_size(self) -> int:
        """Configured rolling window size."""
        return self._window

    @property
    def history_count(self) -> int:
        """Number of candle outcomes in memory."""
        return len(self._history)

    @property
    def fakeout_stats(self) -> dict:
        """Fakeout statistics for dashboard display."""
        if self._thresholds:
            return {
                "using_fakeout": self._thresholds.using_fakeout,
                "fakeout_p75": round(self._thresholds.fakeout_p75, 1),
                "fakeout_max": round(self._thresholds.fakeout_max, 1),
                "fakeout_median": round(self._thresholds.fakeout_median, 1),
                "adaptive_cap": round(self._thresholds.adaptive_cap, 1),
            }
        return {
            "using_fakeout": False,
            "fakeout_p75": 0.0,
            "fakeout_max": 0.0,
            "fakeout_median": 0.0,
            "adaptive_cap": 50.0,
        }

    # ------------------------------------------------------------------
    # Summary & AI context
    # ------------------------------------------------------------------

    def get_summary(self) -> str:
        """Generate a human-readable summary for logging/dashboard."""
        window = self._history[-self._window :]
        if not window:
            return "Adaptive entry: no history yet"
        t = self._thresholds
        if t and t.using_fakeout:
            method = f"fakeout P50=${t.fakeout_median:.0f}, cap=${t.adaptive_cap:.0f}"
        else:
            method = "v-shaped fallback"
        return (
            f"Adaptive entry (last {len(window)} candles): "
            f"reversal_rate={self.rolling_reversal_rate:.0%}, "
            f"signal={self.signal_type}, "
            f"btc_thresh=${self.btc_threshold:.0f} ({method}), "
            f"max_entry=${self.max_entry_price:.2f}"
        )

    def get_ai_context(self, abs_btc_move: float = 0.0) -> str | None:
        """Build reversal rate context for the AI prompt."""
        t = self._thresholds
        if not t:
            return None
        return build_ai_context(
            history=self._history,
            window=self._window,
            signal_type=t.signal_type,
            btc_threshold=t.btc_threshold,
            using_fakeout=t.using_fakeout,
            fakeout_p75=t.fakeout_p75,
            fakeout_max=t.fakeout_max,
            fakeout_median=t.fakeout_median,
            adaptive_cap=t.adaptive_cap,
            abs_btc_move=abs_btc_move,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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

            if len(self._history) > self._window * HISTORY_MAX_FACTOR:
                self._history = self._history[-(self._window * HISTORY_MAX_FACTOR) :]

            if self._history:
                self._log.info(
                    "Loaded %d adaptive entry records (window=%d)",
                    len(self._history),
                    self._window,
                )
        except Exception:
            self._log.warning("Could not load adaptive entry data", exc_info=True)

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
            self._log.warning("Could not save adaptive entry record", exc_info=True)

    def _recompute(self) -> None:
        """Recompute adaptive thresholds from rolling window."""
        result = compute_thresholds(self._history, self._window)
        self._thresholds = result
        self.btc_threshold = result.btc_threshold
        self.max_entry_price = result.max_entry_price

        if len(self._history) >= self._window:
            method = "fakeout" if result.using_fakeout else "v-shaped"
            window = self._history[-self._window :]
            reversals = sum(1 for c in window if c.reversed)
            reversal_rate = reversals / len(window)
            winner_asks = [c.winner_ask_at_20 for c in window if c.winner_ask_at_20 > 0]
            avg_ask = sum(winner_asks) / len(winner_asks) if winner_asks else 0

            self._log.info(
                "Adaptive entry updated: reversal_rate=%.0f%% (%d/%d) → "
                "signal=%s, btc_thresh=$%.0f (cap=$%.0f, %s, P50=$%.0f), "
                "avg_winner_ask=$%.3f → max_entry=$%.2f",
                reversal_rate * 100,
                reversals,
                len(window),
                result.signal_type,
                result.btc_threshold,
                result.adaptive_cap,
                method,
                result.fakeout_median,
                avg_ask,
                result.max_entry_price,
            )
        else:
            self._log.info(
                "Adaptive entry: insufficient history (%d/%d), using defaults (btc_thresh=$%.0f, max_entry=$%.2f)",
                len(self._history),
                self._window,
                self.btc_threshold,
                self.max_entry_price,
            )
