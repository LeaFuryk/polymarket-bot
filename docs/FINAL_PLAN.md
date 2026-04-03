# BTC Polymarket Trading Bot — Project Specification

---

## Objective

Build a profitable, data-driven trading bot for Polymarket BTC 5-minute candle markets that uses Claude as a direction oracle, continuously improves through collected data, and evolves toward a fully agentic architecture as confidence and data volume grow.

The core thesis: a well-structured prompt fed to Claude, informed by real-time market state and historical similar situations, can achieve directional accuracy above 65% on actionable setups — sufficient for positive expected value given Polymarket's payout structure.

---

## Approach

### Core principles

**Claude is a reasoning oracle, not a rule engine.** Hard rules (spread thresholds, cash checks, time limits) live in code. Claude handles the judgment calls that rules cannot — session character, conflicting signals, weight of evidence.

**Data collection precedes optimization.** The first version collects clean market data. Feature selection, model training, and prompt refinement happen after, against real historical data — not against assumptions.

**Migration cost is minimized by design.** Every component is behind a clean interface. The oracle, the data store, the execution layer are all swappable without touching surrounding code. The path from spec bot to agentic bot is a function swap, not a rewrite.

**One source of truth.** Chainlink Data Streams is the only price feed. No Binance, no CEX divergence tracking. Settlement is Chainlink — so collection, labeling, and prediction all use Chainlink.

---

## Architecture

### Overview

Three concentric layers following a hexagonal (ports and adapters) pattern.

```
Outer ring  — infrastructure adapters (Chainlink, Polymarket, storage)
Middle ring — workers (lightweight, single-purpose, no LLM)
Inner core  — oracle (Claude, called sparingly)
```

### Infrastructure adapters (outer ring)

| Adapter | Responsibility |
|---|---|
| Chainlink Data Streams | WebSocket tick feed → candle builder |
| Polymarket CLOB | Order book snapshots, bet placement via py-clob-client |
| Trade store | JSONL append-only log of RagRecords |
| Vector DB | Embedding index for RAG similarity search |
| Hard limits | Code-enforced pre-flight rules — never reaches oracle |

### Workers (middle ring)

All workers are pure Python. No LLM calls. Fast, deterministic, single-purpose.

| Worker | Trigger | Job |
|---|---|---|
| Market worker | Every Chainlink tick | Update candle state, evaluate trigger conditions, build snapshot |
| Pre-flight worker | On trigger fire | Validate spread, cash, timing, cheap token trap |
| RAG worker | On trigger fire (parallel) | Fetch 10 most similar historical records |
| Exec worker | On oracle decision | Validate hard limits, size position, place bet |
| Labeler worker | On candle close | Fetch Chainlink settlement, compute outcome, write RagRecord |
| Monitor worker | Every tick | Watch open positions, cut on threshold breach |

### Oracle (inner core)

Claude Sonnet with cached system prompt. Called at most once per candle. Returns `UP` or `DOWN`. Single token. Never touches infrastructure directly.

```python
async def oracle(snapshot: MarketState, indicators: dict) -> str:
    # today: direct Claude call
    # phase 3: fine-tuned model
    # phase 4: mini agent loop wrapping this same function
    return await claude.call(
        system=SYSTEM_PROMPT,          # cached
        message=build_prompt(snapshot, indicators),
        max_tokens=10
    )
```

### Orchestrator

A single async event loop. Two workers ride it continuously — market worker and monitor worker. Everything else is spawned as background tasks when conditions warrant.

```python
async def main():
    async for tick in chainlink.stream():         # the only loop
        await market_worker.evaluate(tick)        # always — pure Python
        await monitor_worker.check(tick)          # always — pure Python
        # oracle is called inside market_worker
        # only when trigger fires, as a background task
```

### Data model

```python
@dataclass(frozen=True)
class MarketState:
    """Raw market data only. No derived indicators."""
    candles: tuple[CandleData, ...]     # OHLCV only
    current_candle: CurrentCandleData   # price + volume + timing
    up_book: OrderBook
    down_book: OrderBook
    up_price_history: tuple[float, ...]
    bet_state: BetState

@dataclass(frozen=True)
class RagRecord:
    candle_id: str
    trigger_elapsed_pct: float
    market_state: MarketState           # raw — never changes
    raw_indicators: dict                # all computed metrics — grows over time
    outcome: str                        # "UP" | "DOWN" | "PENDING"
    final_ret: float                    # ln(chainlink_close / candle_open)
    embedding: tuple[float, ...]        # recomputable from raw_indicators
    oracle_signal: str | None = None    # optional — populated if oracle was called
    oracle_model: str | None = None     # which model generated the signal
```

### Prompt structure

**System prompt (~35 lines, cached):** market rules, confidence scale, sizing note, output schema.

**User prompt (per cycle):**

```
## PRIMARY SIGNAL
BTC move: $-42.00 (DOWN winning) — STRONG move
BTC NOW: $66,798.00 | Candle open: $66,840.00 | Time left: 187s

## Pre-computed Flags
- Velocity conflict: NONE
- Reversal regime:  MODERATE (score 0.41) → size auto-scaled 75%

## Market
UP token:   ask=0.38 bid=0.35 mid=0.365 spread=8.11% depth: $89bid/$134ask  R/R=1.63
DOWN token: ask=0.63 bid=0.60 mid=0.615 spread=4.76% depth: $201bid/$88ask  R/R=0.59

Recent UP midpoints (last 10): [...]
Midpoint trend: DOWN (-0.175)

## Candle History (newest last)
| # | Open | Close | Dir | Body% |
...
MA5 vs MA12 → BEARISH crossover
Trend score: -0.52 (BEARISH)

## Session Context
Trend consistency: -0.40 (mild bearish trend)
Range position:    0.28 (mid-range — reversal risk low)
YES ob imbalance:  -0.18 (sellers dominant on UP)
NO ob imbalance:   +0.21 (buyers dominant on DOWN)
Vol timing:        0.31 (early informed flow)

## Similar historical setups (RAG — phase 2+)
| elapsed | range_pos | trend | btc_move | outcome |
...

## ML signal (phase 3+)
Direction: UP (67%) | accuracy: 0.64 | MRR: 0.71

## Positions / Portfolio
...

## Cycle #23
```

### Trigger conditions (Layer 1 — pure Python)

All must pass simultaneously:

```python
vol_delta > 0                          # live Polymarket activity
yes_price in [0.45, 0.85]
  OR no_price in [0.45, 0.85]         # actionable odds on either side
volume_pace >= 0.40                    # candle has enough data
elapsed_pct in [0.10, 0.79]           # not too early or too late
up_spread < 0.15                       # liquid market
down_spread < 0.15
```

### Pre-flight hard blocks (Layer 1 — code only)

```python
up_spread > 0.15 or down_spread > 0.15    # illiquid
cash <= 0                                  # no capital
time_remaining < 15                        # too late
btc_move_abs == 0                          # no signal
losing_token_ask < 0.20
  and abs(ob_imbalance) > 0.30            # cheap token trap
```

---

## Phases

### Phase 1 — Data collection (current)

**Goal:** collect 1,000+ labeled RagRecords from real market conditions.

**What runs:** the spec bot — Python loop, trigger conditions, no oracle. Every trigger event snapshots a `MarketState` and populates `raw_indicators`. Every candle close labels the record with outcome and `final_ret`. Oracle is not called. `oracle_signal` is `None`.

**What gets stored per record:**
- Full `MarketState` (raw OHLCV, orderbook, bet state)
- All computable indicators — including ones not yet in the prompt
- Chainlink settlement outcome
- `oracle_signal: None`

**Exit criteria:** 1,000 labeled records with clean Chainlink settlement prices.

---

### Phase 2 — Feature discovery

**Goal:** identify which indicators actually predict outcome. Define the final prompt.

**Method:** logistic regression over full `raw_indicators` feature matrix.

```python
X = pd.DataFrame([r.raw_indicators for r in records])
y = [1 if r.outcome == "UP" else 0 for r in records]
model = LogisticRegression()
model.fit(X, y)
# sort by abs(coef) → feature ranking
```

**Output:** ranked feature list. Top N features become the prompt. The rest are dropped or demoted to RAG only.

**Also in this phase:**
- Backfill `oracle_signal` on all records — replay full `MarketState` through current Claude prompt overnight
- Populate vector DB with embeddings using final feature set
- Enable RAG block in prompt

**Exit criteria:** stable feature set. Prompt validated against historical accuracy. RAG live.

---

### Phase 3 — Production ML model

**Goal:** replace intuition-based prompt with a calibrated probability signal.

**Method:** train on labeled records using final feature set from phase 2. Start with logistic regression, progress to gradient boosting if sample size warrants it.

```python
FINAL_FEATURES = [...]   # from phase 2
model = CalibratedClassifierCV(LogisticRegression())
model.fit(X_train, y_train)
prob_up = model.predict_proba([embedding])[0][1]
```

**Metrics fed back into prompt:**

```
## ML signal
Direction: UP (67%) | accuracy: 0.64 | MRR: 0.71 | MAE: 0.18
Regime accuracy: choppy 0.58 | trending 0.71 | extended 0.69
```

**Exit criteria:** ML model beats baseline (random = 0.50, logistic on raw features = measured in phase 2). Claude + ML accuracy measurably higher than Claude alone.

---

### Phase 4 — Fine-tuning

**Goal:** fine-tune Claude on labeled `{prompt, completion}` pairs from real trading.

**Training data:** one example per candle. Prompt is the full user prompt at trigger time. Completion is `"UP"` or `"DOWN"` based on Chainlink settlement.

**Target:** 2,000+ examples before first fine-tune run. Time-based train/test split — no random shuffling.

**Exit criteria:** fine-tuned model outperforms base Claude on held-out test set.

---

### Phase 5 — Agentic architecture (future)

**Goal:** replace fixed-interval calling with adaptive entry timing via a mini agent loop.

**Architecture:** GPT-4o-mini runs the candle lifecycle (when to sample, when to wait, when to cut). Claude oracle is called once when mini decides conditions are right.

```python
async def oracle(snapshot):
    # same function signature — drop-in replacement
    return await mini_agent.run(
        tools=[get_market_state, wait_seconds,
               confirm_with_oracle, place_bet, cut_position],
        initial_context=snapshot
    )
    # confirm_with_oracle calls Claude internally
```

**Cost:** ~$0.001 mini calls + ~$0.010 oracle call per candle. Equivalent to current architecture.

**Migration cost:** one function replacement. All workers, adapters, data schema unchanged.

---

## Roadmap

| Milestone | Phase | Description |
|---|---|---|
| Bot live, collecting | 1 | Trigger fires, snapshots stored, no oracle |
| 500 records | 1 | First logistic regression — sanity check features |
| 1,000 records | 1→2 | Feature discovery, backfill oracle signals |
| Prompt finalized | 2 | Final feature set defined, RAG live |
| ML model live | 3 | Probability signal in prompt, metrics tracked |
| 2,000 records | 3→4 | Fine-tune dataset ready |
| Fine-tune v1 | 4 | First fine-tuned model, A/B vs base Claude |
| Agentic v1 | 5 | Mini agent loop, adaptive entry timing |

---

## Measurements

### Per-candle metrics (logged every trade)

| Metric | Description |
|---|---|
| `directional_accuracy` | % of oracle calls where signal matched outcome |
| `entry_elapsed_pct` | When in the candle the bet was placed |
| `entry_odds` | yes/no price at entry |
| `final_ret` | Actual candle return (magnitude signal) |
| `pnl` | Realized P&L after fees |
| `oracle_latency_ms` | Time from trigger to oracle response |

### Session metrics (logged each session)

| Metric | Description |
|---|---|
| `win_rate` | Correct directional calls / total calls |
| `avg_entry_odds` | Average entry price across session |
| `api_cost` | Total Claude API spend |
| `calls_per_candle` | Oracle calls / candles traded |
| `trigger_rate` | Candles where trigger fired / total candles |
| `preflight_block_rate` | % of triggers blocked by pre-flight |

### Model metrics (computed in phase 2+)

| Metric | Description |
|---|---|
| `MRR` | Mean reciprocal rank of correct outcome |
| `MAE` | Mean absolute error on final_ret prediction |
| `calibration` | How well probabilities match actual frequencies |
| `regime_accuracy` | Accuracy broken down by trend_consistency bucket |
| `feature_coefficients` | Logistic regression weights — feature importance ranking |

### RAG metrics (phase 2+)

| Metric | Description |
|---|---|
| `rag_hit_accuracy` | Accuracy of oracle when RAG majority matched signal |
| `rag_miss_accuracy` | Accuracy of oracle when RAG majority contradicted signal |
| `avg_similarity_score` | Mean cosine similarity of retrieved records |
| `records_with_signal` | % of RAG records with oracle_signal populated |

### Target thresholds

| Metric | Minimum | Target |
|---|---|---|
| Win rate | 0.60 | 0.70 |
| Oracle latency | < 5s | < 2.5s |
| API cost per session | < $2.00 | < $1.00 |
| Trigger rate | > 0.20 | 0.30–0.50 |
| Entry odds | 0.45–0.85 | 0.45–0.68 |