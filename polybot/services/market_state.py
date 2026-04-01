"""Service: assembles market state for the fine-tuned model."""

from __future__ import annotations

import logging
import math
import time

from polybot.domain.models import (
    BetState,
    CurrentCandleData,
    Microstructure,
    PromptState,
    Technicals,
)
from polybot.ports.market_feed import MarketFeed
from polybot.services.candle_aggregator import CandleAggregator

logger = logging.getLogger(__name__)

CANDLE_INTERVAL = 300  # 5 minutes


class MarketStateService:
    """Orchestrates CandleAggregator + MarketFeed into a PromptState snapshot.

    Depends on CandleAggregator (owns ticks + candles) and MarketFeed (Polymarket).
    """

    def __init__(
        self,
        candle_aggregator: CandleAggregator,
        market_feed: MarketFeed,
        series_slug: str = "btc-updown-5m",
    ) -> None:
        self._aggregator = candle_aggregator
        self._market_feed = market_feed
        self._series_slug = series_slug

    async def get_state(self) -> PromptState | None:
        """Build the full market state snapshot.

        Returns None if essential data (tick or market) is unavailable.
        """
        tick = self._aggregator.latest_tick
        if tick is None:
            logger.warning("No Chainlink tick available yet")
            return None

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            logger.warning("No Polymarket market found")
            return None

        snapshot = await self._market_feed.get_snapshot(market)

        # -- Candles -----------------------------------------------------------
        candles = self._aggregator.candle_data()
        partial = self._aggregator.partial

        # -- Current candle ----------------------------------------------------
        now = time.time()
        candle_start = now - (now % CANDLE_INTERVAL)
        elapsed = now - candle_start
        elapsed_pct = elapsed / CANDLE_INTERVAL
        time_remaining = market.time_remaining
        heartbeat_age = now - tick.timestamp

        # Partial candle OHLC
        candle_open = partial.open if partial else None
        high_so_far = partial.high if partial else None
        low_so_far = partial.low if partial else None

        # partial_ret = ln(last_price / open)
        partial_ret = None
        if candle_open is not None and candle_open > 0:
            partial_ret = math.log(tick.price / candle_open)

        # volume_so_far from partial (Binance volume not available mid-candle,
        # so we use 0.0 — will be refined when we add real-time volume tracking)
        volume_so_far = 0.0

        # volume_pace = volume_so_far / (elapsed_pct × avg_volume)
        volume_pace = None
        closed = self._aggregator.closed_candles()
        if closed and elapsed_pct > 0:
            avg_vol = sum(c.volume for c in closed) / len(closed)
            expected = elapsed_pct * avg_vol
            if expected > 0:
                volume_pace = volume_so_far / expected

        current_candle = CurrentCandleData(
            open=candle_open,
            high_so_far=high_so_far,
            low_so_far=low_so_far,
            last_price=tick.price,
            partial_ret=partial_ret,
            volume_so_far=volume_so_far,
            volume_pace=volume_pace,
            elapsed_sec=elapsed,
            elapsed_pct=elapsed_pct,
            time_remaining_sec=time_remaining,
            chainlink_heartbeat_age_sec=heartbeat_age,
        )

        # -- Microstructure ----------------------------------------------------
        mid = tick.price
        spread_bps = (tick.ask - tick.bid) / mid * 10_000 if mid > 0 else 0.0

        up_book = snapshot.up_book
        microstructure = Microstructure(
            spread_bps=spread_bps,
            ob_imbalance=up_book.imbalance,
            polymarket_yes_price=up_book.midpoint,
            polymarket_yes_delta=None,
            polymarket_vol_delta=None,
        )

        # -- Technicals (not yet implemented) ----------------------------------
        technicals = Technicals(
            rsi14=None,
            macd_hist=None,
            bb_pct_b=None,
            atr14_norm=None,
        )

        # -- Bet state (not yet implemented) -----------------------------------
        bet_state = BetState(
            bet_open_price=None,
            unrealised_ret=None,
            hold_count=0,
            time_remaining_sec=time_remaining,
        )

        return PromptState(
            candles=candles,
            current_candle=current_candle,
            technicals=technicals,
            microstructure=microstructure,
            bet_state=bet_state,
        )
