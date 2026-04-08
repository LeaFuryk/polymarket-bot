"""Bot entry point — connects to collector WS, computes indicators, re-broadcasts on 8766."""

import asyncio
import logging
import os
from dataclasses import asdict

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.joblib_predictor import JoblibPredictor
from polybot.adapters.jsonl_bet_store import JsonlBetStore
from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.services.agent_service import AgentService
from polybot.services.indicator_service import IndicatorService
from polybot.services.portfolio_service import PortfolioService
from polybot.ws import Broadcaster, PolybotServer

# ---------------------------------------------------------------------------
# Configuration (overridable via environment variables)
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("POLYBOT_DB_PATH", "data/collection.db")
SESSION_PATH = os.environ.get("POLYBOT_SESSION_PATH", "data/sessions.jsonl")
BETS_DIR = os.environ.get("POLYBOT_BETS_DIR", "data/bets")
MODEL_PATH = os.environ.get("POLYBOT_MODEL_PATH", "models/logistic_v1.joblib")
SCALER_PATH = os.environ.get("POLYBOT_SCALER_PATH", "models/scaler_v1.joblib")
FEATURES_PATH = os.environ.get("POLYBOT_FEATURES_PATH", "models/feature_cols_v1.joblib")
INITIAL_CASH = float(os.environ.get("POLYBOT_TRADING_INITIAL_CASH", "1000.0"))

# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("polybot")


async def main() -> None:
    repo = SqliteCandleRepository(DB_PATH)
    await repo.init()

    indicators = IndicatorService(candle_repo=repo)
    portfolio = PortfolioService(initial_cash=INITIAL_CASH)
    session_store = JsonlSessionStore(SESSION_PATH)
    bet_store = JsonlBetStore(directory=BETS_DIR)

    predictor = JoblibPredictor(
        model_path=MODEL_PATH,
        scaler_path=SCALER_PATH,
        feature_cols_path=FEATURES_PATH,
    )

    agent = AgentService(
        indicators=indicators,
        portfolio=portfolio,
        predictor=predictor,
        bet_store=bet_store,
    )

    def build_initial_state() -> dict:
        return {
            "type": "initial_state",
            "candles": [asdict(c) for c in indicators.prior_candles],
            "snapshots_so_far": [asdict(s) for s in indicators.snapshots_so_far],
            "portfolio": portfolio.session_summary(),
        }

    broadcaster = Broadcaster()
    server = PolybotServer(broadcaster, initial_state_fn=build_initial_state)
    await server.start()

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
