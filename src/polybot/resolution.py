"""Resolution verification — determines candle winner via BTC price + Polymarket verification."""

from __future__ import annotations

import asyncio
import logging

from polybot.market_data.btc_price import BtcPriceFeed
from polybot.market_data.client import PolymarketRestClient
from polybot.models import CandleMarket, ResolutionRecord

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
        # condition_id -> opening BTC price
        self._open_prices: dict[str, float] = {}

    def record_candle_open(self, market: CandleMarket, btc_price: float) -> None:
        """Record the BTC price at candle open for later resolution."""
        self._open_prices[market.condition_id] = btc_price
        logger.info(
            "Recorded candle open: %s BTC=$%.2f",
            market.slug, btc_price,
        )

    async def _verify_winner_on_polymarket(
        self, market: CandleMarket, btc_winner: str,
    ) -> str:
        """Verify the winner by checking token prices on Polymarket after resolution.

        After a market resolves, the winning token trades at ~$1 and the loser at ~$0.
        We check last trade prices for both UP and DOWN tokens. If they contradict
        our BTC-based determination, we use Polymarket's outcome as authoritative
        (since Polymarket resolves via Chainlink Data Streams, not Binance).

        Returns the verified winner string ("up" or "down").
        """
        if self._rest_client is None:
            return btc_winner

        try:
            # Brief delay to let the market settle on Polymarket
            await asyncio.sleep(3)

            up_price = await self._rest_client.get_last_trade_price(
                token_id=market.up_token_id,
            )
            down_price = await self._rest_client.get_last_trade_price(
                token_id=market.down_token_id,
            )

            logger.info(
                "Polymarket verification for %s: UP=%.4f DOWN=%.4f (BTC says: %s)",
                market.slug,
                up_price or 0.0,
                down_price or 0.0,
                btc_winner,
            )

            # Determine Polymarket's actual winner from token prices
            # After resolution, winning token → ~$1 (>0.85), losing → ~$0 (<0.15)
            polymarket_winner = None
            if up_price is not None and down_price is not None:
                if up_price > 0.85 and down_price < 0.15:
                    polymarket_winner = "up"
                elif down_price > 0.85 and up_price < 0.15:
                    polymarket_winner = "down"
                elif up_price > 0.65 and down_price < 0.35:
                    # Less extreme but still clear signal
                    polymarket_winner = "up"
                elif down_price > 0.65 and up_price < 0.35:
                    polymarket_winner = "down"

            if polymarket_winner is None:
                # Prices are ambiguous (market may not have settled yet)
                logger.warning(
                    "Polymarket prices ambiguous for %s (UP=%.4f DOWN=%.4f), "
                    "using BTC-based winner: %s",
                    market.slug, up_price or 0.0, down_price or 0.0, btc_winner,
                )
                return btc_winner

            if polymarket_winner != btc_winner:
                logger.warning(
                    "WINNER MISMATCH for %s! BTC says %s but Polymarket says %s. "
                    "Using Polymarket's outcome as authoritative.",
                    market.slug, btc_winner, polymarket_winner,
                )
                return polymarket_winner

            logger.info(
                "Winner verified for %s: %s (BTC and Polymarket agree)",
                market.slug, btc_winner,
            )
            return btc_winner

        except Exception:
            logger.exception(
                "Failed to verify winner on Polymarket for %s, "
                "using BTC-based winner: %s",
                market.slug, btc_winner,
            )
            return btc_winner

    async def resolve(
        self, market: CandleMarket, current_btc_price: float,
    ) -> ResolutionRecord:
        """Resolve a candle market by comparing open vs close BTC price,
        then verify against Polymarket's actual outcome.

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
                btc_open = btc_close  # will resolve as "up" (tie goes to up)

        # Primary determination: BTC price comparison
        # Polymarket rule: "greater than or equal to" → UP wins on tie
        btc_winner = "up" if btc_close >= btc_open else "down"

        logger.info(
            "BTC resolution for %s: open=$%.2f close=$%.2f → %s",
            market.slug, btc_open, btc_close, btc_winner,
        )

        # Verify against Polymarket's actual outcome
        winner = await self._verify_winner_on_polymarket(market, btc_winner)

        if winner != btc_winner:
            logger.warning(
                "Final resolution for %s: OVERRIDDEN to %s "
                "(BTC said %s, Polymarket said %s)",
                market.slug, winner, btc_winner, winner,
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
