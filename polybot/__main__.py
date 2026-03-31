"""Smoke script — connect to Chainlink Data Streams and fetch Binance volume."""

import asyncio
import os

from dotenv import load_dotenv

from polybot.adapters.binance_volume import BinanceVolumeAdapter
from polybot.adapters.chainlink_streams import ChainlinkStreamsAdapter


async def main() -> None:
    load_dotenv()

    user_id = os.environ["CH_STREAM_USER_ID"]
    secret = os.environ["CH_STREAM_SECRETS"]

    price_stream = ChainlinkStreamsAdapter(user_id=user_id, secret=secret)
    volume_feed = BinanceVolumeAdapter()

    # Fetch last 5 candle volumes on startup
    volumes = await volume_feed.get_candle_volumes(5)
    print(f"Last 5 candle volumes (BTC): {[f'{v:.2f}' for v in volumes]}")

    await price_stream.connect()

    try:
        async for tick in price_stream.ticks():
            spread = tick.ask - tick.bid
            print(f"BTC ${tick.price:,.2f}  bid ${tick.bid:,.2f}  ask ${tick.ask:,.2f}  spread ${spread:.2f}")
    except KeyboardInterrupt:
        pass
    finally:
        await price_stream.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
