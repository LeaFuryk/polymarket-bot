"""Service: assembles market state for the fine-tuned model."""

from __future__ import annotations

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

        # Snapshot candle state BEFORE any network await.
        candles = self._candles.candle_data()
        partial = self._candles.partial
        partial_snapshot = partial.freeze() if partial else None
        closed = self._candles.closed_candles()

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            self._log.warning("No Polymarket market found")
            return None

        snapshot = await self._market_feed.get_snapshot(market)

        return PromptState(
            candles=candles,
            current_candle=self._build_current_candle(tick, market, partial_snapshot, closed),
            technicals=self._build_technicals(closed),
            microstructure=self._build_microstructure(tick, snapshot),
            bet_state=self._build_bet_state(market),
        )

    # -- Private builders --------------------------------------------------

    def _build_current_candle(
        self,
        tick: BtcTick,
        market: Market,
        partial: PartialCandleSnapshot | None,
        closed: tuple[Candle, ...],
    ) -> CurrentCandleData:
        if partial:
            candle_start = partial.start_time
            elapsed = tick.timestamp - candle_start
        else:
            now = time.time()
            candle_start = now - (now % CANDLE_INTERVAL)
            elapsed = now - candle_start

        elapsed_pct = max(0.0, min(elapsed / CANDLE_INTERVAL, 1.0))
        time_remaining = max(0.0, market.end_time - time.time())

        candle_open = partial.open if partial else None
        high_so_far = partial.high if partial else None
        low_so_far = partial.low if partial else None

        partial_ret = None
        if candle_open is not None and candle_open > 0:
            partial_ret = math.log(tick.price / candle_open)

        # Volume not yet wired for mid-candle.
        # volume_so_far is 0.0 because the schema requires float (not Optional).
        # volume_pace is None (Optional) to signal "unknown" to the model.
        # TODO: wire Binance mid-candle volume to populate these correctly.
        volume_so_far = 0.0
        volume_pace = None

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
            chainlink_heartbeat_age_sec=time.time() - tick.timestamp,
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

    def _build_bet_state(self, market: Market) -> BetState:
        return BetState(
            bet_open_price=None,
            unrealised_ret=None,
            hold_count=0,
            time_remaining_sec=max(0.0, market.end_time - time.time()),
        )
