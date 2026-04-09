# Project Configuration

## Notion
- **Project name**: Polymarket Bot
- **Project page**: a55d248f-c6ac-4e11-a7b4-d40efd2be958
- **Tasks database**: 3187e505-e99b-817c-adad-d61e81be1261
- **Tasks data source**: collection://6497e505-e99b-8248-9718-07551fec2fa9
- **Projects data source**: collection://56e7e505-e99b-8321-a1f4-878d833d9136

## Skills
- `notion-tasks` — Task management from Notion board. Always check Notion before starting work.
- `tars` — All GitHub operations via tars-bot-01 GitHub App (push, PRs, comments, reviews)
- `codex` — Code review gate. Run `/codex:rescue --model gpt-5.4` after implementation to review changes.
- `superpowers` — Planning, TDD, systematic debugging, parallel agents, code review, git worktrees.

## Code Review
- After writing or modifying code, run a Codex review (`/codex:rescue --model gpt-5.4`) on changed files before marking work as complete
- Fix any issues found by the review before presenting results
- Run Codex repeatedly until it reports "No issues found"

## Conventions
- Package manager: `uv`
- Python version: 3.11+
- Linter: `ruff`
- Tests: `pytest` (run with `uv run pytest tests/ -v`)
- Coverage: `uv run pytest --cov --cov-report=term-missing`
- Branch naming: `feat/`, `fix/`, `chore/`
- Commits end with `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`

## Architecture

### Hexagonal Architecture
All code follows hexagonal (ports & adapters) architecture:
- **Ports** in `polybot/ports/` and `polybot_data/ports/` — Protocol classes defining contracts
- **Adapters** in `polybot/adapters/` and `polybot_data/adapters/` — Concrete implementations
- **Services** in `polybot/services/` and `polybot_data/services/` — Business logic
- **Domain** in `polybot/domain/` and `polybot_data/domain/` — Data models
- Adapters MUST explicitly implement their port (e.g., `class JoblibPredictor(Predictor)`)
- Use typed models (dataclasses), NOT dicts, for data flowing through the system
- Dict access only at system boundaries (WS messages) — decode to models immediately via `from_dict`/`from_ws` classmethods on the models

### Two Processes
1. **Collector** (`uv run python -m collector`) — Records market data to SQLite
   - CandleAggregator: builds 5-min OHLCV candles from Chainlink ticks
   - DataCollector: writes snapshots + candles to DB, broadcasts via WS (port 8765)
   - Resolution queue: verifies candle data against Polymarket's authoritative prices
2. **Polybot** (`uv run python -m polybot`) — Trading bot
   - Connects to collector WS, computes 60 indicators, runs ML predictions
   - AgentService orchestrates: IndicatorService + PortfolioService + Predictor
   - Scaling-in strategy with confidence filtering
   - Re-broadcasts on port 8766 for dashboard

### Key Data Flow
```
Chainlink ticks → CandleAggregator → candle_close event → DataCollector → SQLite + WS broadcast
                                                                            ↓
Polybot ← WS (port 8765) → AgentService.process(msg) → IndicatorService + PortfolioService + Predictor
                                                          ↓
                                                        Broadcaster → WS (port 8766) → Dashboard
```

### Polymarket Resolution
- Candles are initially written with Chainlink prices
- A resolution queue checks Polymarket's Gamma API every 60s for authoritative prices
- Open, close, and outcome are corrected to match Polymarket's `eventMetadata`
- On outcome mismatch, portfolio is reverse-settled and re-settled
- `scripts/verify_resolutions.py` can batch-verify all candles against Polymarket

### Recording Startup Flow
1. Aggregator discards first incomplete candle (no event emitted)
2. DataCollector detects candle_id boundary change → `_recording = True`
3. First `candle_close` with `_recording = True` → skip write (this candle was incomplete)
4. Second candle → full snapshots + candle record written
- **NEVER** record orphaned snapshots
- **NEVER** gate snapshots on candle_close events — gate on candle_id boundary changes

## Database
- SQLite at `data/collection.db` — ALWAYS use `-readonly` flag when querying from scripts
- Do NOT query the live DB without `-readonly` — it corrupts the collector's connection
- `scripts/db_stats.sh` for quick stats
- `scripts/verify_resolutions.py` to sync all candles with Polymarket

## Models
- Trained models in `models/` directory (joblib format)
- LogisticRegression: `logistic_v1.joblib` + `scaler_v1.joblib` + `feature_cols_v1.joblib`
- RandomForest: `rf_v1.joblib` + `rf_scaler_v1.joblib` + `rf_feature_cols_v1.joblib`
- XGBoost (calibrated): `xgb_v1.joblib` + `xgb_scaler_v1.joblib` + `xgb_feature_cols_v1.joblib` + `xgb_calibrator_v1.joblib`
- Feature configs: `data/optimal_features_{lr,rf,xgb}.json`
- Strategy configs: `data/optimal_strategy_{lr,rf,xgb}.json`

## Notebooks
Organized into subfolders under `notebooks/`:
```
data/     01_build_features, 02_data_experiments
eval/     01_model_comparison (loads models/, no retraining), 02_advanced_models
lr/       01_feature_selection → optimal_features_lr.json, 02_export → models/, 03_strategy → optimal_strategy_lr.json
rf/       01_feature_selection → optimal_features_rf.json, 02_export → models/, 03_strategy → optimal_strategy_rf.json
xgb/      01_feature_selection → optimal_features_xgb.json, 02_export → models/, 03_strategy → optimal_strategy_xgb.json
experiments/  reversal_indicators (archived)
```
- Run `data/01_build_features` FIRST → `data/latest_features.jsonl`
- Then `*/01_feature_selection` → `data/optimal_features_*.json`
- Then `*/02_export` → `models/`
- Then `*/03_strategy` and `eval/` notebooks (load from `models/`, no retraining)
- `notebooks/technicals.py` — thin re-export from `polybot_data/services/indicator_engine.py`

## Critical Rules
- NEVER modify collector code without explicit user approval
- NEVER start/stop the collector process
- ALWAYS use Codex review before presenting changes as complete
- ALWAYS use typed models, not dicts, inside the codebase
- ALWAYS broadcast full models (via `dataclasses.asdict`), not hand-built dicts
