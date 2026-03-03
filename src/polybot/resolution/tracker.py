"""ResolutionTracker — orchestrates candle resolution."""

from __future__ import annotations

import logging

from polybot.market_data.btc_price import BtcPriceFeed
from polybot.market_data.client import PolymarketRestClient
from polybot.models import CandleMarket, ResolutionRecord
from polybot.resolution.checker import determine_btc_winner
from polybot.resolution.verifier import verify_winner

logger = logging.getLogger(__name__)


class ResolutionTracker:
    """Tracks candle open prices and resolves winners at market rotation.

    Primary: BTC open/close price comparison (fast, usually correct).
    Verification: Checks Polymarket token prices after resolution to confirm
    the winner matches the on-chain outcome (Chainlink Data Streams).
    """

    def __init__(
        self,
        btc_feed: BtcPriceFeed,
        rest_client: PolymarketRestClient | None = None,
    ) -> None:
        self._btc_feed = btc_feed
        self._rest_client = rest_client
        self._open_prices: dict[str, float] = {}

    def record_candle_open(self, market: CandleMarket, btc_price: float) -> None:
        """Record the BTC price at candle open for later resolution."""
        self._open_prices[market.condition_id] = btc_price
        logger.info(
            "Recorded candle open: %s BTC=$%.2f",
            market.slug,
            btc_price,
        )

    def get_candle_open(self, condition_id: str) -> float | None:
        """Get the recorded BTC open price for the current candle."""
        return self._open_prices.get(condition_id)

    async def resolve(
        self,
        market: CandleMarket,
        current_btc_price: float,
    ) -> ResolutionRecord:
        """Resolve a candle market by comparing open vs close BTC price,
        then verify against Polymarket's actual outcome.
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
                btc_open = btc_close  # will resolve as "up" (tie goes to up)

        btc_winner = determine_btc_winner(btc_open, btc_close)

        logger.info(
            "BTC resolution for %s: open=$%.2f close=$%.2f → %s",
            market.slug,
            btc_open,
            btc_close,
            btc_winner,
        )

        winner = await verify_winner(market, btc_winner, self._rest_client)

        if winner != btc_winner:
            logger.warning(
                "Final resolution for %s: OVERRIDDEN to %s (BTC said %s, Polymarket said %s)",
                market.slug,
                winner,
                btc_winner,
                winner,
            )

        return ResolutionRecord(
            slug=market.slug,
            condition_id=market.condition_id,
            start_time=market.start_time,
            end_time=market.end_time,
            btc_open=btc_open,
            btc_close=btc_close,
            winner=winner,
            up_pnl=0.0,
            down_pnl=0.0,
            total_pnl=0.0,
        )
