"""Bot entry point — runs LR, RF, XGBoost in parallel on collector WS stream."""

import asyncio
import logging
import os
from dataclasses import asdict

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.joblib_predictor import JoblibPredictor
from polybot.adapters.jsonl_bet_store import JsonlBetStore
from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.domain.trading_strategy import TradingStrategy
from polybot.services.agent_service import AgentService
from polybot.services.indicator_service import IndicatorService
from polybot.services.model_runner import ModelRunner
from polybot.services.portfolio_service import PortfolioService
from polybot.ws import Broadcaster, PolybotServer

DB_PATH = os.environ.get("POLYBOT_DB_PATH", "data/collection.db")
SESSION_PATH = os.environ.get("POLYBOT_SESSION_PATH", "data/sessions.jsonl")
INITIAL_CASH = float(os.environ.get("POLYBOT_TRADING_INITIAL_CASH", "1000.0"))

MODEL_CONFIGS = [
    {
        "name": "LogisticRegression",
        "model_path": "models/logistic_v1.joblib",
        "scaler_path": "models/scaler_v1.joblib",
        "features_path": "models/feature_cols_v1.joblib",
        "strategy_path": "data/optimal_strategy_lr.json",
        "bets_dir": "data/bets/LogisticRegression",
    },
    {
        "name": "RandomForest",
        "model_path": "models/rf_v1.joblib",
        "scaler_path": "models/rf_scaler_v1.joblib",
        "features_path": "models/rf_feature_cols_v1.joblib",
        "strategy_path": "data/optimal_strategy_rf.json",
        "bets_dir": "data/bets/RandomForest",
    },
    {
        "name": "XGBoost",
        "model_path": "models/xgb_calibrator_v1.joblib",
        "scaler_path": "models/xgb_scaler_v1.joblib",
        "features_path": "models/xgb_feature_cols_v1.joblib",
        "strategy_path": "data/optimal_strategy_xgb.json",
        "bets_dir": "data/bets/XGBoost",
    },
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("polybot")


async def main() -> None:
    repo = SqliteCandleRepository(DB_PATH)
    await repo.init()

    indicators = IndicatorService(candle_repo=repo)
    broadcaster = Broadcaster()
    session_store = JsonlSessionStore(SESSION_PATH)

    runners: list[ModelRunner] = []
    for cfg in MODEL_CONFIGS:
        predictor = JoblibPredictor(
            model_path=cfg["model_path"],
            scaler_path=cfg["scaler_path"],
            feature_cols_path=cfg["features_path"],
        )
        portfolio = PortfolioService(initial_cash=INITIAL_CASH)
        strategy = TradingStrategy.from_json(cfg["strategy_path"], name=cfg["name"])
        bet_store = JsonlBetStore(directory=cfg["bets_dir"])

        runner = ModelRunner(
            name=cfg["name"],
            predictor=predictor,
            portfolio=portfolio,
            strategy=strategy,
            bet_store=bet_store,
            broadcaster=broadcaster,
        )
        runners.append(runner)
        log.info(
            "🤖 %s: %d features, strategy=%s, conf>%.1f",
            cfg["name"],
            len(predictor._feature_cols),
            strategy.entry_points,
            strategy.min_confidence,
        )

    agent = AgentService(indicators=indicators, runners=runners)

    def build_initial_state() -> dict:
        all_entries: list[dict] = []
        for r in runners:
            all_entries.extend(r.current_entries)
        return {
            "type": "initial_state",
            "candles": [asdict(c) for c in indicators.prior_candles],
            "snapshots_so_far": [asdict(s) for s in indicators.snapshots_so_far],
            "portfolios": {r.name: r.portfolio.session_summary() for r in runners},
            "equity_history": {r.name: r.equity_history for r in runners},
            "current_entries": all_entries,
        }

    server = PolybotServer(broadcaster, initial_state_fn=build_initial_state)
    await server.start()

    async def on_message(msg: dict) -> None:
        await agent.process(msg)
        await broadcaster.broadcast_json(msg)

    client = CollectorClient(on_message=on_message)

    try:
        await client.run()
    finally:
        for runner in runners:
            summary = runner.portfolio.session_summary()
            summary["model"] = runner.name
            log.info(
                "📋 %s: W=%d L=%d | PnL=$%.2f | Balance=$%.2f | Return=%+.1f%%",
                runner.name,
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
