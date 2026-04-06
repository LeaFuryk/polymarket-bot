"""Bot entry point — connects to collector WS, computes indicators, re-broadcasts on 8766."""

import asyncio
import logging
import os

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.services.agent_service import AgentService
from polybot.services.indicator_service import IndicatorService
from polybot.services.portfolio_service import PortfolioService
from polybot.ws import Broadcaster, PolybotServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("polybot")


async def main() -> None:
    broadcaster = Broadcaster()
    server = PolybotServer(broadcaster)
    await server.start()

    repo = SqliteCandleRepository("data/collection.db")
    await repo.init()

    indicators = IndicatorService(candle_repo=repo)

    initial_cash = float(os.environ.get("POLYBOT_TRADING_INITIAL_CASH", "1000.0"))
    portfolio = PortfolioService(initial_cash=initial_cash)
    session_store = JsonlSessionStore("data/sessions.jsonl")

    agent = AgentService(indicators=indicators, portfolio=portfolio)

    async def on_message(msg: dict) -> None:
        await agent.process(msg)
        await broadcaster.broadcast_json(msg)

    client = CollectorClient(on_message=on_message)

    try:
        await client.run()
    finally:
        summary = portfolio.session_summary()
        log.info(
            "📋 Session: W=%d L=%d | PnL=$%.2f | Balance=$%.2f | Return=%+.1f%%",
            summary["wins"],
            summary["losses"],
            summary["net_pnl"],
            summary["final_balance"],
            summary["total_return_pct"],
        )
        await session_store.save_session(summary)
        await client.stop()
        await repo.close()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
