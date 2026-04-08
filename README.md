# Polymarket BTC Candle Bot

A trading bot for Polymarket's 5-minute BTC UP/DOWN prediction markets. Collects live market data, computes 60 technical indicators, predicts outcomes with ML models, and executes a scaling-in trading strategy.

## Architecture

Two independent processes connected via WebSocket:

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
│   ├── IndicatorService → 60 technical indicators per tick    │
│   ├── Predictor (RF/LR) → P(UP) probability                 │
│   ├── PortfolioService → Cash, positions, PnL, fees         │
│   └── Scaling-in strategy → 2x entries with 3-consecutive   │
│                                                              │
│ Broadcaster → WS (port 8766) → Dashboard                     │
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

# 4. In another terminal, start the bot
uv run python -m polybot
```

## Technology

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Package Manager | uv |
| Market Data | Chainlink Data Streams WebSocket, Binance API, Polymarket CLOB + Gamma APIs |
| ML Models | scikit-learn (LogisticRegression, RandomForest) |
| Data Store | SQLite (aiosqlite) |
| WebSocket | websockets library |
| Event System | pyee (AsyncIOEventEmitter) |
| Linter | ruff |
| Tests | pytest (217 tests) |

## Project Structure

```
polybot_data/               # Shared data layer
├── domain/                 # Domain models (Candle, Snapshot, CandleRecord)
├── ports/                  # Port protocols (CandleSource, DataStore, MarketFeed)
├── adapters/               # Adapters (Chainlink, Binance, Polymarket, SQLite)
└── services/               # Services (CandleAggregator, DataCollector, indicator_engine)

polybot/                    # Trading bot
├── domain/                 # Bot domain models (Position, PortfolioState, BetRecord)
├── ports/                  # Port protocols (Predictor, CandleRepository, SessionStore, BetStore)
├── adapters/               # Adapters (JoblibPredictor, SqliteCandleRepo, JsonlStores)
├── services/               # Services (AgentService, IndicatorService, PortfolioService)
└── ws/                     # WebSocket (Broadcaster, PolybotServer)

collector/                  # Collector process
├── __main__.py             # Entry point
└── server.py               # WS server (port 8765)

notebooks/                  # Research & evaluation (14 notebooks)
├── 0 - build_features.ipynb      # DB → latest_features.jsonl
├── 1 - model_training.ipynb      # Feature selection, forward selection
├── 4 - advanced_models.ipynb     # LR vs RF vs XGBoost vs DNN
├── 10 - export_model.ipynb       # Export LR model
├── 11 - rf_optimization.ipynb    # RF feature importance + optimization
├── 12 - lr_vs_rf.ipynb           # Head-to-head comparison
└── 13 - export_rf_model.ipynb    # Export RF model

models/                     # Trained models (joblib)
├── rf_v1.joblib            # RandomForest (20 features, 88.2% per-candle)
├── rf_scaler_v1.joblib
├── rf_feature_cols_v1.joblib
├── logistic_v1.joblib      # LogisticRegression (31 features)
├── scaler_v1.joblib
└── feature_cols_v1.joblib

scripts/
├── db_stats.sh             # Quick DB stats (read-only)
└── verify_resolutions.py   # Batch-verify candles against Polymarket
```

## Trading Strategy

**Scaling-in with 3-consecutive trigger** (from notebook 8):

1. **Entry 1** at elapsed >= 5%: if 3 consecutive predictions agree → bet 2% of balance
2. **Entry 2** at elapsed >= 50%: if model still agrees with entry 1 → add 2% of balance
3. If model flips direction → stop scaling
4. Max entry price: $0.85 (R/R floor)

Settlement: winning shares pay $1 each, losing shares expire at $0.

**Polymarket fees**: `fee = shares × 0.072 × price × (1 - price)` on buys (shares) and sells (USDC).

## Data Pipeline

```
1. Collector records candles + snapshots to SQLite (5s intervals)
2. Resolution queue verifies prices against Polymarket every 60s
3. Run notebook 0 to compute features → data/latest_features.jsonl
4. Run notebooks 1-13 for analysis, training, evaluation
5. Export model to models/ directory
6. Polybot loads model on startup, runs predictions every second
```

## Configuration

Environment variables (in `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `POLYBOT_DB_PATH` | `data/collection.db` | SQLite database path |
| `POLYBOT_MODEL_PATH` | `models/rf_v1.joblib` | Model file path |
| `POLYBOT_SCALER_PATH` | `models/rf_scaler_v1.joblib` | Scaler file path |
| `POLYBOT_FEATURES_PATH` | `models/rf_feature_cols_v1.joblib` | Feature columns path |
| `POLYBOT_TRADING_INITIAL_CASH` | `1000.0` | Starting balance |
| `POLYBOT_SESSION_PATH` | `data/sessions.jsonl` | Session summary output |
| `POLYBOT_BETS_DIR` | `data/bets` | Bet records directory |

## Tests

```bash
uv run pytest tests/ -v          # Run all 217 tests
uv run pytest tests/ --cov       # With coverage
uv run ruff check .              # Lint
```
