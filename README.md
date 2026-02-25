# Polymarket BTC Candle Bot

An AI-powered paper trading agent that trades Polymarket BTC 5-minute candle prediction markets using Claude as its decision engine. The bot features a self-improving feedback loop where Claude reflects on past outcomes, updates its own knowledge base, and tunes the indicators fed into future decisions.

**Paper trading only** — no real money is ever at risk. The bot simulates order execution, slippage, fees, and portfolio accounting against live Polymarket orderbook data.

---

## Technology

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| AI Brain | Claude (Anthropic API) with structured JSON output |
| Market Data | Binance BTC/USDT spot (primary), Chainlink on-chain (cross-ref), CoinGecko (24h change), Binance 5-min OHLCV |
| Data Models | Pydantic v2 |
| Config | YAML + `.env` overrides |
| Dashboard | Rich live terminal UI + standalone web dashboard |
| Logging | JSONL (daily-rotating trade + resolution logs) + SQLite analytics |
| Package | `setuptools` with `src/` layout |

### Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client (async) — decisions + reflection |
| `py-clob-client` | Polymarket CLOB REST orderbook + trade data |
| `httpx` | Async HTTP for CoinGecko, Binance, Gamma discovery API |
| `pydantic` | Strict data contracts across all components |
| `pyyaml` | Configuration loading |
| `rich` | Live terminal dashboard + analysis reports |
| `websockets` | WebSocket support (wired, not yet active) |
| `python-dotenv` | `.env` secret management |

### External APIs

| API | Auth | Purpose |
|-----|------|---------|
| Polymarket CLOB | None (public) | Orderbooks, last trade prices |
| Polymarket Gamma | None | Market discovery by slug pattern |
| Chainlink BTC/USD (on-chain) | None (public RPC) | **Primary BTC price** — matches Polymarket resolution source |
| CoinGecko | None | 24h change % (convenience metric only) |
| Binance klines | None | 5-min OHLCV candle history for micro-trend analysis; historical price fallback |
| Ethereum RPC | None | Read Chainlink price feed aggregator contract |

---

## How It Works

The bot runs 6 concurrent async tasks in the same event loop. The MarketMonitor fetches data every second, runs prefilter checks, and triggers the AI when conditions are favorable. The AIDecision task waits for triggers and runs the full decision pipeline. The PositionMonitor tracks open positions every second and triggers exits at stop-loss/take-profit thresholds. Every 10 candle resolutions, Claude reflects on its performance using a quantitative scorecard and produces structured observations that feed into future decisions.

### The Self-Improving Loop

```
Monitor ──► Trigger AI ──► Trade ──► Monitor P&L ──► SL/TP Exit
  │              │           │           │              │
  │              │           │           │              └─ PositionMonitor detects -60%/+80%
  │              │           │           │                 → triggers AI exit evaluation
  │              │           │           │
  │              │           │           └─ PositionMonitor marks-to-market every 1s
  │              │           │
  │              │           └─ Simulated execution with slippage + 20bps fees
  │              │
  │              └─ AIDecision: indicators, ML, two-pass screen, Claude → JSON
  │
  └─ MarketMonitor: 1s data fetch, prefilter, R/R check → trigger AI

Resolve ──► Reflect ──► Adjust Inputs ──► (next candle)
```

### Multi-Task Architecture

```
TradingAgent.run()  (orchestrator)
    |
    +-- MarketMonitor (1s loop) -- fetches data, runs prefilter, records snapshots, signals AI
    +-- AIDecision (event-driven) -- makes trades when triggered, has cooldown
    +-- PositionMonitor (1s loop) -- tracks P&L, triggers exits at SL/TP
    +-- RotationLoop (5s loop) -- handles candle transitions
    +-- DashboardLoop (2s loop) -- writes dashboard JSON
    +-- DataStore writer (async) -- batched SQLite inserts from queue
```

All tasks are `asyncio.Task` in the same event loop (no OS threads). Safe for shared state.

### MarketMonitor (every 1 second)

1. **Fetch snapshot** — Up + Down orderbooks, BTC spot price (2s cache TTL), latest 5-min candle
2. **Run prefilter** — Checks 1-5: time remaining, spread width, book depth, choppy market, entry setup
3. **Record PreFilterSnapshot** — Per-second market state stored in a 300-entry deque (~5 min history)
4. **Compute R/R** — Calculate risk/reward ratio for both UP and DOWN tokens
5. **Trigger AI** — Uses adaptive entry thresholds (learned from rolling candle history) to decide when to call AI. The `AdaptiveEntryTracker` sets a BTC move threshold ($20/$30/$40) based on rolling reversal rate and caps entry price based on recent winner ask prices. Falls back to static R/R threshold when adaptive is disabled. AI cooldown (60s) still applies

### AIDecision (event-driven)

Waits for entry triggers (from MarketMonitor) or exit triggers (from PositionMonitor):

1. **Pre-trade risk checks** — Daily loss halt, minimum liquidity
2. **Build context** — FeatureVector + BTC candle history + feedback context + computed indicators + ML prediction
3. **Two-pass screening** — Haiku screens first (entry only, not exits)
4. **Claude decides** — Full Sonnet decision with structured JSON output
5. **Confidence gate** — Override BUY to HOLD if confidence < 0.55
6. **Calibration gate** — Override BUY to HOLD if calibrated win rate < break-even
7. **Anti-hedge guard** — Blocks BUY if opposite side has shares
8. **Position sizing** — Flattened R/R scale: 100% at R/R >= 2.0, 80% at 1.0, 55% at 0.5, 20% minimum. Multiplied by BTC move magnitude scaling (80%/90%/100%). Minimum 40 shares enforced
8. **Post-trade risk checks** — Position size, concentration, cash, spread (BUY only)
9. **Execute + log** — Simulate fill, update portfolio, write TradeRecord

### PositionMonitor (every 1 second)

1. **Mark-to-market** — Update position values using cached snapshot
2. **Compute P&L %** — For each open position (UP and DOWN independently)
3. **Check thresholds** — Stop-loss at -60%, take-profit at +80% (configurable)
4. **Trigger exit** — Push exit signal to AIDecision with reason and current P&L (respects AI cooldown; emergencies ≤-30% bypass)

### Market Rotation & Resolution

When a 5-minute candle expires and a new one begins:
- All pending limit orders are cancelled
- The old candle is resolved by comparing BTC price at open vs close (from Chainlink)
- Resolves "Up" if close >= open, "Down" otherwise (equal price = Up wins)
- Winning token positions settle at $1/share, losing at $0
- Session W/L stats are updated
- Portfolio positions reset for the new candle
- Every 10 resolutions → **reflection** is triggered
- Resolution counter is persisted to `logs/agent_state.json` so it survives restarts

### Pending Bet Recovery on Startup

If the bot crashes or is stopped mid-candle, trades may be logged without a matching resolution. On restart, the bot automatically detects and resolves these:

1. Scans `trades_*.jsonl` for candle slugs with fills (BUY/SELL) but no entry in `resolutions_*.jsonl`
2. Fetches each unresolved market from the Gamma API and verifies the candle has ended
3. Looks up BTC open/close prices via Binance historical API
4. Verifies the winner against Polymarket token prices (settled at ~$1/$0)
5. Reconstructs PnL from logged fills and writes the missing resolution record
6. Appends to dashboard history so all-time stats remain accurate

This runs once at startup before the main trading loop begins. Candles that are still live are skipped.

### Reflection (Self-Improvement)

After every 10 candle resolutions, the bot calls Claude with a **quantitative scorecard** (current batch vs previous batch: win rate, avg PnL, avg win/loss size, hold rate) plus resolution/trade tables and active observations. This creates a real feedback loop where reflection can see if its changes helped.

Claude produces **structured observations** — descriptive, not imperative:
- Good: "momentum plays at entry 0.30-0.40 won 3/4 times"
- Forbidden: "NEVER trade above 0.40" or "require 0.72+ confidence"

Each observation is categorized (pattern/bias/edge/regime) and stored in `observations.jsonl` with an expiry (default 30 resolutions). Reflection can also explicitly expire old observations that are contradicted by new data. This **append-only with decay** approach prevents the death spiral where reflection wrote escalating rules into persistent files.

**Base knowledge** (`trading_patterns.md`, `self_assessment.md`) is **read-only** — human-curated strategy and bias notes injected into decisions as reference, never overwritten by reflection. Session history gets one row appended per reflection batch.

The decision prompt shows active observations as contextual hints with age and remaining life:
```
## Recent Observations (contextual hints, not hard rules)
- [pattern] momentum plays at entry 0.30-0.40 won 3/4 times (observed 5 resolutions ago, expires in 25)
- [edge] late-candle entries (<90s) at <0.35 had 80% win rate (observed 3 resolutions ago, expires in 27)
```

### Dynamic Feature Selection

The bot computes technical indicators controlled by `data/feature_config.json`. Reflection can enable, disable, or tune these indicators based on observed correlation with wins/losses.

**Available indicators (24 total):**

| Indicator | Category | What it measures |
|-----------|----------|------------------|
| `token_momentum` | Token | Rate of change over window |
| `token_volatility` | Token | Standard deviation over window |
| `token_ma_crossover` | Token | Short vs long SMA crossover |
| `token_mean_reversion` | Token | Z-score from mean (overextension) |
| `orderbook_imbalance` | Orderbook | Bid/ask depth ratio |
| `spread_trend` | Orderbook | Spread level classification |
| `down_orderbook_imbalance` | Orderbook | Bid/ask depth ratio for DOWN token |
| `cross_book_flow` | Orderbook | UP vs DOWN depth comparison for informed flow detection |
| `best_entry_analysis` | Orderbook | Compares UP/DOWN ask prices and risk/reward ratios |
| `token_price_divergence` | Orderbook | Up + Down midpoint deviation from $1 |
| `btc_momentum` | BTC | BTC spot price rate of change |
| `btc_volatility` | BTC | BTC spot price standard deviation |
| `btc_candle_momentum` | BTC Candle | Up/down ratio of last N 5-min candles |
| `btc_candle_ma_cross` | BTC Candle | MA5 vs MA12 crossover on 5-min candle closes |
| `consecutive_streak` | BTC Candle | Count of consecutive same-direction candles with mean reversion signal |
| `streak_magnitude` | BTC Candle | Total $ move during candle streak with exhaustion detection |
| `btc_vs_candle_open` | BTC Candle | Where BTC is NOW vs current candle open (the key binary outcome signal) |
| `volatility_30m` | BTC Candle | Avg candle range + stdev for regime detection (trending vs choppy) |
| `volume_trend` | BTC Candle | Recent vs prior volume ratio for momentum confirmation |
| `flat_market_edge` | BTC Candle | Detects flat BTC conditions where UP wins by default |
| `chainlink_divergence` | Chainlink | Binance vs Chainlink price divergence (resolution risk) |
| `market_trend` | BTC Candle | EMA20/EMA50 regime detection with counter-trend size reduction |
| `session_streak` | Session | Current W/L record |
| `confidence_calibration` | Session | Avg confidence on wins vs losses |

**Default config** enables most indicators. The reflection system can enable, disable, or tune any indicator as it identifies useful patterns.

---

## How to Run

### 1. Install

```bash
git clone <repo-url> && cd polymarket-bot
pip install -e .

# With dev dependencies (for tests):
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` and set your Anthropic API key:
```
POLYBOT_AI_API_KEY=sk-ant-...
```

That's the only required setup. The bot auto-discovers the current BTC candle market via the Gamma API.

### 3. Run

```bash
python -m polybot
```

A live Rich dashboard will appear showing: current candle market, orderbook state, positions, portfolio value, last action, risk status, and resolution history.

### Optional: Custom config

```bash
python -m polybot path/to/custom-config.yaml
```

### Optional: Web dashboard

The bot writes `logs/dashboard_data.json` every cycle. Open the web dashboard in a browser:

```bash
# From the project root:
python -m http.server 8080
# Then open http://localhost:8080/dashboard/
```

The dashboard auto-refreshes every 30 seconds and shows: stats cards (win rate, PnL, open trade PnL, cash, portfolio value, AI cost, trading fees, avg confidence), current market with live countdown, BTC price with Chainlink on-chain price and divergence warning, positions, scrollable trade timeline with expandable reasoning, resolutions table, cumulative PnL chart, risk panel, intelligence panel (ML model status, confidence calibration curve, exit analysis stats), **adaptive entry panel** (live BTC threshold, max entry price, reversal rate, regime badge — CALM/MODERATE/CHOPPY), and **iteration history panel** (side-by-side comparison cards of all archived iterations with color-coded deltas). The sidebar includes an **Iterations** section listing all archived iterations — clicking one opens a **dedicated analysis page** with full-width PnL curve, **changes from previous iteration** (18 metrics compared side-by-side with color-coded delta badges), trade quality breakdown (entry price distribution, fill price, confidence, hold rate), resolution stats (avg BTC move, win/loss PnL, risk/reward ratio), calibration & intelligence (shadow accuracy, exit analysis, confidence calibration chart), AI observations (categorized learnings), session history table, and a scrollable per-candle resolutions detail table. Candle timelines include regime color bars, BTC move labels at endpoints, entry price labels on BUY dots, and win/loss row tinting. Cash and Portfolio metrics are scoped to the selected view — overview shows all-time values, while individual sessions show start-to-current deltas for that session. The full accounting formula is: `cash = initial_cash + resolution_pnl + open_trade_pnl - fees - ai_cost`.

### Optional: Plain mode (no terminal dashboard)

Set `dashboard_enabled: false` in `config/default.yaml` for structured log output instead of the live Rich terminal dashboard.

### Environment Variable Overrides

| Variable | Purpose | Default |
|----------|---------|---------|
| `POLYBOT_AI_API_KEY` | Anthropic API key | (required) |
| `POLYBOT_AI_MODEL` | Claude model ID | `claude-sonnet-4-5-20250929` |
| `POLYBOT_AGENT_DECISION_INTERVAL` | Seconds between cycles after first AI call | `60` |
| `POLYBOT_AGENT_FAST_POLL_INTERVAL` | Seconds between cycles before first AI call | `10` |
| `POLYBOT_AGENT_INITIAL_CASH` | Starting paper balance | `1000.0` |
| `POLYBOT_AGENT_MAX_CYCLES` | Stop after N cycles (0=unlimited) | `0` |
| `POLYBOT_AGENT_MIN_CONFIDENCE` | Minimum AI confidence to allow BUY | `0.55` |
| `POLYBOT_MARKET_CONDITION_ID` | Pin a specific market | auto-discovered |
| `POLYBOT_RISK_DAILY_LOSS_LIMIT_PCT` | Daily loss halt threshold | `0.10` |
| `POLYBOT_KNOWLEDGE_DIR` | Knowledge files directory | `data/knowledge` |
| `POLYBOT_ETHEREUM_RPC_URL` | Ethereum RPC for Chainlink reads | `https://ethereum.publicnode.com` |

---

## Where Are the Outputs

```
polymarket-bot/
├── logs/
│   ├── polybot.log                    # Application log (DEBUG to file, INFO to console)
│   ├── trades_20260218.jsonl          # One TradeRecord per cycle (daily rotation)
│   ├── resolutions_20260218.jsonl     # One ResolutionRecord per candle close
│   ├── dashboard_data.json            # Live dashboard state (updated each cycle)
│   ├── agent_state.json               # Persisted agent state (survives restarts)
│   ├── adaptive_entry.jsonl           # Adaptive entry tracker: rolling candle outcomes for threshold learning
│   └── polybot.db                     # SQLite analytics (per-second snapshots, decisions, candle outcomes)
│
├── data/
│   ├── feature_config.json            # Indicator settings (AI-managed)
│   ├── market_history.db              # Persistent market data (never deleted, accumulates across iterations)
│   └── knowledge/
│       ├── trading_patterns.md        # Human-curated: strategy & patterns (read-only)
│       ├── self_assessment.md         # Human-curated: known biases (read-only)
│       ├── observations.jsonl         # AI-written: structured observations (append-only, auto-expire)
│       └── session_history.md         # AI-written: rolling batch summaries
```

### Trade Logs (JSONL)

Each line in `trades_*.jsonl` is a full `TradeRecord` containing:
- Market state at decision time (bid/ask/mid/spread/depth, BTC price)
- AI decision (action, token side, order type, size, confidence, reasoning, latency)
- Execution result (fill price, slippage, fees)
- Post-trade portfolio state (shares, PnL, cash, total value)
- Risk flags (halted, blocked, reason)

### Resolution Logs (JSONL)

Each line in `resolutions_*.jsonl` records:
- Candle slug, condition ID, start/end timestamps
- BTC open and close prices
- Winner (up/down)
- PnL per token and total

### SQLite Analytics (`logs/polybot.db`)

Per-second market replay and decision analysis. Three tables:

| Table | Rows | Content |
|-------|------|---------|
| `candles` | 1 per 5-min candle | slug, BTC open/close, winner, resolution PnL |
| `snapshots` | ~300 per candle | Full UP+DOWN orderbook, R/R, BTC price, prefilter, streak, indicators JSON |
| `decisions` | 1-5 per candle | AI action, confidence, reasoning, fill, risk, portfolio state, indicators JSON |

Example queries:

```sql
-- Best entry point per candle vs what the bot actually got
SELECT c.slug, c.winner,
    MIN(CASE WHEN c.winner='up' THEN s.up_best_ask ELSE s.down_best_ask END) AS best_entry,
    (SELECT d.fill_price FROM decisions d WHERE d.candle_id=c.candle_id AND d.action='BUY' LIMIT 1) AS actual_entry
FROM candles c JOIN snapshots s ON s.candle_id = c.candle_id
WHERE c.winner IS NOT NULL GROUP BY c.candle_id;

-- Streak + R/R vs outcomes (strategy discovery)
SELECT c.winner, COUNT(DISTINCT c.candle_id) AS n,
    AVG(json_extract(s.indicators_json, '$.btc_vs_candle_open.value')) AS avg_btc_move
FROM snapshots s JOIN candles c ON c.candle_id = s.candle_id
WHERE c.winner IS NOT NULL AND s.streak >= 3 AND s.rr_up > 1.5
GROUP BY c.winner;
```

Storage: ~150KB/candle, ~42MB/day. WAL mode enables concurrent reads while the bot writes.

### Persistent Market History (`data/market_history.db`)

A separate SQLite database that accumulates **pure market data** across all iterations — never deleted by `polybot-archive`. While `logs/polybot.db` mixes market data with session-specific decisions and portfolio state (and gets archived/cleaned each iteration), market history stores only what happened in the market: candle outcomes and per-second orderbook snapshots.

| Table | Rows | Content |
|-------|------|---------|
| `market_candles` | 1 per 5-min candle | condition_id, slug, iteration label, BTC open/close, winner |
| `market_snapshots` | ~300 per candle | Full UP+DOWN orderbook (bid/ask/mid/spread/depth), R/R ratios, BTC price, BTC move from open, streak |

Each candle is tagged with an `iteration` label (e.g., `iter_003`) so you can track data provenance. The `UNIQUE(condition_id)` constraint prevents duplicates if the same candle is seen across restarts.

With 500+ candles accumulated, you can statistically validate every assumption in the codebase — momentum continuation rates, reversal frequencies, optimal entry timing — instead of guessing.

### Analysis Report

```bash
polybot-analyze              # reads logs/ by default
polybot-analyze /path/to/logs
```

Prints a Rich table with: Total Cycles, Total Trades, Win Rate, Total PnL, Sharpe Ratio, Max Drawdown, Avg Trade Size, Total Fees, Final Portfolio, Final Cash.

### Iteration Archive & Comparison

Archive a complete iteration snapshot before starting a fresh run:

```bash
polybot-archive                    # → archive/iter_001/, then clean working dirs
polybot-archive --name "baseline"  # → archive/baseline/, then clean
polybot-archive --no-clean         # archive without cleaning
```

Each archive contains all generated artifacts (trade logs, resolutions, SQLite DB, AI knowledge, feature config) plus a `summary.json` with key metrics: date range, candles, trades, win rate, PnL, fees, AI cost, net result, reflections count, and enabled indicators.

Compare performance across all archived iterations:

```bash
polybot-compare                    # Rich table of all iterations side-by-side
```

Shows label, date range, candles, trades, win rate, PnL, fees, AI cost, and net result with color-coded deltas from the previous iteration.

### Assumption Validation

Validate trading assumptions against accumulated market history data:

```bash
polybot-validate                        # All reports
polybot-validate --report momentum      # Specific report
polybot-validate --report reversals     # Reversal rates
polybot-validate --report entry         # Optimal entry timing
polybot-validate --report distribution  # BTC move distribution
polybot-validate --min-candles 50       # Require 50+ samples for full confidence
```

**Reports:**

| Report | What it shows |
|--------|--------------|
| `summary` | Total candles, date range, iterations, UP/DOWN win split, avg BTC move, data quality |
| `momentum` | For each move × time bucket: % where mid-candle BTC direction = final winner |
| `reversals` | Same data inverted: % where mid-candle direction ≠ final winner |
| `entry` | Average best ask price for the winning side at each time-remaining bucket |
| `distribution` | Percentiles (10th–95th) of absolute BTC moves at candle close |

Requires `data/market_history.db` — accumulated automatically by the bot across iterations. Low-sample cells are dimmed; cells below `--min-candles` threshold are flagged.

---

## How Iterations Work

The bot improves through two mechanisms that compound over time:

### Knowledge Accumulation (every 10 resolutions)

```
Resolution 1-10:  Bot trades, outcomes accumulate
Resolution 10:    Claude reflection runs
                   → Sees scorecard: current batch vs previous (win rate, PnL, hold rate)
                   → Produces 1-5 descriptive observations → appended to observations.jsonl
                   → Can expire old observations contradicted by new data
                   → Appends one-line summary to session_history.md

Resolution 11-20: Bot trades with base knowledge + active observations
Resolution 20:    Another reflection
                   → Scorecard shows delta from last batch
                   → Old observations expire naturally (after 30 resolutions)
                   → New observations replace them based on fresh data

... and so on
```

The knowledge system has three layers:
- **Base knowledge** (read-only) — `trading_patterns.md`, `self_assessment.md` — human-curated strategy and bias notes
- **Observations** (append-only with decay) — `observations.jsonl` — AI-written descriptive observations that expire after ~30 resolutions
- **Session history** — `session_history.md` — Rolling table of batch summaries (last 20)

### Feature Selection Tuning (alongside reflection)

During each reflection, Claude also reviews the indicator configuration:
- Sees which indicators were active during wins vs losses
- Can enable up to 2 new indicators or disable noisy ones
- Can adjust parameters (e.g., change momentum window from 10 to 15)

This means the *input data* to decisions evolves over time, not just the decision-making knowledge.

### Iteration Timeline

| Resolutions | What Happens |
|-------------|--------------|
| 0 | Bot starts with base knowledge + indicators, no observations yet |
| 1-9 | Trading with base knowledge, accumulating outcomes |
| 10 | First reflection — scorecard computed, 1-5 observations created, indicator tuning |
| 11-19 | Trading with base knowledge + active observations as contextual hints |
| 20 | Second reflection — scorecard shows delta vs batch 1, old observations may expire |
| 30+ | Observations from batch 1 naturally expire; knowledge is always fresh |

---

## How to Improve It

### Tune the configuration

The most direct levers are in `config/default.yaml`:

- **`monitor.ai_cooldown_seconds`** — Minimum time between AI calls (default 60s). Lower = more responsive but higher API costs
- **`monitor.rr_trigger_threshold`** — R/R ratio needed to trigger AI when adaptive entry is disabled (default 1.0, entry <= $0.50)
- **`monitor.adaptive_entry_enabled`** — Use adaptive BTC threshold + max entry price learned from rolling candle history (default true)
- **`monitor.adaptive_entry_window`** — Number of candles in the rolling window for adaptive stats (default 5)
- **`monitor.stop_loss_pct`** / **`monitor.take_profit_pct`** — Position exit thresholds (default -60%/+80%)
- **`initial_cash`** — Affects position sizing through risk percentages
- **`temperature`** — Currently 0.0 (deterministic); slight increase (0.1-0.3) may help exploration
- **`risk.max_position_pct`** — Increase for more aggressive sizing, decrease for safety
- **`risk.daily_loss_limit_pct`** — Tighter stop-loss or wider runway
- **`risk.min_reward_risk_ratio`** — Minimum risk/reward ratio (kept for reference). No hard block — position size scales with R/R quality: 100% at R/R >= 2.0, 80% at 1.0, 55% at 0.5, 20% minimum

### Add new indicators

Create a new indicator function in `src/polybot/indicators.py`:

```python
@register("my_indicator")
def _my_indicator(
    snap: MarketSnapshot, params: dict, session: SessionContext | None,
) -> IndicatorResult | None:
    # Your logic here
    return IndicatorResult(name="My Indicator", value=0.5, label="0.50 (signal)")
```

Then add it to `data/feature_config.json`:
```json
{"name": "my_indicator", "enabled": true, "params": {}}
```

The reflection system will learn whether to keep it enabled.

### Improve the decision prompt

Edit `src/polybot/decision_engine/prompts.py`:
- `SYSTEM_PROMPT` — The instructions Claude follows for every decision
- `format_feature_vector()` — What data Claude sees each cycle

### Improve the reflection prompt

Edit `src/polybot/knowledge.py`:
- `REFLECTION_PROMPT` — Controls what Claude analyzes and what observations it produces
- Observations are append-only with automatic expiry — safe to experiment with

### Activate WebSocket support

The provider is already wired for WebSocket orderbook updates (`provider.update_from_ws()`). Build a WebSocket handler module that:
1. Connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market`
2. Subscribes to the current market's token IDs
3. Maintains a live orderbook from diffs
4. Calls `provider.update_from_ws(orderbook=..., last_price=...)` on each update

This would give sub-second market data instead of polling REST every 60s.

### Potential enhancements

- **Multi-timeframe analysis** — Feed indicators from both 5-min and longer timeframes
- **Ensemble decisions** — Run multiple Claude calls with different temperatures and aggregate
- **Backtesting** — Replay historical JSONL logs through the decision engine
- **SQLite query tooling** — The SQLite analytics store (`logs/polybot.db`) captures per-second snapshots, decisions, and candle outcomes. Build analysis scripts or a query UI on top of it
- **Dynamic SL/TP thresholds** — Currently stop-loss (-15%) and take-profit (+30%) are fixed; could adapt based on time remaining, volatility, or position size
- **Cross-candle learning** — Track BTC price patterns across multiple candles for longer-term trend detection

---

## Architecture

```
TradingAgent (agent.py) — orchestrator, launches 6 concurrent tasks
 │
 ├── SharedState (shared_state.py) — central coordination hub
 │   PreFilterSnapshot deque, asyncio.Event/Queue, position P&L, rotation flag
 │
 ├── MarketMonitor (tasks/market_monitor.py) — 1s loop
 │   MarketDataProvider → prefilter → PreFilterSnapshot → trigger AI
 │
 ├── AIDecision (tasks/ai_decision.py) — event-driven
 │   Waits on ai_trigger_event (entry) or exit_trigger_queue (SL/TP)
 │   → FeatureVector → indicators → ML → screen → Claude → execute
 │
 ├── PositionMonitor (tasks/position_monitor.py) — 1s loop
 │   Mark-to-market → P&L % → SL/TP check → exit_trigger_queue
 │
 ├── RotationLoop — 5s loop (in agent.py)
 │   MarketDiscovery → candle transition → resolution → reflection
 │
 ├── DashboardLoop — 2s loop (in agent.py)
 │   Writes dashboard JSON from shared state
 │
 ├── AdaptiveEntryTracker (adaptive_entry.py)
 │   Rolling reversal rate → adaptive BTC threshold ($20/$30/$40) + max entry price
 │   Persisted to logs/adaptive_entry.jsonl
 │
 ├── MarketDiscovery ─── Gamma API
 │   Finds current BTC 5-min candle market by slug pattern
 │
 ├── MarketDataProvider ─── CLOB REST + Chainlink + Binance 5m OHLCV + (WebSocket)
 │   Assembles MarketSnapshot: orderbooks, Chainlink BTC price, 5-min candle history
 │
 ├── RiskManager
 │   Pre-trade: daily halt, min liquidity
 │   Post-trade: spread, position size, concentration, cash, short-sell, depth
 │
 ├── FeatureConfig + Indicators
 │   Reads data/feature_config.json → runs enabled indicators → prompt text
 │
 ├── DecisionEngine ─── Claude API
 │   FeatureVector + feedback + indicators → structured JSON decision
 │
 ├── ExecutionSimulator
 │   Market orders: slippage model + 20bps fee → SimulatedFill
 │
 ├── SimulatedOrderBook
 │   Limit orders: TTL lifecycle, fill when price crosses limit
 │
 ├── Portfolio
 │   Dual Up/Down position tracking, mark-to-market, binary settlement
 │
 ├── ResolutionTracker
 │   BTC open/close comparison → winner determination
 │
 ├── KnowledgeManager ─── Claude API
 │   Base knowledge (.md, read-only) + observations (JSONL, append-only with decay)
 │   Every 10 resolutions: reflection → scorecard → observations + feature_config.json
 │
 ├── DataStore (datastore.py) — async task
 │   SQLite WAL mode, batched writes from asyncio.Queue
 │   candles + snapshots (1/sec) + decisions → logs/polybot.db
 │
 ├── MarketHistoryStore (datastore.py) — async task
 │   Persistent market data across iterations → data/market_history.db
 │   Pure market observables only (no decisions/portfolio)
 │
 ├── TradeLog
 │   JSONL daily-rotating: trades + resolutions
 │
 └── Web Dashboard (dashboard/index.html)
     Standalone HTML/CSS/JS — reads logs/dashboard_data.json, auto-refreshes
```

---

## Project Structure

```
polymarket-bot/
├── archive/                         # Iteration snapshots (gitignored)
│   └── iter_001/                    # Each archive preserves logs/, data/, summary.json
├── config/
│   └── default.yaml              # Primary configuration
├── dashboard/
│   └── index.html                # Standalone web dashboard (no build step)
├── data/
│   ├── feature_config.json       # AI-managed indicator config
│   └── knowledge/                # AI-written knowledge files
├── logs/                         # Trade logs, resolution logs, dashboard JSON, agent state
├── src/polybot/
│   ├── __main__.py               # Entry point
│   ├── agent.py                  # TradingAgent — orchestrator (launches 5 async tasks)
│   ├── shared_state.py           # SharedState + PreFilterSnapshot — task coordination
│   ├── adaptive_entry.py         # Adaptive entry thresholds from rolling candle history
│   ├── config.py                 # AppConfig + MonitorConfig + YAML + env loading
│   ├── datastore.py              # SQLite analytics — per-second snapshots + decisions + candles
│   ├── indicators.py             # Indicator registry + 13 built-in indicators
│   ├── knowledge.py              # KnowledgeManager + structured reflection + scorecard
│   ├── models.py                 # All Pydantic data models
│   ├── resolution.py             # Candle winner determination
│   ├── analysis/
│   │   ├── archive.py            # polybot-archive CLI — iteration snapshots
│   │   ├── compare.py            # polybot-compare CLI — cross-iteration comparison
│   │   ├── report.py             # polybot-analyze CLI
│   │   └── validate.py           # polybot-validate CLI — assumption validation against market history
│   ├── decision_engine/
│   │   ├── engine.py             # Claude API decision calls
│   │   ├── prompts.py            # System prompt + feature formatting
│   │   └── schemas.py            # JSON schema for structured output
│   ├── logging/
│   │   └── trade_log.py          # JSONL trade + resolution logging
│   ├── market_data/
│   │   ├── btc_price.py          # Chainlink on-chain (primary) + CoinGecko (24h) + Binance (candles)
│   │   ├── client.py             # Polymarket CLOB REST client
│   │   ├── discovery.py          # Gamma API market discovery
│   │   └── provider.py           # Unified MarketSnapshot facade
│   ├── risk/
│   │   └── manager.py            # Pre/post-trade risk checks
│   ├── simulator/
│   │   ├── engine.py             # Market order execution simulation
│   │   ├── orderbook.py          # Limit order lifecycle
│   │   └── portfolio.py          # Dual-position portfolio tracking
│   └── tasks/
│       ├── market_monitor.py     # 1s market data polling + prefilter + AI trigger
│       ├── ai_decision.py        # Event-driven AI decision pipeline
│       └── position_monitor.py   # Real-time P&L tracking + SL/TP exits
├── tests/                        # pytest + pytest-asyncio
├── .env.example                  # Environment variable template
└── pyproject.toml                # Package definition + dependencies
```

---

## License

This project is for educational and research purposes only. It does not place real trades.
