"""Bot entry point — connects to collector WS, computes indicators, re-broadcasts on 8766."""

import asyncio
import logging

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.services.agent_service import AgentService
from polybot.ws import Broadcaster, PolybotServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("polybot")


async def main() -> None:
    broadcaster = Broadcaster()
    server = PolybotServer(broadcaster)
    await server.start()

    repo = SqliteCandleRepository("data/collection.db")
    await repo.init()

    agent = AgentService(candle_repo=repo)

    async def on_message(msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            row = agent.on_snapshot(msg)
            if row is not None:
                log.info(
                    "📊 %s | elapsed=%.0f%% | BTC $%.2f | rsi=%s | streak=%s",
                    row["candle_id"],
                    (row["elapsed_pct"] or 0) * 100,
                    row["btc_price"] or 0,
                    row.get("rsi"),
                    row.get("consecutive_streak"),
                )
        elif msg_type == "candle_close":
            await agent.on_candle_close(msg)
        await broadcaster.broadcast_json(msg)

    client = CollectorClient(on_message=on_message)

    try:
        await client.run()
    finally:
        await client.stop()
        await repo.close()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
