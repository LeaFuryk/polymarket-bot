"""Rules-based pre-filter — skip AI calls on obvious HOLD cycles.

Runs cheap, fast checks before calling Claude to determine if there's any
plausible trade setup. Saves 60-70% of AI API costs by filtering out cycles
where HOLD is the only sensible decision.

Each check returns a (should_skip, reason) tuple. If any check says skip,
the cycle is logged as a HOLD without calling the AI.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from polybot.models import BtcCandle, MarketSnapshot

logger = logging.getLogger(__name__)


@dataclass
class PreFilterResult:
    """Result of the rules-based pre-filter."""

    should_skip: bool
    reason: str
    # Computed signals passed to AI if not skipped (avoids recomputation)
    consecutive_streak: int = 0
    streak_direction: str = ""
    btc_range_30m: float = 0.0
    best_entry_price: float = 1.0


class PreFilter:
    """Cheap rules-based screen to skip obvious HOLD cycles before calling AI.

    Configurable thresholds with sensible defaults derived from trading analysis.
    """

    def __init__(
        self,
        min_time_remaining: float = 45.0,
        choppy_range_threshold: float = 50.0,
        choppy_max_entry: float = 0.28,
        no_streak_max_entry: float = 0.40,
        min_streak_for_trade: int = 0,
        max_spread_pct: float = 0.08,
        min_book_depth: float = 50.0,
    ) -> None:
        self.min_time_remaining = min_time_remaining
        self.choppy_range_threshold = choppy_range_threshold
        self.choppy_max_entry = choppy_max_entry
        self.no_streak_max_entry = no_streak_max_entry
        self.min_streak_for_trade = min_streak_for_trade
        self.max_spread_pct = max_spread_pct
        self.min_book_depth = min_book_depth

        # Stats tracking
        self.total_checks = 0
        self.total_skipped = 0

    @property
    def skip_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.total_skipped / self.total_checks

    def check(
        self,
        time_remaining: float,
        snapshot: MarketSnapshot,
        has_open_position: bool = False,
    ) -> PreFilterResult:
        """Run all pre-filter checks. Returns result with should_skip flag.

        If the bot has an open position, the filter skips AI — exits are
        handled by PositionMonitor at configured thresholds (-60%/+80%).
        """
        self.total_checks += 1

        # Compute shared signals
        candles = snapshot.btc_candles
        streak, streak_dir = self._compute_streak(candles)
        btc_range = self._compute_btc_range_30m(candles)
        best_entry = self._compute_best_entry(snapshot)

        result = PreFilterResult(
            should_skip=False,
            reason="",
            consecutive_streak=streak,
            streak_direction=streak_dir,
            btc_range_30m=btc_range,
            best_entry_price=best_entry,
        )

        # If we have open positions, skip AI — PositionMonitor handles exits
        # at -60%/+80% thresholds via exit_trigger_queue
        if has_open_position:
            result.should_skip = True
            result.reason = "Position open — exits handled by PositionMonitor"
            self.total_skipped += 1
            logger.debug("Pre-filter SKIP: %s", result.reason)
            return result

        # Check 1: Time remaining too low for new entries
        if time_remaining < self.min_time_remaining:
            result.should_skip = True
            result.reason = f"Time remaining {time_remaining:.0f}s < {self.min_time_remaining:.0f}s minimum"
            self.total_skipped += 1
            logger.info("Pre-filter SKIP: %s", result.reason)
            return result

        # Check 2: Both orderbooks have wide spreads
        up_spread = snapshot.orderbook.spread_pct
        down_spread = snapshot.down_orderbook.spread_pct
        if (up_spread is not None and up_spread > self.max_spread_pct and
                down_spread is not None and down_spread > self.max_spread_pct):
            result.should_skip = True
            result.reason = f"Both spreads wide: UP={up_spread:.2%}, DOWN={down_spread:.2%}"
            self.total_skipped += 1
            logger.info("Pre-filter SKIP: %s", result.reason)
            return result

        # Check 3: Both orderbooks lack depth
        up_depth = snapshot.orderbook.bid_depth + snapshot.orderbook.ask_depth
        down_depth = snapshot.down_orderbook.bid_depth + snapshot.down_orderbook.ask_depth
        if up_depth < self.min_book_depth and down_depth < self.min_book_depth:
            result.should_skip = True
            result.reason = f"Both books thin: UP={up_depth:.0f}, DOWN={down_depth:.0f}"
            self.total_skipped += 1
            logger.info("Pre-filter SKIP: %s", result.reason)
            return result

        # Check 4: Choppy market with no good entry price
        if btc_range < self.choppy_range_threshold and best_entry > self.choppy_max_entry:
            result.should_skip = True
            result.reason = (
                f"Choppy market (range=${btc_range:.0f} < ${self.choppy_range_threshold:.0f}) "
                f"and no cheap entry (best={best_entry:.3f} > {self.choppy_max_entry:.3f})"
            )
            self.total_skipped += 1
            logger.info("Pre-filter SKIP: %s", result.reason)
            return result

        # Check 5: No streak and no good entry — no clear setup
        if streak < 2 and best_entry > self.no_streak_max_entry:
            result.should_skip = True
            result.reason = (
                f"No clear setup: streak={streak}, best entry={best_entry:.3f} > "
                f"{self.no_streak_max_entry:.3f}"
            )
            self.total_skipped += 1
            logger.info("Pre-filter SKIP: %s", result.reason)
            return result

        # All checks passed — call AI
        return result

    @staticmethod
    def _compute_streak(candles: list[BtcCandle]) -> tuple[int, str]:
        """Count consecutive same-direction candles from the most recent."""
        if not candles:
            return 0, ""
        streak = 1
        direction = candles[-1].direction
        for c in reversed(candles[:-1]):
            if c.direction == direction:
                streak += 1
            else:
                break
        return streak, direction

    @staticmethod
    def _compute_btc_range_30m(candles: list[BtcCandle]) -> float:
        """Compute BTC price range over the last ~30 minutes (6 candles)."""
        if len(candles) < 2:
            return 0.0
        recent = candles[-6:] if len(candles) >= 6 else candles
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        return max(highs) - min(lows)

    @staticmethod
    def _compute_best_entry(snapshot: MarketSnapshot) -> float:
        """Find the cheapest entry price across both tokens.

        Lower price = better risk/reward for binary options.
        """
        prices = []
        up_ask = snapshot.orderbook.best_ask
        down_ask = snapshot.down_orderbook.best_ask
        if up_ask is not None:
            prices.append(up_ask)
        if down_ask is not None:
            prices.append(down_ask)
        return min(prices) if prices else 1.0
