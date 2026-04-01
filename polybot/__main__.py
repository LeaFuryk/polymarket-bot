"""Entry point — run MarketStateService and print prompt state."""

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

from polybot.adapters.binance_volume import BinanceVolumeAdapter
from polybot.adapters.chainlink_streams import ChainlinkStreamsAdapter
from polybot.adapters.polymarket import PolymarketAdapter
from polybot.services.market_state import MarketStateService

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def main() -> None:
    load_dotenv()

    price_stream = ChainlinkStreamsAdapter(
        user_id=os.environ["CH_STREAM_USER_ID"],
        secret=os.environ["CH_STREAM_SECRETS"],
    )
    volume_feed = BinanceVolumeAdapter()
    market_feed = PolymarketAdapter()

    service = MarketStateService(price_stream, volume_feed, market_feed)

    await price_stream.connect()
    asyncio.create_task(service.consume_ticks())

    # Wait briefly for first tick
    await asyncio.sleep(2)

    while True:
        state = await service.get_state()
        if state is not None:
            print(json.dumps(state.to_dict(), indent=2))
        else:
            print("Waiting for data...")
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
