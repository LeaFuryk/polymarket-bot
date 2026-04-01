"""Service: assembles market state for the fine-tuned model."""

from __future__ import annotations

import logging
import math
import time

from polybot.domain.models import (
    BetState,
    BtcTick,
    CurrentCandleData,
    Market,
    MarketSnapshot,
    Microstructure,
    PromptState,
    Technicals,
)
from polybot.ports.market_feed import MarketFeed
from polybot.services.candle_aggregator import CandleAggregator
from polybot.services.technicals import (
    atr_normalized,
    bollinger_pct_b,
    macd_histogram,
    rsi,
)

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
        """Build the full market state snapshot."""
        tick = self._aggregator.latest_tick
        if tick is None:
            logger.warning("No Chainlink tick available yet")
            return None

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            logger.warning("No Polymarket market found")
            return None

        snapshot = await self._market_feed.get_snapshot(market)

        return PromptState(
            candles=self._aggregator.candle_data(),
            current_candle=self._build_current_candle(tick, market),
            technicals=self._build_technicals(),
            microstructure=self._build_microstructure(tick, snapshot),
            bet_state=self._build_bet_state(market),
        )

    # -- Private builders --------------------------------------------------

    def _build_current_candle(self, tick: BtcTick, market: Market) -> CurrentCandleData:
        now = time.time()
        candle_start = now - (now % CANDLE_INTERVAL)
        elapsed = now - candle_start
        elapsed_pct = elapsed / CANDLE_INTERVAL

        partial = self._aggregator.partial
        candle_open = partial.open if partial else None
        high_so_far = partial.high if partial else None
        low_so_far = partial.low if partial else None

        partial_ret = None
        if candle_open is not None and candle_open > 0:
            partial_ret = math.log(tick.price / candle_open)

        # Volume tracking not yet wired for mid-candle
        volume_so_far = 0.0
        volume_pace = None
        closed = self._aggregator.closed_candles()
        if closed and elapsed_pct > 0:
            avg_vol = sum(c.volume for c in closed) / len(closed)
            expected = elapsed_pct * avg_vol
            if expected > 0:
                volume_pace = volume_so_far / expected

        return CurrentCandleData(
            open=candle_open,
            high_so_far=high_so_far,
            low_so_far=low_so_far,
            last_price=tick.price,
            partial_ret=partial_ret,
            volume_so_far=volume_so_far,
            volume_pace=volume_pace,
            elapsed_sec=elapsed,
            elapsed_pct=elapsed_pct,
            time_remaining_sec=market.time_remaining,
            chainlink_heartbeat_age_sec=now - tick.timestamp,
        )

    def _build_technicals(self) -> Technicals:
        candles = self._aggregator.closed_candles()
        closes = [c.close for c in candles]
        return Technicals(
            rsi14=rsi(closes),
            macd_hist=macd_histogram(closes),
            bb_pct_b=bollinger_pct_b(closes),
            atr14_norm=atr_normalized(candles),
        )

    def _build_microstructure(self, tick: BtcTick, snapshot: MarketSnapshot) -> Microstructure:
        mid = tick.price
        spread_bps = (tick.ask - tick.bid) / mid * 10_000 if mid > 0 else 0.0
        up_book = snapshot.up_book
        return Microstructure(
            spread_bps=spread_bps,
            ob_imbalance=up_book.imbalance,
            polymarket_yes_price=up_book.midpoint,
            polymarket_yes_delta=None,
            polymarket_vol_delta=None,
        )

    def _build_bet_state(self, market: Market) -> BetState:
        return BetState(
            bet_open_price=None,
            unrealised_ret=None,
            hold_count=0,
            time_remaining_sec=market.time_remaining,
        )
