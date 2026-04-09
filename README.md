# Polymarket BTC Candle Bot

A trading bot for Polymarket's 5-minute BTC UP/DOWN prediction markets. Collects live market data, computes 60 technical indicators, runs 3 ML models in parallel (LogisticRegression, RandomForest, XGBoost), each with independent portfolios and strategies, and broadcasts trading events to a real-time dashboard.

## Architecture

Three components connected via WebSocket:

```
┌─────────────────────────────────────────────────────────────┐
│ Collector (port 8765)                                        │
│                                                              │
│ Chainlink Data Streams → CandleAggregator → 5-min OHLCV     │
│ Binance API → Volume data                                    │
│ Polymarket APIs → Orderbooks, token prices, market volume    │
│                                                              │
│ DataCollector → SQLite (data/collection.db) + WS broadcast   │
│ Resolution Queue → Polymarket Gamma API verification         │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│ Polybot (port 8766)                                          │
│                                                              │
│ AgentService (orchestrator)                                   │
│   ├── IndicatorService → 60 technical indicators (shared)    │
│   ├── ModelRunner: LogisticRegression (own portfolio + bets) │
│   ├── ModelRunner: RandomForest (own portfolio + bets)       │
│   └── ModelRunner: XGBoost (own portfolio + bets)            │
│                                                              │
│ Each runner: Predictor → TradingStrategy → PortfolioService  │
│ Broadcasts: model_entry, model_settlement + collector events │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│ Dashboard (port 3000)                                        │
│                                                              │
│ Next.js 16 / React 19 / Tailwind / Custom SVG charts         │
│ Section 1: Candle chart (BTC OHLC history)                   │
│ Section 2: Current bet (UP/DOWN price lines + model entries) │
│ Section 3: Portfolio comparison (3 equity curves + stats)     │
│ Section 4: Previous bets (expandable trade history)           │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Set up environment
cp .env.example .env
# Edit .env with your Chainlink Data Streams credentials

# 3. Start the collector (runs continuously)
uv run python -m collector

# 4. In another terminal, start the bot (runs 3 models in parallel)
uv run python -m polybot

# 5. In another terminal, start the dashboard
cd dashboard-next && npm install && npm run dev
# Open http://localhost:3000
```

## Technology

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Package Manager | uv |
| Market Data | Chainlink Data Streams WebSocket, Binance API, Polymarket CLOB + Gamma APIs |
| ML Models | scikit-learn (LogisticRegression, RandomForest), XGBoost (calibrated) |
| Data Store | SQLite (aiosqlite) |
| WebSocket | websockets library |
| Event System | pyee (AsyncIOEventEmitter) |
| Dashboard | Next.js 16, React 19, Tailwind CSS 4, custom SVG charts |
| Linter | ruff |
| Tests | pytest (235 tests) |

## Project Structure

```
polybot_data/               # Shared data layer
├── domain/                 # Domain models (Candle, Snapshot, CandleRecord)
├── ports/                  # Port protocols (CandleSource, DataStore, MarketFeed)
├── adapters/               # Adapters (Chainlink, Binance, Polymarket, SQLite)
└── services/               # Services (CandleAggregator, DataCollector, indicator_engine)

polybot/                    # Trading bot
├── domain/                 # Bot domain (Position, PortfolioState, BetRecord, TradingStrategy)
├── ports/                  # Port protocols (Predictor, CandleRepository, SessionStore, BetStore)
├── adapters/               # Adapters (JoblibPredictor, SqliteCandleRepo, JsonlStores)
├── services/               # Services (AgentService, ModelRunner, IndicatorService, PortfolioService)
└── ws/                     # WebSocket (Broadcaster, PolybotServer)

collector/                  # Collector process
├── __main__.py             # Entry point
└── server.py               # WS server (port 8765)

dashboard-next/             # Real-time dashboard (Next.js)
└── src/
    ├── components/         # Candles, current bet, portfolios, history
    ├── hooks/              # useWebSocket (port 8766)
    ├── context/            # DashboardContext (central state)
    └── lib/                # Types, constants, formatters

notebooks/                  # Research & evaluation
├── data/                   # 01_build_features, 02_data_experiments
├── eval/                   # 01_model_comparison, 02_advanced_models
├── lr/                     # 01_feature_selection, 02_export, 03_strategy
├── rf/                     # 01_feature_selection, 02_export, 03_strategy
├── xgb/                    # 01_feature_selection, 02_export, 03_strategy
└── experiments/            # reversal_indicators (archived)

models/                     # Trained models (joblib)
├── logistic_v1.joblib      # LogisticRegression
├── scaler_v1.joblib
├── feature_cols_v1.joblib
├── rf_v1.joblib            # RandomForest
├── rf_scaler_v1.joblib
├── rf_feature_cols_v1.joblib
├── xgb_v1.joblib           # XGBoost
├── xgb_scaler_v1.joblib
├── xgb_feature_cols_v1.joblib
└── xgb_calibrator_v1.joblib  # Isotonic probability calibrator

data/
├── collection.db           # SQLite database (candles + snapshots)
├── latest_features.jsonl   # Pre-computed features for notebooks
├── optimal_features_lr.json   # LR optimal feature set
├── optimal_features_rf.json   # RF optimal feature set
├── optimal_features_xgb.json  # XGB optimal feature set + hyperparameters
├── optimal_strategy_lr.json   # LR best scaling-in strategy
├── optimal_strategy_rf.json   # RF best scaling-in strategy
├── optimal_strategy_xgb.json  # XGB best scaling-in strategy
└── bets/                   # Per-model bet records
    ├── LogisticRegression/
    ├── RandomForest/
    └── XGBoost/

scripts/
├── db_stats.sh             # Quick DB stats (read-only)
└── verify_resolutions.py   # Batch-verify candles against Polymarket
```

## Multi-Model Trading

The bot runs 3 models in parallel, each with:
- Its own **predictor** (loaded from `models/`)
- Its own **portfolio** ($1,000 starting balance each)
- Its own **strategy** (loaded from `data/optimal_strategy_*.json`)
- Its own **bet records** (separate JSONL files per model)

Each model's strategy is discovered through notebook evaluation:

| Model | Features | Strategy | Selection Method |
|-------|----------|----------|-----------------|
| LogisticRegression | `optimal_features_lr.json` | `optimal_strategy_lr.json` | Forward selection |
| RandomForest | `optimal_features_rf.json` | `optimal_strategy_rf.json` | Importance ranking |
| XGBoost | `optimal_features_xgb.json` | `optimal_strategy_xgb.json` | Importance ranking + grid search + calibration |

## Notebook Pipeline

```
data/01_build_features  →  latest_features.jsonl
         ↓
*/01_feature_selection  →  optimal_features_*.json
         ↓
*/02_export             →  models/*.joblib
         ↓
*/03_strategy           →  optimal_strategy_*.json
         ↓
eval/01_model_comparison  (loads from models/, head-to-head comparison)
```

All model notebooks follow the same structure: `01_feature_selection`, `02_export`, `03_strategy`. Feature selection produces a JSON config, export trains on all data and saves to `models/`, strategy loads the exported model and finds the best scaling-in configuration.

## Trading Strategy

Each model uses the **Strategy pattern** via `TradingStrategy` (loaded from JSON):

- **Entry points**: configurable checkpoints (e.g., 5% elapsed, 50% elapsed)
- **Consecutive agreement**: N predictions must agree before entering
- **Confidence threshold**: minimum prediction confidence to trigger entry
- **Bet sizing**: 2% of portfolio balance per entry
- **Max bid**: $0.85 (risk/reward floor)

Settlement: winning shares pay $1 each, losing shares expire at $0.

**Polymarket fees**: `fee = shares × 0.072 × price × (1 - price)`

## Dashboard

Real-time trading dashboard at `http://localhost:3000`. Connects to Polybot WS (port 8766) — single connection receives all events.

**Events:**
- `snapshot` — BTC price, orderbooks, elapsed % (from collector)
- `candle_close` — OHLC, outcome (from collector)
- `model_entry` — model name, direction, price, confidence, inference time
- `model_settlement` — model name, outcome, PnL, cash, W/L counts

**Sections:**
1. Candle chart — last 20 candles with outcome badges
2. Current bet — UP/DOWN price lines with model entry markers (color-coded per model)
3. Portfolio comparison — 3 equity curves + stats cards (balance, W/L, win rate, return)
4. Previous bets — expandable list with historical price charts and model markers

## Configuration

Environment variables (in `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `POLYBOT_DB_PATH` | `data/collection.db` | SQLite database path |
| `POLYBOT_TRADING_INITIAL_CASH` | `1000.0` | Starting balance per model |
| `POLYBOT_SESSION_PATH` | `data/sessions.jsonl` | Session summary output |

Model and strategy paths are configured in `polybot/__main__.py` via `MODEL_CONFIGS`.

## Tests

```bash
uv run pytest tests/ -v          # Run all 235 tests
uv run pytest tests/ --cov       # With coverage
uv run ruff check .              # Lint
```
