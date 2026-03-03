"""Polymarket verification — confirms BTC-based winner against on-chain outcome."""

from __future__ import annotations

import asyncio
import logging

from polybot.models import CandleMarket
from polybot.resolution.checker import determine_polymarket_winner
from polybot.resolution.constants import VERIFICATION_DELAY
from polybot.resolution.protocol import PriceClient

logger = logging.getLogger(__name__)


async def verify_winner(
    market: CandleMarket,
    btc_winner: str,
    rest_client: PriceClient | None,
) -> str:
    """Verify the BTC-based winner against Polymarket's actual outcome.

    After a market resolves, the winning token trades at ~$1 and the loser
    at ~$0. If Polymarket disagrees with BTC, we use Polymarket as
    authoritative (resolves via Chainlink Data Streams, not Binance).

    Returns the verified winner ("up" or "down").
    """
    if rest_client is None:
        return btc_winner

    try:
        await asyncio.sleep(VERIFICATION_DELAY)

        up_price = await rest_client.get_last_trade_price(
            token_id=market.up_token_id,
        )
        down_price = await rest_client.get_last_trade_price(
            token_id=market.down_token_id,
        )

        logger.info(
            "Polymarket verification for %s: UP=%.4f DOWN=%.4f (BTC says: %s)",
            market.slug,
            up_price or 0.0,
            down_price or 0.0,
            btc_winner,
        )

        polymarket_winner = determine_polymarket_winner(up_price, down_price)

        if polymarket_winner is None:
            logger.warning(
                "Polymarket prices ambiguous for %s (UP=%.4f DOWN=%.4f), using BTC-based winner: %s",
                market.slug,
                up_price or 0.0,
                down_price or 0.0,
                btc_winner,
            )
            return btc_winner

        if polymarket_winner != btc_winner:
            logger.warning(
                "WINNER MISMATCH for %s! BTC says %s but Polymarket says %s. "
                "Using Polymarket's outcome as authoritative.",
                market.slug,
                btc_winner,
                polymarket_winner,
            )
            return polymarket_winner

        logger.info(
            "Winner verified for %s: %s (BTC and Polymarket agree)",
            market.slug,
            btc_winner,
        )
        return btc_winner

    except Exception:
        logger.exception(
            "Failed to verify winner on Polymarket for %s, using BTC-based winner: %s",
            market.slug,
            btc_winner,
        )
        return btc_winner
