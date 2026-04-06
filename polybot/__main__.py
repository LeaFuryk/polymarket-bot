"""Bot entry point — connects to collector WS, computes indicators, re-broadcasts on 8766."""

import asyncio
import logging
import os

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.services.agent_service import AgentService
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

    agent = AgentService(candle_repo=repo)

    initial_cash = float(os.environ.get("POLYBOT_TRADING_INITIAL_CASH", "1000.0"))
    portfolio = PortfolioService(initial_cash=initial_cash)
    session_store = JsonlSessionStore("data/sessions.jsonl")

    async def on_message(msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            row = agent.on_snapshot(msg)
            if row is not None:
                up = row.get("up_best_bid"), row.get("up_best_ask")
                down = row.get("down_best_bid"), row.get("down_best_ask")
                if up[0] is not None and up[1] is not None and down[0] is not None and down[1] is not None:
                    portfolio.update_prices((up[0] + up[1]) / 2, (down[0] + down[1]) / 2)
                log.info(
                    "📊 %s | elapsed=%.0f%% | BTC $%.2f | rsi=%s | streak=%s | cash=$%.2f",
                    row["candle_id"],
                    (row["elapsed_pct"] or 0) * 100,
                    row["btc_price"] or 0,
                    row.get("rsi"),
                    row.get("consecutive_streak"),
                    portfolio.state.cash,
                )
        elif msg_type == "candle_close":
            await agent.on_candle_close(msg)
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
