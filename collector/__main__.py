"""Data server — collects market data, broadcasts via WebSocket, records to SQLite."""

import asyncio
import logging
import os

from dotenv import load_dotenv
from polybot_data.adapters.binance_volume import BinanceVolumeAdapter
from polybot_data.adapters.chainlink_streams import ChainlinkStreamsAdapter
from polybot_data.adapters.polymarket import PolymarketAdapter
from polybot_data.adapters.sqlite_store import SqliteStore
from polybot_data.services.candle_aggregator import CandleAggregator
from polybot_data.services.data_collector import DataCollector
from pyee.asyncio import AsyncIOEventEmitter

from collector.server import CollectorServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def main() -> None:
    load_dotenv()

    price_stream = ChainlinkStreamsAdapter(
        user_id=os.environ["CH_STREAM_USER_ID"],
        secret=os.environ["CH_STREAM_SECRETS"],
    )
    volume_feed = BinanceVolumeAdapter()
    market_feed = PolymarketAdapter()

    store = SqliteStore("data/collection.db")
    await store.init()

    events = AsyncIOEventEmitter()
    events.on("error", lambda err: logging.getLogger("collector.events").exception("Event handler error: %s", err))
    aggregator = CandleAggregator(price_stream, volume_feed, events=events)

    # WS server — thin broadcaster, no fetching
    server = CollectorServer()
    await server.start()

    # Single fetch loop: builds snapshot → broadcasts via server + records to SQLite
    collector = DataCollector(
        aggregator,
        market_feed,
        store,
        events=events,
        broadcast_fn=server.broadcast_json,
    )

    await price_stream.connect()

    agg_task = asyncio.create_task(aggregator.run())
    col_task = asyncio.create_task(collector.run())

    try:
        done, _ = await asyncio.wait([agg_task, col_task], return_when=asyncio.FIRST_EXCEPTION)
        # Re-raise the first exception
        for task in done:
            task.result()
    finally:
        # Cancel running tasks
        for task in [agg_task, col_task]:
            task.cancel()
        await asyncio.gather(agg_task, col_task, return_exceptions=True)

        # Wait for pending candle_close event handlers to finish
        try:
            await asyncio.wait_for(events.wait_for_complete(), timeout=15.0)
        except TimeoutError:
            pass
        await collector.drain()
        await server.stop()
        await price_stream.disconnect()
        await volume_feed.close()
        await market_feed.close()
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
