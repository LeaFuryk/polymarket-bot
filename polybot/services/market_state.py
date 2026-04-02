"""Service: assembles market state for the fine-tuned model."""

from __future__ import annotations

import asyncio
import logging
import math
import time

from polybot.domain.models import (
    BetState,
    BtcTick,
    Candle,
    CurrentCandleData,
    Market,
    MarketSnapshot,
    Microstructure,
    PartialCandleSnapshot,
    PromptState,
    Technicals,
)
from polybot.ports.candle_source import CandleSource
from polybot.ports.market_feed import MarketFeed
from polybot.services.technicals import (
    atr_normalized,
    bollinger_pct_b,
    macd_histogram,
    rsi,
)

CANDLE_INTERVAL = 300  # 5 minutes


class MarketStateService:
    """Orchestrates CandleSource + MarketFeed into a PromptState snapshot.

    Depends on CandleSource (read-only candle data) and MarketFeed (Polymarket).
    """

    def __init__(
        self,
        candle_source: CandleSource,
        market_feed: MarketFeed,
        series_slug: str = "btc-updown-5m",
        logger: logging.Logger | None = None,
    ) -> None:
        self._candles = candle_source
        self._market_feed = market_feed
        self._series_slug = series_slug
        self._log = logger or logging.getLogger(__name__)

    async def get_state(self) -> PromptState | None:
        """Build the full market state snapshot."""
        tick = self._candles.latest_tick
        if tick is None:
            self._log.warning("No Chainlink tick available yet")
            return None

        # Snapshot ALL state BEFORE any network await for consistency.
        now = time.time()
        candles = self._candles.candle_data()
        partial = self._candles.partial
        partial_snapshot = partial.freeze() if partial else None
        closed = self._candles.closed_candles()

        vol_start = partial_snapshot.start_time if partial_snapshot else now - (now % CANDLE_INTERVAL)
        vol_end = min(now, partial_snapshot.end_time) if partial_snapshot else now

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            self._log.warning("No Polymarket market found")
            return None

        # Only fetch volume if we have an active partial candle
        if partial_snapshot:
            snapshot, volume_so_far = await asyncio.gather(
                self._market_feed.get_snapshot(market),
                self._candles.get_partial_volume(vol_start, vol_end),
            )
        else:
            snapshot = await self._market_feed.get_snapshot(market)
            volume_so_far = 0.0

        return PromptState(
            candles=candles,
            current_candle=self._build_current_candle(tick, market, partial_snapshot, closed, volume_so_far, now),
            technicals=self._build_technicals(closed),
            microstructure=self._build_microstructure(tick, snapshot),
            bet_state=self._build_bet_state(market, now),
        )

    # -- Private builders --------------------------------------------------

    def _build_current_candle(
        self,
        tick: BtcTick,
        market: Market,
        partial: PartialCandleSnapshot | None,
        closed: tuple[Candle, ...],
        volume_so_far: float = 0.0,
        snapshot_time: float = 0.0,
    ) -> CurrentCandleData:
        now = snapshot_time or time.time()
        if partial:
            candle_start = partial.start_time
            elapsed = tick.timestamp - candle_start
        else:
            candle_start = now - (now % CANDLE_INTERVAL)
            elapsed = now - candle_start

        elapsed_pct = max(0.0, min(elapsed / CANDLE_INTERVAL, 1.0))
        time_remaining = max(0.0, market.end_time - now)

        candle_open = partial.open if partial else None
        high_so_far = partial.high if partial else None
        low_so_far = partial.low if partial else None

        partial_ret = None
        if candle_open is not None and candle_open > 0:
            partial_ret = math.log(tick.price / candle_open)

        # volume_pace = volume_so_far / (elapsed_pct × avg_volume)
        volume_pace = None
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
            time_remaining_sec=time_remaining,
            chainlink_heartbeat_age_sec=now - tick.timestamp,
        )

    def _build_technicals(self, closed: tuple[Candle, ...]) -> Technicals:
        closes = [c.close for c in closed]
        return Technicals(
            rsi14=rsi(closes),
            macd_hist=macd_histogram(closes),
            bb_pct_b=bollinger_pct_b(closes),
            atr14_norm=atr_normalized(closed),
        )

    def _build_microstructure(self, tick: BtcTick, snapshot: MarketSnapshot) -> Microstructure:
        mid = tick.price
        spread_bps = (tick.ask - tick.bid) / mid * 10_000 if mid > 0 else 0.0
        up_book = snapshot.up_book
        return Microstructure(
            spread_bps=spread_bps,
            ob_imbalance=up_book.imbalance,
            polymarket_yes_price=up_book.midpoint,
            polymarket_yes_delta=None,  # TODO: track midpoint at candle open
            polymarket_vol_delta=None,  # TODO: track volume at candle open
        )

    def _build_bet_state(self, market: Market, now: float) -> BetState:
        return BetState(
            bet_open_price=None,
            unrealised_ret=None,
            hold_count=0,
            time_remaining_sec=max(0.0, market.end_time - now),
        )
