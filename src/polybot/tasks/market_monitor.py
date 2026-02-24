"""Market monitor task — fetches data every 1s, runs prefilter, triggers AI.

Runs as an asyncio.Task. Records PreFilterSnapshots and sets the AI trigger
event when conditions are favorable.
"""

from __future__ import annotations

import asyncio
import logging
import time

from polybot.config import AppConfig
from polybot.market_data.provider import MarketDataProvider
from polybot.prefilter import PreFilter
from polybot.resolution import ResolutionTracker
from polybot.shared_state import PreFilterSnapshot, SharedState
from polybot.simulator.portfolio import Portfolio

logger = logging.getLogger(__name__)


class MarketMonitor:
    """Fetches market data every second, runs prefilter, triggers AI."""

    def __init__(
        self,
        config: AppConfig,
        shared: SharedState,
        market_data: MarketDataProvider,
        prefilter: PreFilter,
        portfolio: Portfolio,
        resolution_tracker: ResolutionTracker,
    ) -> None:
        self._config = config
        self._shared = shared
        self._market_data = market_data
        self._prefilter = prefilter
        self._portfolio = portfolio
        self._resolution_tracker = resolution_tracker
        self._interval = config.monitor.market_monitor_interval
        self._rr_threshold = config.monitor.rr_trigger_threshold
        self._cooldown = config.monitor.ai_cooldown_seconds

    async def run(self) -> None:
        """Main loop — runs until shutdown."""
        logger.info("MarketMonitor started (interval=%.1fs)", self._interval)
        while not self._shared.shutdown:
            if self._shared.rotation_in_progress:
                await asyncio.sleep(0.2)
                continue

            try:
                await self._tick()
            except Exception:
                logger.exception("MarketMonitor tick error")

            await asyncio.sleep(self._interval)

        logger.info("MarketMonitor stopped")

    async def _tick(self) -> None:
        """Single monitoring cycle."""
        market = self._shared.current_market
        if market is None:
            return

        time_remaining = market.time_remaining()
        if time_remaining <= 0:
            return

        # Fetch market snapshot
        try:
            snapshot = await self._market_data.get_snapshot()
        except Exception:
            logger.debug("MarketMonitor: data fetch failed", exc_info=True)
            return

        self._shared.latest_snapshot = snapshot
        self._shared.snapshot_timestamp = time.time()

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_mid = up_ob.midpoint
        down_mid = down_ob.midpoint

        # Compute R/R for both tokens
        up_ask = up_ob.best_ask or 1.0
        down_ask = down_ob.best_ask or 1.0
        rr_up = (1.0 - up_ask) / up_ask if up_ask > 0 else 0
        rr_down = (1.0 - down_ask) / down_ask if down_ask > 0 else 0

        # Compute BTC move from candle open
        btc_move = 0.0
        btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
        candle_open = self._shared.candle_open_btc
        if candle_open is not None and btc_price_val > 0:
            btc_move = btc_price_val - candle_open

        # Run prefilter checks (1-5, no R/R gate)
        has_position = (
            self._portfolio.up_position.shares > 0
            or self._portfolio.down_position.shares > 0
        )
        pf_result = self._prefilter.check(time_remaining, snapshot, has_position)

        # Build snapshot record
        pf_snapshot = PreFilterSnapshot(
            timestamp=time.time(),
            time_remaining=time_remaining,
            checks={
                "time_ok": time_remaining >= 45,
                "spread_ok": not pf_result.should_skip or "spread" not in pf_result.reason.lower(),
                "depth_ok": not pf_result.should_skip or "thin" not in pf_result.reason.lower(),
                "choppy_ok": not pf_result.should_skip or "choppy" not in pf_result.reason.lower(),
                "setup_ok": not pf_result.should_skip or "setup" not in pf_result.reason.lower(),
                "prefilter_passed": not pf_result.should_skip,
            },
            reasons=[pf_result.reason] if pf_result.reason else [],
            best_entry_up=up_ask,
            best_entry_down=down_ask,
            rr_up=rr_up,
            rr_down=rr_down,
            btc_price=btc_price_val,
            up_mid=up_mid,
            down_mid=down_mid,
            up_spread_pct=up_ob.spread_pct,
            down_spread_pct=down_ob.spread_pct,
            streak=pf_result.consecutive_streak,
            streak_direction=pf_result.streak_direction,
            btc_move_from_open=btc_move,
        )
        self._shared.prefilter_history.append(pf_snapshot)

        # Decide whether to trigger AI
        best_rr = max(rr_up, rr_down)
        prefilter_passed = not pf_result.should_skip

        # Always trigger for exit decisions when we have a position
        force_trigger = has_position and prefilter_passed

        should_trigger = force_trigger or (
            prefilter_passed
            and best_rr >= self._rr_threshold
        )

        if should_trigger and not self._shared.ai_trigger_event.is_set():
            # Check cooldown
            now = time.time()
            elapsed = now - self._shared.ai_last_call_time
            if elapsed >= self._cooldown or force_trigger:
                best_side = "up" if rr_up >= rr_down else "down"
                self._shared.ai_trigger_reason = (
                    f"R/R={best_rr:.2f} ({best_side}), "
                    f"prefilter={'PASS' if prefilter_passed else 'SKIP'}, "
                    f"btc_move=${btc_move:+.0f}"
                )
                if force_trigger:
                    self._shared.ai_trigger_reason = (
                        f"position_check: {self._shared.ai_trigger_reason}"
                    )
                self._shared.ai_trigger_event.set()
                logger.info(
                    "AI triggered: %s (cooldown=%.0fs elapsed)",
                    self._shared.ai_trigger_reason, elapsed,
                )
