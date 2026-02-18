"""Resolution verification — determines candle winner via BTC price."""

from __future__ import annotations

import logging

from polybot.market_data.btc_price import BtcPriceFeed
from polybot.models import CandleMarket, ResolutionRecord

logger = logging.getLogger(__name__)


class ResolutionTracker:
    """Tracks candle open prices and resolves winners at market rotation."""

    def __init__(self, btc_feed: BtcPriceFeed) -> None:
        self._btc_feed = btc_feed
        # condition_id -> opening BTC price
        self._open_prices: dict[str, float] = {}

    def record_candle_open(self, market: CandleMarket, btc_price: float) -> None:
        """Record the BTC price at candle open for later resolution."""
        self._open_prices[market.condition_id] = btc_price
        logger.info(
            "Recorded candle open: %s BTC=$%.2f",
            market.slug, btc_price,
        )

    async def resolve(
        self, market: CandleMarket, current_btc_price: float,
    ) -> ResolutionRecord:
        """Resolve a candle market by comparing open vs close BTC price.

        Args:
            market: The candle market being resolved.
            current_btc_price: BTC price at rotation time (close price).

        Returns:
            ResolutionRecord with winner determination and PnL data.
        """
        btc_close = current_btc_price

        # Get opening price: prefer live-captured, fallback to Binance historical
        btc_open = self._open_prices.pop(market.condition_id, None)
        if btc_open is None:
            logger.warning(
                "No live open price for %s, fetching from Binance",
                market.slug,
            )
            btc_open = await self._btc_feed.get_price_at(market.start_time)
            if btc_open is None:
                logger.error(
                    "Could not determine open price for %s, defaulting to close",
                    market.slug,
                )
                btc_open = btc_close  # will resolve as "down" (tie goes to down)

        winner = "up" if btc_close > btc_open else "down"

        logger.info(
            "Resolved %s: open=$%.2f close=$%.2f → winner=%s",
            market.slug, btc_open, btc_close, winner,
        )

        return ResolutionRecord(
            slug=market.slug,
            condition_id=market.condition_id,
            start_time=market.start_time,
            end_time=market.end_time,
            btc_open=btc_open,
            btc_close=btc_close,
            winner=winner,
            up_pnl=0.0,  # filled in by agent after portfolio resolution
            down_pnl=0.0,
            total_pnl=0.0,
        )
