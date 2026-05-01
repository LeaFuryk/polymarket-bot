"""Bot entry point — runs LR, RF, XGBoost (+ optional DNN) in parallel on collector WS stream."""

import asyncio
import logging
import os
from dataclasses import asdict
from pathlib import Path

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

try:
    from polybot.adapters.dnn_predictor import DnnPredictor

    _HAS_DNN = True
except ImportError:
    _HAS_DNN = False

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

DNN_CONFIG = {
    "name": "DNN",
    "model_path": "models/dnn_v1.pt",
    "scaler_path": "models/dnn_scaler_v1.joblib",
    "calibrator_path": "models/dnn_calibrator_v1.joblib",
    "features_path": "models/dnn_feature_cols_v1.joblib",
    "strategy_path": "data/optimal_strategy_dnn.json",
    "bets_dir": "data/bets/DNN",
    "temporal": False,
}

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
            "🤖 %s: %d features, min_edge=%.3f, max_entries=%d",
            cfg["name"],
            len(predictor._feature_cols),
            strategy.min_edge,
            strategy.max_entries,
        )

    # --- Optional DNN runner ---
    if _HAS_DNN and Path(DNN_CONFIG["model_path"]).exists():
        _cal_path = DNN_CONFIG["calibrator_path"]
        dnn_predictor = DnnPredictor(
            model_path=DNN_CONFIG["model_path"],
            scaler_path=DNN_CONFIG["scaler_path"],
            calibrator_path=_cal_path if Path(_cal_path).exists() else None,
            feature_cols_path=DNN_CONFIG["features_path"],
            temporal=DNN_CONFIG["temporal"],
        )
        dnn_portfolio = PortfolioService(initial_cash=INITIAL_CASH)
        dnn_strategy = TradingStrategy.from_json(DNN_CONFIG["strategy_path"], name=DNN_CONFIG["name"])
        dnn_bet_store = JsonlBetStore(directory=DNN_CONFIG["bets_dir"])

        dnn_runner = ModelRunner(
            name=DNN_CONFIG["name"],
            predictor=dnn_predictor,
            portfolio=dnn_portfolio,
            strategy=dnn_strategy,
            bet_store=dnn_bet_store,
            broadcaster=broadcaster,
        )
        runners.append(dnn_runner)
        log.info(
            "🤖 %s: %d features (temporal=%s), min_edge=%.3f, max_entries=%d",
            DNN_CONFIG["name"],
            len(dnn_predictor._feature_cols),
            DNN_CONFIG["temporal"],
            dnn_strategy.min_edge,
            dnn_strategy.max_entries,
        )
    elif not _HAS_DNN:
        log.info("⏭️  DNN model skipped — torch not installed")
    else:
        log.info("⏭️  DNN model skipped — %s not found", DNN_CONFIG["model_path"])

    # --- Consensus runner (DNN + majority vote) ---
    consensus_runner: ModelRunner | None = None
    consensus_strategy_path = "data/optimal_strategy_consensus.json"
    if Path(consensus_strategy_path).exists() and _HAS_DNN and any(r.name == "DNN" for r in runners):
        from polybot.adapters.consensus_predictor import ConsensusPredictor

        consensus_strategy = TradingStrategy.from_json(consensus_strategy_path, name="Consensus")
        consensus_predictor = ConsensusPredictor(
            dnn_name="DNN",
            edge_threshold=consensus_strategy.edge_threshold,
            min_agreement=consensus_strategy.min_agreement,
        )
        consensus_portfolio = PortfolioService(initial_cash=INITIAL_CASH)
        consensus_bet_store = JsonlBetStore(directory="data/bets/Consensus")

        consensus_runner = ModelRunner(
            name="Consensus",
            predictor=consensus_predictor,
            portfolio=consensus_portfolio,
            strategy=consensus_strategy,
            bet_store=consensus_bet_store,
            broadcaster=broadcaster,
            is_ensemble=True,
        )
        log.info(
            "🤖 Consensus: DNN + majority agree, edge_threshold=%.3f, min_agreement=%d",
            consensus_strategy.edge_threshold,
            consensus_strategy.min_agreement,
        )
    else:
        log.info("⏭️  Consensus skipped — requires DNN + strategy config")

    active_names = [r.name for r in runners]
    log.info("🚀 Active models: %s", ", ".join(active_names))

    agent = AgentService(indicators=indicators, runners=runners, consensus_runner=consensus_runner)

    def build_initial_state() -> dict:
        all_runners = runners + ([consensus_runner] if consensus_runner else [])
        all_entries: list[dict] = []
        for r in all_runners:
            all_entries.extend(r.current_entries)
        return {
            "type": "initial_state",
            "candles": [asdict(c) for c in indicators.prior_candles],
            "snapshots_so_far": [asdict(s) for s in indicators.snapshots_so_far],
            "portfolios": {r.name: r.portfolio.session_summary() for r in all_runners},
            "equity_history": {r.name: r.equity_history for r in all_runners},
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
        all_runners = runners + ([consensus_runner] if consensus_runner else [])
        for runner in all_runners:
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
