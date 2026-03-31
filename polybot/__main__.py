"""Smoke script — connect to Chainlink Data Streams and print BTC ticks."""

import asyncio
import os

from dotenv import load_dotenv

from polybot.adapters.chainlink_streams import ChainlinkStreamsAdapter


async def main() -> None:
    load_dotenv()

    user_id = os.environ["CH_STREAM_USER_ID"]
    secret = os.environ["CH_STREAM_SECRETS"]

    adapter = ChainlinkStreamsAdapter(user_id=user_id, secret=secret)
    await adapter.connect()

    try:
        async for tick in adapter.ticks():
            spread = tick.ask - tick.bid
            print(f"BTC ${tick.price:,.2f}  bid ${tick.bid:,.2f}  ask ${tick.ask:,.2f}  spread ${spread:.2f}")
    except KeyboardInterrupt:
        pass
    finally:
        await adapter.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
