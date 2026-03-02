# Polymarket BTC Candle Bot

An AI-powered trading agent that trades Polymarket BTC 5-minute candle prediction markets using Claude as its decision engine. The bot features a self-improving feedback loop where Claude reflects on past outcomes, updates its own knowledge base, and tunes the indicators fed into future decisions.

**Two modes**: paper trading (default, simulated execution) or live trading (real CLOB orders via py-clob-client with shadow paper comparison). In paper mode, no real money is at risk. In live mode, GTC limit orders are placed at the AI's evaluated price with a 3-second TTL — if unfilled, the order is cancelled (you never pay more than the AI evaluated). Three-layer fill detection (status polling + `size_matched` + balance-based stealth fill detection) handles the CLOB API's async status propagation delay. 9 layers of safety (kill switch, order caps, limit order TTL, dry run).

---

## Technology

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| AI Brain | Claude (Anthropic API) with structured JSON output |
| Market Data | Chainlink RTDS WebSocket (primary price + 5-min candle builder), Binance BTC/USDT spot (fallback), CoinGecko (24h change), Binance 5-min OHLCV (startup backfill) |
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
| `websockets` | Chainlink RTDS WebSocket for real-time resolution-source BTC price |
| `python-dotenv` | `.env` secret management |

### External APIs

| API | Auth | Purpose |
|-----|------|---------|
| Polymarket CLOB | None (public) | Orderbooks, last trade prices |
| Polymarket Gamma | None | Market discovery by slug pattern |
| Polymarket RTDS WebSocket | None (public) | **Primary BTC price** — Chainlink Data Streams price used for resolution |
| Chainlink BTC/USD (on-chain) | None (public RPC) | Cross-reference BTC price (fallback when WebSocket inactive) |
| CoinGecko | None | 24h change % (convenience metric only) |
| Binance klines | None | 5-min OHLCV candle startup backfill (~200 candles); replaced by Chainlink WS candles as they accumulate |
| Ethereum RPC | None | Read Chainlink price feed aggregator contract |

---

## How It Works

The bot runs 6 concurrent async tasks in the same event loop. The MarketMonitor fetches data every second, runs prefilter checks, and triggers the AI when conditions are favorable. The AIDecision task waits for triggers and runs the full decision pipeline. The PositionMonitor tracks open positions every second and triggers exits at stop-loss/take-profit thresholds. Every 10 candle resolutions, Claude reflects on its performance using a quantitative scorecard and produces structured observations that feed into future decisions.

### The Self-Improving Loop

```
Monitor ──► Trigger AI ──► Trade ──► Monitor P&L ──► SL/TP Exit
  │              │           │           │              │
  │              │           │           │              └─ PositionMonitor detects -60%/+80%
  │              │           │           │                 → triggers exit via AIDecision queue
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
2. **Run prefilter** — Skips AI when positioned (exits handled by PositionMonitor). For entries: checks time remaining, spread width, book depth, choppy market, entry setup
3. **Record PreFilterSnapshot** — Per-second market state stored in a 300-entry deque (~5 min history)
4. **Compute R/R** — Calculate risk/reward ratio for both UP and DOWN tokens
5. **Trigger AI** — Uses adaptive entry thresholds (learned from rolling candle history) to decide when to call AI. The `AdaptiveEntryTracker` computes a fakeout-based BTC move threshold ($20–$100) from the last 5 candles' actual BTC trajectories: for each candle, it measures how far BTC moved in the *wrong direction* (peak move opposite to eventual winner) from per-second prefilter snapshots. The threshold is set to P50 (median) of fakeout magnitudes (5-candle window), clamped to [$20, adaptive_cap] where the adaptive cap = max($50, min($100, P75 * 1.2)) — so in calm markets the cap stays at $50 (unchanged behavior), but in wild markets with large fakeouts the cap rises up to $100, letting the threshold protect against genuine noise. Volatile outliers age out in ~25 min. When fakeout max exceeds 1.5x the threshold, a HIGH-VOLATILITY MARKET advisory warns the AI to wait for sustained confirmation. Reversal rate and signal type still use the full window (10 candles) for smoothness. All entries must pass this threshold — no bypasses. Falls back to a V-shaped reversal-rate formula when peak data is unavailable (old records). When reversal rate is 40–60% (UNCERTAIN) and BTC hasn't cleared the fakeout threshold, the AI is told to buy the cheapest side instead of guessing direction — at coin-flip accuracy, only cheap entries are profitable. When BTC has moved past the fakeout threshold, the UNCERTAIN message switches to favor momentum — the move has cleared typical noise and contrarian bets are fighting real signal. When reversal rate >55%, the AI receives a contrarian context with the actual rate and average winner ask, letting it decide to bet against the initial BTC direction. **Reversal detection** uses a retracement-based algorithm: (1) if BTC crosses the fakeout threshold in the initial direction, momentum is confirmed; (2) if BTC retraces 80%+ of its peak commitment with accelerating retreat or crosses zero, that's a reversal; (3) otherwise inconclusive (not enough commitment to judge). This replaces the old threshold-crossing first-cross check which measured noise, not commitment. On startup, bootstraps from Binance 1-min klines (using the same retracement logic adapted for 1-min closes) if history is insufficient. Falls back to static R/R threshold when adaptive is disabled. AI cooldown (60s) still applies

### AIDecision (event-driven)

Waits for entry triggers (from MarketMonitor) or exit triggers (from PositionMonitor):

1. **Pre-trade risk checks** — Daily loss halt, minimum liquidity
2. **Build context** — Compact FeatureVector + BTC candle history + feedback context + computed indicators + ML prediction (with top 3 feature drivers) + BTC trajectory (velocity/peak-drawback) + cross-candle microstructure (spread/volatility trends) + entry timing performance (WR by time-remaining bucket from resolved session trades) + soft safeguard warnings (Chainlink divergence >$100, post-stop-loss cooldown, counter-trend advisory, session drawdown alert, per-side failure patterns, calibration overconfidence). Ensemble disagreement (ML vs AI direction) is tracked
3. **Two-pass screening** — Haiku screens first (entry only, not exits). Screening reason is passed to Sonnet as a "Pre-Screening Note". Pass-through rate tracked for tuning
4. **Claude decides** — Full Sonnet decision with structured JSON output
5. **Confidence gate** — Override BUY to HOLD if confidence < 0.55
6. **Calibration gate** — Override BUY to HOLD if calibrated win rate < break-even (with overconfidence warnings per bin)
7. **Anti-hedge guard** — Blocks BUY if opposite side has shares. During **reversal flip**, auto-closes the held position instead of blocking, so the BUY proceeds as a flip
7b. **Anti-flip guard** — Blocks buying the opposite side after a SELL on the same candle (prevents whipsaw). Same-side re-entry allowed. Bypassed during **post-SL contrarian flip** (see below)
7c. **Single-entry-per-side** — Blocks buying the same side twice on the same candle (code-enforced position discipline)
7d. **Entry price cap** — Blocks BUY when best ask >= $0.85 (R/R < 0.18, negative avg PnL in backtesting)
8. **Sell size clamp** — Clamps sell size to actual held shares (fixes rounding from fractional position sizing)
9. **Position sizing** — Gentle R/R scale (0.75x-1.0x, since data shows cheap entries are often contrarian traps). Multiplied by BTC move magnitude scaling (80%/90%/100%) and counter-trend reduction (50-70%). Minimum 40 shares (20 for counter-trend)
10. **Post-trade risk checks** — Position size, concentration, cash, spread (BUY only)
11. **Execute + log** — Simulate fill, update portfolio, write TradeRecord
12. **Contrarian flip** — After any exit (stop-loss or reversal retracement), if the position was closed and BTC confirms the reversal (time >= 60s, BTC moving against the exited side), triggers a second AI decision for the opposite side. The anti-flip guard is bypassed for this entry only. No price gate — the AI sees the full context and decides BUY or HOLD

### PositionMonitor (every 1 second)

1. **Mark-to-market** — Update position values using cached snapshot
2. **Compute P&L %** — For each open position (UP and DOWN independently)
3. **Adaptive dynamic stop-loss** — Computed per-position from 5 factors: (1) time weighting (-60% at 240s to -20% at 0s), (2) regime from reversal rate (momentum tightens, choppy widens), (3) BTC velocity (against position tightens, favors widens), (4) ML alignment at entry (agreed widens, disagreed tightens), (5) entry price quality (expensive tightens +6%, cheap ≤$0.40 widens -10%, very cheap ≤$0.30 widens -15%). Bounded by configurable floor/ceiling (-75% to -15%)
4. **Adaptive dynamic take-profit** — Time-weighted base with 3 adjustments: regime (momentum lets winners run, choppy takes profits), BTC velocity, entry price quality. Bounded (+20% to +120%)
5. **Reversal retracement detection** — When BTC retraces 80%+ from its peak move back toward candle open (minimum $25 peak, after 30s minimum hold time), triggers a **single AI call**: AI decides **HOLD** (keep position, SL stays active) or **BUY opposite** (auto-close current position + flip to other side via `_auto_close_for_flip`, which logs the SELL to the trade JSONL). The prompt includes rich retracement analytics computed from per-second prefilter history: peak move + age, retracement %, zero crossing, retreat velocity/acceleration, and opposite-side R/R. Fires once per position
6. **Trigger exit** — Push exit signal to AIDecision with reason, P&L, and dynamic threshold (respects AI cooldown; emergencies ≤-30% bypass)
7. **Fallback** — When `dynamic_sl_enabled: false`, uses existing time-weighted-only logic

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

### Outage Detection & Recovery

The bot monitors Polymarket Gamma API availability and handles outages gracefully:
- **Detection**: 3+ consecutive market discovery failures trigger outage state
- **During outage**: Trading paused, structured warnings logged every 60s with duration, dashboard shows red outage banner with elapsed time
- **Recovery**: When markets return, missed candles are skipped (no stale resolution), pre-outage orders cancelled, clean restart with next live market
- **Dashboard**: Real-time outage/recovery banners with duration tracking

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

After every 10 candle resolutions, the bot calls Claude with a **quantitative scorecard** (current batch vs previous batch: win rate, avg PnL, avg win/loss size, hold rate) plus resolution/trade tables and active observations. This creates a real feedback loop where reflection can see if its changes helped. The trades table includes **opposite-side context** (the other side's ask price and signal type) so reflection can identify "wrong side" mistakes — e.g., buying UP at $0.68 when DOWN was $0.31 in an UNCERTAIN market. A **Side Selection Analysis** section flags these expensive-side trades with outcomes, and the real-time feedback table shows the same context so Claude can self-correct within a session.

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

The dashboard auto-refreshes every 30 seconds and shows a **deep analysis section** on iterations with analysis data (profit factor, loss classifications, entry price ROI, confidence calibration, weird loss investigations, ranked actionable fixes), plus stats cards (win rate, PnL, open trade PnL, cash, portfolio value, AI cost, trading fees, avg confidence), current market with live countdown, BTC price with Chainlink on-chain price and divergence warning, positions with **dynamic SL/TP thresholds**, scrollable trade timeline with expandable reasoning, resolutions table, **interactive cumulative PnL chart with hover tooltips and crosshair**, risk panel, intelligence panel (ML model status, confidence calibration curve, exit analysis stats), **adaptive entry panel** (live BTC threshold, max entry price, reversal rate, regime badge — CALM/MODERATE/CHOPPY), and **iteration history panel** (side-by-side comparison cards of all archived iterations with color-coded deltas). The sidebar includes an **Iterations** section listing all archived iterations — clicking one opens a **dedicated analysis page** with full-width interactive PnL curve (gridlines, gradient fill, win/loss colored dots, hover tooltips), **changes from previous iteration** (18 metrics compared side-by-side with color-coded delta badges), **consolidated Performance Statistics panel** (dense multi-column grid combining trade quality, resolution stats, calibration/intelligence, and account state in a single full-width section), entry price distribution bar, confidence calibration bins, **active indicators panel**, AI observations (categorized learnings), session history table, and a scrollable per-candle resolutions detail table. Candle timelines include regime color bars, **interactive prefilter ticks** (green=passed, gray=failed, amber=cheap entry rejected — hover for popover showing entry prices, R/R, BTC move, spread, depth, streak, and rejection reason), **AI model badges** (H=Haiku, S=Sonnet, P=prefilter skip), **winner price heatmap** (green→red gradient showing cheap→expensive entry windows), BTC move labels at endpoints, entry price labels on BUY dots, and win/loss row tinting. Each trade dot expands to show model info (Haiku/Sonnet/prefilter) and a **collapsible Input Data section** with BTC price, orderbook state, portfolio, and AI cost at decision time. The iteration layout uses **tight spacing** and **dense stat grids** for maximum information density, backed by **per-candle snapshot timelines** (downsampled every ~10s from SQLite) surfaced in both live and archived dashboard JSON. Cash and Portfolio metrics are scoped to the selected view — overview shows all-time values, while individual sessions show start-to-current deltas for that session. The full accounting formula is: `cash = initial_cash + resolution_pnl + open_trade_pnl - fees - ai_cost`.

### Optional: Plain mode (no terminal dashboard)

Set `dashboard_enabled: false` in `config/default.yaml` for structured log output instead of the live Rich terminal dashboard.

### Live Trading

The bot supports real money trading on Polymarket via CLOB API. **Default is paper mode** — live trading must be explicitly enabled.

#### 1. Generate API credentials

Export your Polygon wallet private key from MetaMask, add it to `.env`:
```
POLYBOT_TRADING_PRIVATE_KEY=0x...
```

Then generate CLOB API credentials:
```bash
uv run python scripts/generate_api_key.py
```

This prints `POLYBOT_TRADING_API_KEY`, `POLYBOT_TRADING_API_SECRET`, and `POLYBOT_TRADING_API_PASSPHRASE` — add them to `.env`.

#### 1b. Set your proxy wallet address

Go to **polymarket.com → Profile → Settings** and copy the **Address** field. Add it to `.env`:
```
POLYBOT_TRADING_PROXY_WALLET_ADDRESS=0x...
```

This is the Polymarket proxy wallet (Gnosis Safe) that holds your USDC. The bot signs orders with your private key but sets this address as the `maker` (funder) in signed orders.

#### 2. Test with dry run

Set live mode with dry run enabled — orders are signed but not posted:
```
POLYBOT_TRADING_MODE=live
POLYBOT_TRADING_DRY_RUN=true
```

Run the bot and verify: auth works, balance syncs, orders are signed, fills flow through correctly. Check logs for `DRY RUN:` messages.

#### 3. Go live

```
POLYBOT_TRADING_MODE=live
POLYBOT_TRADING_DRY_RUN=false
```

**Recommended first session**: watch the entire session, ready to Ctrl+C. The safety defaults are conservative:
- Max order size: $50 per trade
- Kill switch: shuts down if session loss exceeds $40
- Min wallet balance: refuses BUY below $5 USDC
- GTC limit orders at AI's evaluated price with 3s TTL (never pays more than evaluated)
- Three-layer fill detection: status polling, `size_matched` field, balance-based stealth fill detection
- Full execution telemetry: orderbook snapshots at submit/fill/cancel, poll progression, fill source, balance diffs
- Unfilled orders auto-cancelled after timeout — no stuck orders

#### 4. Shadow comparison

In live mode, every trade is also simulated on a shadow paper portfolio. The dashboard shows:
- **Shadow PnL** — what the paper simulator would have made on the same trades
- **Exec Cost** — difference between live PnL and shadow PnL (slippage + real fees vs simulated)
- Per-trade: live fill price vs paper fill price with price difference %
- Trade logs include `paper_fill_price` and `paper_total_cost` fields

This gives hard data on how much real CLOB execution costs vs simulation.

#### Safety layers

| Layer | What | Where |
|-------|------|-------|
| 1 | Config default `mode: paper` | config.py |
| 2 | Dry run mode (sign, don't post) | LiveExecutionEngine |
| 3 | Max order size ($50 hard cap) | LiveExecutionEngine.execute() |
| 4 | Min wallet balance check | LiveExecutionEngine.execute() |
| 5 | Session kill switch ($40 loss) | _balance_sync_loop() |
| 6 | GTC limit order with 3s TTL (price-safe) | LiveExecutionEngine._submit_limit_order() |
| 7 | Existing risk manager | RiskManager (unchanged) |
| 8 | Auto-cancel unfilled orders | LiveExecutionEngine._submit_limit_order() |
| 9 | Startup credential + balance validation | agent.py |

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
| `POLYBOT_TRADING_MODE` | Trading mode: `paper` or `live` | `paper` |
| `POLYBOT_TRADING_PRIVATE_KEY` | Polygon wallet private key | (required for live) |
| `POLYBOT_TRADING_API_KEY` | CLOB API key | (required for live) |
| `POLYBOT_TRADING_API_SECRET` | CLOB API secret | (required for live) |
| `POLYBOT_TRADING_API_PASSPHRASE` | CLOB API passphrase | (required for live) |
| `POLYBOT_TRADING_PROXY_WALLET_ADDRESS` | Polymarket proxy wallet (from Profile Settings) | (required for live) |
| `POLYBOT_TRADING_DRY_RUN` | Sign orders but don't post | `false` |
| `POLYBOT_TRADING_MAX_ORDER_SIZE_USD` | Hard cap per order | `50.0` |
| `POLYBOT_TRADING_MAX_SESSION_LOSS_USD` | Kill switch threshold | `40.0` |

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

A comprehensive statistical analysis (340+ candles across 9 iterations) found: BTC moves >$50 have ~65-70% directional accuracy (originally estimated at ~90% from a smaller sample, corrected after iter_008's 128 candles showed at least 10 losses on $50+ moves); two EV peaks at 30-45s and 120-165s; cheap entries (R/R 1.5-3.0) are often contrarian traps; and streaks of 3+ continue ~62% of the time. Findings are loaded into `data/knowledge/trading_patterns.md` as soft guidance for the AI.

### Analysis Report

```bash
polybot-analyze              # reads logs/ by default
polybot-analyze /path/to/logs
```

Prints a Rich table with: Total Cycles, Total Trades, Win Rate, Total PnL, Sharpe Ratio, Max Drawdown, Avg Trade Size, Total Fees, Final Portfolio, Final Cash. If `logs/polybot.db` exists, appends an aggregate **Candle Replay Summary** (fill rates, entry gaps, post-cancel recovery, side accuracy).

### Iteration Archive & Comparison

Archive a complete iteration snapshot before starting a fresh run:

```bash
polybot-archive                    # → archive/iter_001/, then clean working dirs
polybot-archive --name "baseline"  # → archive/baseline/, then clean
polybot-archive --no-clean         # archive without cleaning
```

Each archive contains all generated artifacts (trade logs, resolutions, SQLite DB, AI knowledge, feature config) plus a `summary.json` with key metrics: bot version, date range, candles, trades, win rate, PnL, fees, AI cost, net result, reflections count, enabled indicators, and aggregate replay stats (fill rates, entry gaps, recovery rate, side accuracy).

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

### Candle Replay

Deterministically replay any candle's per-second orderbook timeline to analyze fill opportunities, entry timing, and order execution quality:

```bash
polybot-replay --slug btc-updown-5m           # Latest candle matching slug
polybot-replay --slug btc-updown-5m --all     # All candles for slug
polybot-replay --slug btc-updown-5m --candle-id 15
polybot-replay --slug btc-updown-5m --ttl 5   # Counterfactual: what if TTL was 5s?
polybot-replay --slug btc-updown-5m --limit-price 0.45  # Fixed limit price scan
```

**Report sections:**

| Section | What it shows |
|---------|--------------|
| Header | Candle ID, slug, traded side, duration, winner outcome, BTC open/close |
| Orderbook Summary | Min/max/mean/stdev for best_bid, best_ask, mid, spread, BTC price |
| Decision Timeline | Each AI decision with confidence, fill price, book state at decision time |
| Fillability Scan | For each second, simulates a limit order at best_ask — reports fillable seconds, fill rate, best/worst entry, delay distribution |
| Post-Cancel Recovery | For missed orders: 30s price trajectory after cancel, did price return to fillable range? |
| Live Order Telemetry | Overlays v0.15.0 `live_order_json`: order lifecycle, polls, decision-to-submit ask drift |
| Key Insights | Auto-generated: best entry vs actual fill, TTL counterfactuals, recovery analysis |

Reads from `logs/polybot.db` (per-session data with decisions). Use `--db` to point at a different database.

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
- **`monitor.adaptive_entry_window`** — Number of candles in the rolling window for adaptive stats (default 10)
- **`monitor.stop_loss_pct`** / **`monitor.take_profit_pct`** — Base position exit thresholds (default -60%/+80%). When dynamic SL/TP is enabled, these serve as the starting point for adaptive computation
- **`monitor.dynamic_sl_enabled`** / **`monitor.dynamic_tp_enabled`** — Enable adaptive SL/TP using regime, velocity, ML, and entry price factors (default true)
- **`monitor.sl_floor`** / **`monitor.sl_ceiling`** — Bounds for dynamic stop-loss (default -75% / -15%)
- **`monitor.tp_floor`** / **`monitor.tp_ceiling`** — Bounds for dynamic take-profit (default +20% / +120%)
- **`initial_cash`** — Affects position sizing through risk percentages
- **`temperature`** — Currently 0.0 (deterministic); slight increase (0.1-0.3) may help exploration
- **`risk.max_position_pct`** — Increase for more aggressive sizing, decrease for safety
- **`risk.daily_loss_limit_pct`** — Tighter stop-loss or wider runway
- **`risk.min_reward_risk_ratio`** — Minimum risk/reward ratio (kept for reference). No hard block — gentle R/R scale: 100% at R/R >= 1.0, 75% minimum (data shows cheap entries are often contrarian traps with low win rates)

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

### Activate WebSocket orderbook support

The provider is already wired for WebSocket orderbook updates (`provider.update_from_ws()`). Build a WebSocket handler module that:
1. Connects to `wss://ws-subscriptions-clob.polymarket.com/ws/market`
2. Subscribes to the current market's token IDs
3. Maintains a live orderbook from diffs
4. Calls `provider.update_from_ws(orderbook=..., last_price=...)` on each update

This would give sub-second orderbook data instead of polling REST every 60s. (Note: BTC price WebSocket is already active via `ChainlinkWSFeed`.)

### Potential enhancements

- **Multi-timeframe analysis** — Feed indicators from both 5-min and longer timeframes
- **Ensemble decisions** — Run multiple Claude calls with different temperatures and aggregate
- **Backtesting** — Replay historical JSONL logs through the decision engine
- **SQLite query tooling** — The SQLite analytics store (`logs/polybot.db`) captures per-second snapshots, decisions, and candle outcomes. Build analysis scripts or a query UI on top of it
- **Dynamic SL/TP thresholds** — Implemented in v0.5.2: adaptive stop-loss and take-profit computed every second from 5 factors (time, regime, BTC velocity, ML alignment, entry price)
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
 │   Fakeout-based BTC threshold ($20–$100) from per-candle peak wrong-direction moves
 │   Persisted to logs/adaptive_entry.jsonl
 │
 ├── MarketDiscovery ─── Gamma API
 │   Finds current BTC 5-min candle market by slug pattern
 │
 ├── ChainlinkWSFeed ─── Polymarket RTDS WebSocket
 │   Real-time Chainlink BTC/USD (primary price — matches resolution source)
 │
 ├── MarketDataProvider ─── CLOB REST + Chainlink WS + Binance 5m OHLCV
 │   Assembles MarketSnapshot: orderbooks, BTC price (Chainlink WS or Binance), 5-min candle history
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
 ├── LiveExecutionEngine (execution/live.py) — live mode only
 │   py-clob-client Level 2 → GTC limit orders (3s TTL) → LiveOrderResult
 │   Kill switch, dry run, order size cap, auto-cancel, stealth fill detection
 │   Full telemetry: OB snapshots, poll progression, fill source, balance diffs
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
│   │   ├── replay.py             # polybot-replay CLI — candle orderbook replay & fill analysis
│   │   ├── report.py             # polybot-analyze CLI
│   │   └── validate.py           # polybot-validate CLI — assumption validation against market history
│   ├── execution/
│   │   ├── __init__.py
│   │   └── live.py              # Live CLOB execution (GTC limit orders, safety checks)
│   ├── decision_engine/
│   │   ├── engine.py             # Claude API decision calls
│   │   ├── prompts.py            # System prompt + feature formatting
│   │   └── schemas.py            # JSON schema for structured output
│   ├── logging/
│   │   └── trade_log.py          # JSONL trade + resolution logging
│   ├── market_data/
│   │   ├── btc_price.py          # Hybrid BTC price: Chainlink WS (primary) + Binance (fallback) + CoinGecko (24h)
│   │   ├── chainlink_ws.py       # Chainlink RTDS WebSocket — real-time resolution-source BTC price
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
├── scripts/
│   └── generate_api_key.py      # Derive CLOB API credentials from wallet key
├── tests/                        # pytest + pytest-asyncio
├── .env.example                  # Environment variable template
└── pyproject.toml                # Package definition + dependencies
```

---

## License

This project is for educational and research purposes. Live trading mode places real orders on Polymarket — use at your own risk.
