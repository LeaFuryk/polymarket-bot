"""Smoke script — connect all data providers and print live data."""

import asyncio
import logging
import os

from dotenv import load_dotenv

from polybot.adapters.binance_volume import BinanceVolumeAdapter
from polybot.adapters.chainlink_streams import ChainlinkStreamsAdapter
from polybot.adapters.polymarket import PolymarketAdapter

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")

SERIES_SLUG = "btc-updown-5m"


async def print_volume_and_market(
    volume_feed: BinanceVolumeAdapter,
    market_feed: PolymarketAdapter,
) -> None:
    """Print Binance volume and Polymarket snapshot every 60 seconds."""
    while True:
        print("\n=== Binance Volume (last 5 candles) ===")
        volumes = await volume_feed.get_candle_volumes(5)
        for i, v in enumerate(volumes, 1):
            print(f"  candle {i}: {v:.2f} BTC")

        print("\n=== Polymarket Snapshot ===")
        market = await market_feed.discover_market(SERIES_SLUG)
        if market:
            print(f"  market:    {market.question}")
            print(f"  slug:      {market.slug}")
            print(f"  remaining: {market.time_remaining:.0f}s")

            snapshot = await market_feed.get_snapshot(market)
            up = snapshot.up_book
            down = snapshot.down_book
            print(
                f"  UP  book:  bid={up.best_bid}  ask={up.best_ask}  mid={up.midpoint}  depth={up.bid_depth:.0f}/{up.ask_depth:.0f}"
            )
            print(
                f"  DOWN book: bid={down.best_bid}  ask={down.best_ask}  mid={down.midpoint}  depth={down.bid_depth:.0f}/{down.ask_depth:.0f}"
            )
            print(f"  last trade: {snapshot.last_trade_price}")
            print(f"  imbalance:  {up.imbalance:.3f}")
        else:
            print("  No market found")

        await asyncio.sleep(60)


async def print_chainlink_ticks(price_stream: ChainlinkStreamsAdapter) -> None:
    """Stream and print Chainlink ticks."""
    await price_stream.connect()
    try:
        async for tick in price_stream.ticks():
            spread = tick.ask - tick.bid
            print(f"BTC ${tick.price:,.2f}  bid ${tick.bid:,.2f}  ask ${tick.ask:,.2f}  spread ${spread:.2f}")
    finally:
        await price_stream.disconnect()


async def main() -> None:
    load_dotenv()

    price_stream = ChainlinkStreamsAdapter(
        user_id=os.environ["CH_STREAM_USER_ID"],
        secret=os.environ["CH_STREAM_SECRETS"],
    )
    volume_feed = BinanceVolumeAdapter()
    market_feed = PolymarketAdapter()

    await asyncio.gather(
        print_volume_and_market(volume_feed, market_feed),
        print_chainlink_ticks(price_stream),
    )


if __name__ == "__main__":
    asyncio.run(main())
