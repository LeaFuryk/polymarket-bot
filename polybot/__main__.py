"""Bot entry point — connects to collector WS, logs data, re-broadcasts on port 8766."""

import asyncio
import logging

from polybot.adapters.collector_client import CollectorClient
from polybot.ws import Broadcaster, PolybotServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def main() -> None:
    broadcaster = Broadcaster()
    server = PolybotServer(broadcaster)
    await server.start()

    client = CollectorClient(relay=broadcaster)

    try:
        await client.run()
    finally:
        await client.stop()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
