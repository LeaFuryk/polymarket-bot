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
| Logging | JSONL (daily-rotating trade + resolution logs) |
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

The bot runs a continuous loop of 5-minute cycles. Each cycle it discovers the current BTC candle market on Polymarket, gathers data (including 200 historical 5-min BTC candles for micro-trend analysis), asks Claude for a trading decision, simulates execution, and logs everything. Every 3 candle resolutions, Claude reflects on its performance and updates its own knowledge base and indicator configuration.

### The Self-Improving Loop

```
Decide ──► Trade ──► Resolve ──► Reflect ──► Adjust Inputs ──► Decide (better)
  │          │          │           │              │
  │          │          │           │              └─ Update data/feature_config.json
  │          │          │           │                 (enable/disable/tune indicators)
  │          │          │           │
  │          │          │           └─ Claude analyzes W/L patterns,
  │          │          │              writes data/knowledge/*.md files
  │          │          │
  │          │          └─ BTC candle closes → winner = up or down
  │          │             Winning token pays $1, loser pays $0
  │          │
  │          └─ Simulated execution with slippage + 20bps fees
  │
  └─ Claude reads: orderbook, BTC 5-min candle history, positions,
     risk state, computed indicators, past learnings → outputs JSON
```

### Decision Cycle (12 steps)

Each cycle (~60 seconds) the agent executes:

1. **Discover market** — Query Gamma API for the active BTC 5-min candle. Detect rotation to a new candle.
2. **Resolution buffer** — Skip trading if <10 seconds remain (too close to expiry).
3. **Fetch snapshot** — Up + Down orderbooks, BTC spot price, latest 5-min candle, last trade price.
4. **Mark-to-market** — Update unrealized PnL on both token positions.
5. **Check limit fills** — Scan pending limit orders against current orderbook.
6. **Pre-trade risk checks** — Daily loss halt, minimum liquidity. Run *before* Claude API call to save cost.
7. **Rules-based pre-filter** — Cheap checks (time remaining, choppy market, entry pricing, candle streaks) skip obvious HOLDs without calling Claude, saving 60-70% of AI costs.
8. **Build context** — Assemble FeatureVector + BTC candle history + feedback context + computed indicators.
9. **Claude decides** — Structured JSON: `action`, `token_side`, `order_type`, `size`, `confidence`, `reasoning`.
10. **Confidence gate** — Hard override: if confidence < 0.6, the trade is forced to HOLD regardless of Claude's recommendation.
10b. **Calibration gate** — Checks stated confidence against historical calibration data. If the actual win rate at that confidence level is below break-even (55%), the trade is overridden to HOLD.
11. **Post-trade risk checks** — Validate spread, position sizing, concentration, cash sufficiency.
12. **Execute + log** — Simulate fill, update portfolio, write TradeRecord to JSONL, write dashboard JSON.

### Market Rotation & Resolution

When a 5-minute candle expires and a new one begins:
- All pending limit orders are cancelled
- The old candle is resolved by comparing BTC price at open vs close (from Chainlink)
- Resolves "Up" if close >= open, "Down" otherwise (equal price = Up wins)
- Winning token positions settle at $1/share, losing at $0
- Session W/L stats are updated
- Portfolio positions reset for the new candle
- Every 3 resolutions → **reflection** is triggered
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

After every 3 candle resolutions, the bot calls Claude with:
- Recent resolution outcomes (W/L, BTC moves, PnL)
- Recent trade history (actions, confidence, fills)
- Current knowledge files
- Current indicator configuration

Claude produces:
- **trading_patterns.md** — Observed market behavior patterns
- **self_assessment.md** — Identified biases and recurring mistakes
- **session_history.md** — Rolling log of recent session batches
- **feature_config.json** (optional) — Updated indicator settings (at most 2 changes per reflection)

### Dynamic Feature Selection

The bot computes technical indicators controlled by `data/feature_config.json`. Reflection can enable, disable, or tune these indicators based on observed correlation with wins/losses.

**Available indicators (13 total):**

| Indicator | Category | What it measures |
|-----------|----------|------------------|
| `token_momentum` | Token | Rate of change over window |
| `token_volatility` | Token | Standard deviation over window |
| `token_ma_crossover` | Token | Short vs long SMA crossover |
| `token_mean_reversion` | Token | Z-score from mean (overextension) |
| `orderbook_imbalance` | Orderbook | Bid/ask depth ratio |
| `spread_trend` | Orderbook | Spread level classification |
| `token_price_divergence` | Orderbook | Up + Down midpoint deviation from $1 |
| `btc_momentum` | BTC | BTC spot price rate of change |
| `btc_volatility` | BTC | BTC spot price standard deviation |
| `btc_candle_momentum` | BTC Candle | Up/down ratio of last N 5-min candles |
| `btc_candle_ma_cross` | BTC Candle | MA5 vs MA12 crossover on 5-min candle closes |
| `session_streak` | Session | Current W/L record |
| `confidence_calibration` | Session | Avg confidence on wins vs losses |

**Default config** enables 6 indicators: `token_momentum`, `token_volatility`, `orderbook_imbalance`, `btc_momentum`, `btc_candle_momentum`, `btc_candle_ma_cross`. The reflection system enables/disables others as it identifies useful patterns.

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

The dashboard auto-refreshes every 60 seconds and shows: stats cards (win rate, PnL, open trade PnL, cash, portfolio value, AI cost, trading fees, avg confidence), current market with live countdown, BTC price, positions, scrollable trade timeline with expandable reasoning, resolutions table, cumulative PnL chart, and risk panel. Cash and Portfolio metrics are scoped to the selected view — overview shows all-time values, while individual sessions show start-to-current deltas for that session. The full accounting formula is: `cash = initial_cash + resolution_pnl + open_trade_pnl - fees - ai_cost`.

### Optional: Plain mode (no terminal dashboard)

Set `dashboard_enabled: false` in `config/default.yaml` for structured log output instead of the live Rich terminal dashboard.

### Environment Variable Overrides

| Variable | Purpose | Default |
|----------|---------|---------|
| `POLYBOT_AI_API_KEY` | Anthropic API key | (required) |
| `POLYBOT_AI_MODEL` | Claude model ID | `claude-sonnet-4-5-20250929` |
| `POLYBOT_AGENT_DECISION_INTERVAL` | Seconds between cycles | `60` |
| `POLYBOT_AGENT_INITIAL_CASH` | Starting paper balance | `10000.0` |
| `POLYBOT_AGENT_MAX_CYCLES` | Stop after N cycles (0=unlimited) | `0` |
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
│   └── agent_state.json               # Persisted agent state (survives restarts)
│
├── data/
│   ├── feature_config.json            # Indicator settings (AI-managed)
│   └── knowledge/
│       ├── trading_patterns.md        # AI-written: market behavior observations
│       ├── self_assessment.md         # AI-written: bias and mistake analysis
│       └── session_history.md         # AI-written: rolling session summaries
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

### Analysis Report

```bash
polybot-analyze              # reads logs/ by default
polybot-analyze /path/to/logs
```

Prints a Rich table with: Total Cycles, Total Trades, Win Rate, Total PnL, Sharpe Ratio, Max Drawdown, Avg Trade Size, Total Fees, Final Portfolio, Final Cash.

---

## How Iterations Work

The bot improves through two mechanisms that compound over time:

### Knowledge Accumulation (every 3 resolutions)

```
Resolution 1-3: Bot trades, outcomes accumulate
Resolution 3:   Claude reflection runs
                 → Analyzes what worked/failed
                 → Writes updated .md knowledge files
                 → These files are injected into every future decision prompt

Resolution 4-6: Bot trades with updated knowledge
Resolution 6:   Another reflection
                 → Builds on previous knowledge
                 → Identifies new patterns or corrects old ones

... and so on
```

The knowledge files are concise (< 100 lines each) and contain:
- **Trading patterns** — "BTC momentum tends to persist within a candle", "wide spreads correlate with losses"
- **Self assessment** — "Overconfident on down bets", "tends to trade too late in the candle"
- **Session history** — Rolling table of recent batch outcomes

### Feature Selection Tuning (alongside reflection)

During each reflection, Claude also reviews the indicator configuration:
- Sees which indicators were active during wins vs losses
- Can enable up to 2 new indicators or disable noisy ones
- Can adjust parameters (e.g., change momentum window from 10 to 15)

This means the *input data* to decisions evolves over time, not just the decision-making knowledge.

### Iteration Timeline

| Resolutions | What Happens |
|-------------|--------------|
| 0 | Bot starts with 6 default indicators + seeded knowledge (known biases, patterns) |
| 1-2 | Trading with BTC candle analysis, accumulating outcomes |
| 3 | First reflection — initial patterns identified, first possible indicator change |
| 4-6 | Trading with first knowledge layer + possibly updated indicators |
| 6 | Second reflection — patterns refined, more indicator tuning |
| 9+ | Knowledge compounds; indicator selection stabilized to what works |

---

## How to Improve It

### Tune the configuration

The most direct levers are in `config/default.yaml`:

- **`decision_interval`** — Shorter intervals (e.g., 30s) give more data points per candle but cost more API calls
- **`initial_cash`** — Affects position sizing through risk percentages
- **`temperature`** — Currently 0.0 (deterministic); slight increase (0.1-0.3) may help exploration
- **`risk.max_position_pct`** — Increase for more aggressive sizing, decrease for safety
- **`risk.daily_loss_limit_pct`** — Tighter stop-loss or wider runway

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
- `REFLECTION_PROMPT` — Controls what Claude analyzes and what files it produces
- Add new knowledge file categories if needed

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
- **SQLite storage** — The config field `sqlite_enabled` exists but isn't wired yet; implement for queryable trade history
- **Position management within candle** — Currently the bot can enter and exit mid-candle; add explicit take-profit / stop-loss logic
- **Cross-candle learning** — Track BTC price patterns across multiple candles for longer-term trend detection

---

## Architecture

```
TradingAgent (agent.py) — main orchestration loop
 │
 ├── MarketDiscovery ─── Gamma API
 │   Finds current BTC 5-min candle market by slug pattern
 │
 ├── MarketDataProvider ─── CLOB REST + Chainlink + Binance 5m OHLCV + (WebSocket)
 │   Assembles MarketSnapshot: orderbooks, Chainlink BTC price, 5-min candle history
 │
 ├── RiskManager
 │   Pre-trade: daily halt, min liquidity
 │   Post-trade: spread, position size, concentration, cash, short-sell
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
 │   Loads .md knowledge files for decisions
 │   Every 3 resolutions: reflection → updated .md + feature_config.json
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
│   ├── agent.py                  # TradingAgent — main loop
│   ├── config.py                 # AppConfig + YAML + env loading
│   ├── indicators.py             # Indicator registry + 13 built-in indicators
│   ├── knowledge.py              # KnowledgeManager + reflection
│   ├── models.py                 # All Pydantic data models
│   ├── resolution.py             # Candle winner determination
│   ├── analysis/
│   │   └── report.py             # polybot-analyze CLI
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
│   └── simulator/
│       ├── engine.py             # Market order execution simulation
│       ├── orderbook.py          # Limit order lifecycle
│       └── portfolio.py          # Dual-position portfolio tracking
├── tests/                        # pytest + pytest-asyncio
├── .env.example                  # Environment variable template
└── pyproject.toml                # Package definition + dependencies
```

---

## License

This project is for educational and research purposes only. It does not place real trades.
