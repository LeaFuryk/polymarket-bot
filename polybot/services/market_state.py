"""Service: assembles market state for the fine-tuned model."""

from __future__ import annotations

import asyncio
import logging
import time

from polybot.domain.models import (
    BetState,
    BtcTick,
    CurrentCandleData,
    Microstructure,
    PromptState,
    Technicals,
)
from polybot.ports.market_feed import MarketFeed
from polybot.ports.price_stream import PriceStream
from polybot.ports.volume_feed import VolumeFeed

logger = logging.getLogger(__name__)

CANDLE_INTERVAL = 300  # 5 minutes


class MarketStateService:
    """Orchestrates all adapters and returns a PromptState snapshot.

    Depends only on ports (PriceStream, VolumeFeed, MarketFeed).
    """

    def __init__(
        self,
        price_stream: PriceStream,
        volume_feed: VolumeFeed,
        market_feed: MarketFeed,
        series_slug: str = "btc-updown-5m",
    ) -> None:
        self._price_stream = price_stream
        self._volume_feed = volume_feed
        self._market_feed = market_feed
        self._series_slug = series_slug
        self._latest_tick: BtcTick | None = None

    async def consume_ticks(self) -> None:
        """Background task: consume Chainlink ticks into internal buffer."""
        async for tick in self._price_stream.ticks():
            self._latest_tick = tick

    async def get_state(self) -> PromptState | None:
        """Build the full market state snapshot.

        Returns None if essential data (tick or market) is unavailable.
        """
        tick = self._latest_tick
        if tick is None:
            logger.warning("No Chainlink tick available yet")
            return None

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            logger.warning("No Polymarket market found")
            return None

        # Fetch Polymarket snapshot + Binance volume in parallel
        now = time.time()
        candle_start = now - (now % CANDLE_INTERVAL)

        snapshot, volume_so_far = await asyncio.gather(
            self._market_feed.get_snapshot(market),
            self._volume_feed.get_volume(candle_start, now),
        )

        # -- Build current candle ------------------------------------------
        elapsed = now - candle_start
        time_remaining = market.time_remaining
        elapsed_pct = elapsed / CANDLE_INTERVAL if CANDLE_INTERVAL > 0 else 0.0

        heartbeat_age = now - tick.timestamp

        current_candle = CurrentCandleData(
            open=None,
            high_so_far=None,
            low_so_far=None,
            last_price=tick.price,
            partial_ret=None,
            volume_so_far=volume_so_far,
            volume_pace=None,
            elapsed_sec=elapsed,
            elapsed_pct=elapsed_pct,
            time_remaining_sec=time_remaining,
            chainlink_heartbeat_age_sec=heartbeat_age,
        )

        # -- Build microstructure ------------------------------------------
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

        # -- Technicals (not yet implemented) ------------------------------
        technicals = Technicals(
            rsi14=None,
            macd_hist=None,
            bb_pct_b=None,
            atr14_norm=None,
        )

        # -- Bet state (not yet implemented) -------------------------------
        bet_state = BetState(
            bet_open_price=None,
            unrealised_ret=None,
            hold_count=0,
            time_remaining_sec=time_remaining,
        )

        return PromptState(
            candles=(),
            current_candle=current_candle,
            technicals=technicals,
            microstructure=microstructure,
            bet_state=bet_state,
        )
