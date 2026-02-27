# AI Engineering Analysis — Polymarket Trading Bot

> **Author**: Claude Opus 4.6 (AI Engineering Audit)
> **Date**: 2026-02-26
> **Codebase Version**: v0.4.1
> **Methodology**: Full codebase read (~6,000 lines across 18 Python files + 1 dashboard), cross-referenced with 7 archived iteration results, real trade logs, and system prompts.

---

## Table of Contents

1. [How This Analysis Was Conducted](#1-how-this-analysis-was-conducted)
2. [Architecture Overview](#2-architecture-overview)
3. [Opportunity 1: Prompt Token Waste](#3-opportunity-1-prompt-token-waste)
4. [Opportunity 2: Screening → Decision Context Gap](#4-opportunity-2-screening--decision-context-gap)
5. [Opportunity 3: ML Scorer Underutilization](#5-opportunity-3-ml-scorer-underutilization)
6. [Opportunity 4: No Cross-Candle Microstructure Memory](#6-opportunity-4-no-cross-candle-microstructure-memory)
7. [Opportunity 5: Reflection System Fires Too Infrequently](#7-opportunity-5-reflection-system-fires-too-infrequently)
8. [Opportunity 6: Sparse Calibration Data](#8-opportunity-6-sparse-calibration-data)
9. [Opportunity 7: Binary Exit Strategy](#9-opportunity-7-binary-exit-strategy)
10. [Opportunity 8: No Velocity/Acceleration Data](#10-opportunity-8-no-velocityacceleration-data)
11. [Opportunity 9: Temperature = 0.0 Determinism](#11-opportunity-9-temperature--00-determinism)
12. [Opportunity 10: No Ensemble or Disagreement Signal](#12-opportunity-10-no-ensemble-or-disagreement-signal)
13. [Implementation Priority Matrix](#13-implementation-priority-matrix)

---

## 1. How This Analysis Was Conducted

### Methodology: AI Systems Auditing

This analysis follows a structured approach that any AI engineer should use when auditing an AI-powered system:

#### Step 1: Map the Data Flow

Before looking at any individual component, I traced how data flows through the entire system end-to-end:

```
Raw Market Data → Feature Engineering → AI Context Construction →
LLM Decision → Post-Decision Gates → Execution → Outcome → Feedback Loop
```

Every AI system has this pipeline. The opportunities hide in the **gaps between stages** — where information is lost, delayed, or never connected.

#### Step 2: Identify Information Asymmetries

The core question: **"What does the AI NOT know that would help it decide better?"**

I compared what data exists in the system (logged, computed, available) against what actually reaches the LLM prompt. Every piece of available-but-unused data is a potential opportunity.

#### Step 3: Measure Feedback Loop Latency

AI systems improve through feedback. I measured how quickly each feedback mechanism operates:

| Feedback Loop | Latency | Bottleneck |
|---|---|---|
| Calibration | ~75 trades to populate one bin | Sparse data per bin |
| Reflection | Every 10 resolutions (~50 min) | Fixed trigger interval |
| ML Scorer | Every resolution (~5 min) | ✓ Fast |
| Adaptive Entry | Every resolution (~5 min) | ✓ Fast |
| Exit Tracker | Post-resolution | Data logged but never fed back |

Slow feedback loops mean the system can't adapt to changing conditions. Fast loops mean it can, but only if the data actually reaches the decision-maker.

#### Step 4: Token Economics

Every token sent to the LLM costs money and consumes context window. I measured:
- How many tokens are **signal** (data the AI needs to make better decisions)
- How many tokens are **noise** (static boilerplate, repeated explanations, invariant context)

This is unique to AI engineering — traditional software doesn't have a "cost per character of input."

#### Step 5: Cross-Reference with Outcomes

I read the archived iteration results (iter_004 through iter_007) to see which failure modes actually occurred. This grounds the analysis in reality rather than theory. For example, iter_007's $71 loss from reversals directly motivated the velocity/acceleration opportunity — the data existed (prefilter snapshots), but the AI never saw it.

---

## 2. Architecture Overview

Understanding the architecture is prerequisite to understanding the opportunities. Here's the system at a conceptual level:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Trading Agent                            │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │  Market   │  │   AI     │  │ Position │  │  Dashboard   │   │
│  │ Monitor   │  │ Decision │  │ Monitor  │  │    Loop      │   │
│  │ (1s loop) │  │ (event)  │  │ (1s loop)│  │  (2s loop)   │   │
│  └────┬──────┘  └────┬─────┘  └────┬─────┘  └──────────────┘   │
│       │              │             │                            │
│       │   trigger     │    exit     │                            │
│       ├──────────────►│◄───────────┤                            │
│       │              │             │                            │
│       │         ┌────▼─────┐      │                            │
│       │         │  2-Pass  │      │                            │
│       │         │ Pipeline │      │                            │
│       │         │          │      │                            │
│       │         │ Haiku    │      │                            │
│       │         │   ↓      │      │                            │
│       │         │ Sonnet   │      │                            │
│       │         └────┬─────┘      │                            │
│       │              │            │                            │
│       │         ┌────▼─────┐      │                            │
│       │         │  Gates   │      │                            │
│       │         │ Confid.  │      │                            │
│       │         │ Calibr.  │      │                            │
│       │         │ Anti-*   │      │                            │
│       │         └────┬─────┘      │                            │
│       │              │            │                            │
│       │         ┌────▼─────┐      │                            │
│       │         │Execution │      │                            │
│       │         │Simulator │      │                            │
│       │         └──────────┘      │                            │
│       │                           │                            │
│  ┌────▼───────────────────────────▼────┐                       │
│  │         Feedback Systems            │                       │
│  │  Calibration | Reflection | ML      │                       │
│  │  Exit Track  | Adaptive Entry       │                       │
│  └─────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

### Key AI Engineering Concepts in This System

**1. Two-Pass LLM Pipeline (Cost Optimization)**

This is a common pattern in production AI systems: use a cheap/fast model to filter, then a powerful/expensive model for the actual decision. It's the same principle as cascade classifiers in ML — spend compute only where it matters.

```
Cost without two-pass: 100 triggers × $0.005 = $0.50/session
Cost with two-pass:    100 × $0.0008 (Haiku) + 30 × $0.005 (Sonnet) = $0.23/session
Savings: 54%
```

**2. Structured Output (JSON Schema Constrained Decoding)**

Instead of parsing free-form text, the system uses Claude's structured output feature — the API guarantees the response matches a JSON schema. This eliminates parsing failures, a major reliability concern in production AI systems.

**3. Online Learning (ML Scorer)**

The logistic regression model trains after every candle resolution — no batch training, no model deployment pipeline. This is called "online learning" and it's ideal for non-stationary environments (markets) where the data distribution shifts constantly.

**4. Calibration (Confidence → Accuracy Mapping)**

The system tracks whether the AI's stated confidence actually correlates with win rate. This is a critical concept: **LLMs are notoriously miscalibrated** — a model saying "I'm 80% confident" doesn't mean it's right 80% of the time. The calibration system measures this gap and uses it to gate trades.

---

## 3. Opportunity 1: Prompt Token Waste

### The Discovery

When reading `prompts.py:format_feature_vector()` (lines 135-350), I counted the tokens that are **identical every single cycle**:

```python
# These lines appear in EVERY prompt, unchanged:
"Prefer the token with tighter spread when both sides are viable. "
"DOWN tokens often have wider spreads — factor this cost into your edge calculation."
"(⚠ NOT predictive for 5-min candles — ~40% go opposite to daily trend)"
"Condition ID: {fv.market.condition_id}"
"Token ID: {fv.market.up_token_id[:12]}..."
```

Each prompt also includes the full OHLC table header, section headers, and explanatory notes. These are educational for the AI on the first call — but by the 100th call in a session, they're pure waste.

### Why This Matters (AI Engineering Principle)

**Token economics** is a first-class concern in AI engineering. Every input token has:

1. **Direct cost**: $3 per million tokens (Sonnet). A 2,000-token prompt costs $0.006. Cut 400 tokens → save $0.0012 per call → $0.12 per 100 calls.

2. **Attention dilution**: LLMs have finite attention. The more tokens in the context, the harder it is for the model to focus on what matters. Research shows that LLMs perform worse on tasks when the context contains irrelevant information (the "lost in the middle" phenomenon). Static boilerplate pushes the actual market data further from the model's attention peak.

3. **Latency**: More tokens = more processing time. In a trading bot where decisions are time-sensitive (5-min candles), every 100ms matters.

### The Technical Fix

Move static explanations into the system prompt (sent once per conversation). The per-cycle user message should contain only variable data:

**Before** (every cycle):
```
## BTC Context (Chainlink BTC/USD — resolution source)   ← static header
- BTC Price NOW: $67,395.55                              ← variable
- Chainlink On-Chain Price: $67,390.00 (divergence: $5.55) — THIS is the resolution source  ← partially static
- BTC 24h Change: +1.23% (⚠ NOT predictive for 5-min candles — ~40% go opposite...)  ← mostly static
```

**After** (system prompt has the explanations, per-cycle is pure data):
```
## BTC
NOW: $67,395.55 | Chainlink: $67,390.00 (div: $5.55) | 24h: +1.23%
```

The system prompt already explains what Chainlink is, what divergence means, and why 24h change isn't predictive. Repeating it 100 times wastes tokens.

### Estimated Impact

- **Token reduction**: ~300-500 tokens per Sonnet call (~15-25%)
- **Cost savings**: ~$0.10-0.15 per 100 decisions
- **Quality improvement**: Better signal-to-noise ratio in the attention window
- **Risk**: Minimal — the AI still gets all the same data, just without redundant explanations

---

## 4. Opportunity 2: Screening → Decision Context Gap

### The Discovery

In `ai_decision.py`, lines ~350-420, I traced what happens between the two AI passes:

```python
# Pass 1: Haiku screening
screen_result = await self._engine.screen(screening_context)
# screen_result contains: should_trade (bool) + reason (string)

if not screen_result.should_trade:
    return  # HOLD — reason is logged but that's it

# Pass 2: Sonnet decision — screen_result.reason is THROWN AWAY
decision, latency, cost = await self._engine.decide(full_feature_vector)
```

Haiku's reasoning (e.g., "BTC moved +$52 with 78% reversal rate — strong contrarian setup") is **never passed to Sonnet**. Sonnet builds its own analysis from scratch.

### Why This Matters (AI Engineering Principle)

This is a **context propagation failure** — a common anti-pattern in multi-stage LLM pipelines.

In a well-designed pipeline, each stage should **build on** the previous stage's work, not redo it. This is analogous to:
- A junior analyst writing a brief → senior analyst reads it before the full review
- A triage nurse's notes being visible to the doctor
- A compiler's lexer output feeding into the parser

When you discard intermediate reasoning, you lose:

1. **Priming effect**: Sonnet would benefit from knowing what Haiku already identified as the key signal. LLMs are sensitive to priming — seeing "strong contrarian setup" at the top of the context biases Sonnet toward evaluating the contrarian angle more deeply.

2. **Consistency**: If Haiku said "trade because of reversal rate" but Sonnet focuses on momentum, the pipeline is internally inconsistent. Passing Haiku's reasoning forces Sonnet to address it (agree or disagree).

3. **Debugging**: When a trade goes wrong, you want to know: did both models agree on WHY to trade? If Haiku said "momentum" and Sonnet said "contrarian," that disagreement itself is a risk signal.

### The Technical Fix

```python
# Before: reason discarded
decision = await self._engine.decide(feature_vector)

# After: reason injected as context
screening_note = f"## Pre-Screening Note (fast model)\n{screen_result.reason}"
decision = await self._engine.decide(feature_vector, screening_context=screening_note)
```

This adds ~20-30 tokens to the Sonnet prompt but provides a significant reasoning anchor.

### Estimated Impact

- **Quality**: Better decision consistency between screening and full analysis
- **Cost**: ~$0.00005 per call (negligible — 20-30 extra tokens)
- **Debug value**: High — creates an audit trail of multi-model reasoning
- **Risk**: Near-zero — it's additive context, not a constraint

---

## 5. Opportunity 3: ML Scorer Underutilization

### The Discovery

Reading `ml_scorer.py` (324 lines), I found that the model computes rich internal state that's thrown away:

```python
def predict(self, features: dict[str, float]) -> MLPrediction:
    # Computes per-feature contributions (how much each feature pushes toward UP/DOWN)
    contributions = {}
    for i, name in enumerate(FEATURE_NAMES):
        contributions[name] = self._weights[i] * normalized[i]

    # But only returns:
    return MLPrediction(
        up_probability=prob,
        confidence=confidence_label,
        feature_contributions=contributions,  # ← THIS IS COMPUTED but barely used
    )
```

In `ai_decision.py`, only the probability and confidence label reach the AI prompt:

```python
ml_line = f"ML Baseline: {pred.up_probability:.0%} UP ({pred.confidence})"
```

The **per-feature contributions** — which explain WHY the model thinks UP or DOWN — are logged but never shown to the AI.

### Why This Matters (AI Engineering Principle)

This is a case of **interpretability waste**. One of the key advantages of simple ML models (logistic regression) over deep learning is that they're **inherently interpretable**. You can see exactly how much each feature contributes to the prediction.

In AI engineering, interpretability serves two purposes:

1. **Human debugging**: Engineers can inspect feature weights to understand model behavior.
2. **LLM context enrichment**: An LLM can use feature contributions as reasoning anchors. Instead of "ML says 65% UP," it sees "ML says 65% UP — driven by: strong UP streak (+0.3), BTC +$45 from open (+0.25), but high reversal rate (-0.15)."

This turns the ML scorer from a black-box hint into a **structured reasoning scaffold**. The LLM can then agree with the ML's logic, identify where the ML might be wrong (e.g., "ML is weighting streak heavily, but the streak is about to exhaust"), or calibrate its own confidence against the ML's.

### Additional Missed Uses

**Position Sizing Signal**: If ML confidence is very high (>70%) but AI confidence is moderate (0.60), this disagreement should either increase size (ML provides independent confirmation) or decrease it (they might be seeing different things).

**Screening Enhancement**: If ML strongly disagrees with Haiku's direction, that's a red flag. Currently this disagreement is invisible.

**Feature Weight Tracking**: Over time, the model learns which features predict outcomes. Tracking weight evolution reveals market regime changes — e.g., if `reversal_rate` weight suddenly becomes strongly negative, the market is shifting from momentum to mean-reversion.

### The Technical Fix

Enhance the ML line in the prompt:

```python
# Before: one-line summary
ml_line = f"ML Baseline: {pred.up_probability:.0%} UP ({pred.confidence})"

# After: include top contributing features
top_features = sorted(
    pred.feature_contributions.items(),
    key=lambda x: abs(x[1]),
    reverse=True
)[:3]
drivers = ", ".join(f"{name}: {val:+.2f}" for name, val in top_features)
ml_line = f"ML Baseline: {pred.up_probability:.0%} UP ({pred.confidence}) — drivers: {drivers}"
```

### Estimated Impact

- **Quality**: Significantly better — gives the AI structured reasoning about WHY the baseline predicts a direction
- **Cost**: ~30 extra tokens per call (~$0.0001)
- **Debugging**: Much better — you can see when ML and AI disagree on reasoning
- **Risk**: Low — additive context only

---

## 6. Opportunity 4: No Cross-Candle Microstructure Memory

### The Discovery

Each AI decision is scoped to the current candle. The feature vector in `prompts.py:format_feature_vector()` includes BTC candle history (OHLC tables), but NO information about:

- How spreads have evolved across recent candles
- Whether orderbook depth has been increasing or decreasing
- Whether the current candle's BTC volatility is normal or extreme compared to recent ones
- Whether the market's pricing pattern is stable or shifting

The system HAS this data — `MarketMonitor` captures `PreFilterSnapshot` every second with full orderbook state. But snapshots are discarded at candle boundaries. The AI sees only the current candle's snapshot.

### Why This Matters (AI Engineering Principle)

This is a **context horizon problem**. The AI has a temporal blind spot: it can see BTC price history (200 candles via Binance klines), but it can't see **market microstructure** history (spreads, depth, imbalance).

In trading, microstructure often predicts price action before price itself moves:

- **Widening spreads** → market makers pulling liquidity → expect volatility
- **Thinning depth** → fewer resting orders → larger price impact per trade
- **Persistent orderbook imbalance** → directional pressure building

These are **leading indicators** that precede BTC moves. The BTC candle history is a **lagging indicator** (it shows what already happened). Giving the AI both leading and lagging indicators dramatically improves its ability to predict the next candle.

### Why This Wasn't Caught Earlier

This is a subtle issue because the system DOES have indicators like `orderbook_imbalance` and `spread_trend` — but these are computed within the current candle only. They answer "what is the orderbook like RIGHT NOW?" not "how has the orderbook been changing OVER TIME?"

The difference matters: an orderbook imbalance of 1.5 (bid-heavy) means one thing if it's been stable for 20 minutes (structural bias), and something very different if it just spiked from 0.8 to 1.5 in the last candle (sudden pressure shift).

### The Technical Approach

Build a `MicrostructureSummary` computed from the last 3-5 candles' prefilter snapshots:

```python
@dataclass
class MicrostructureSummary:
    avg_spread_trend: float      # Are spreads widening or narrowing?
    depth_trend: float           # Is liquidity growing or shrinking?
    imbalance_persistence: float # How consistent is the order flow direction?
    volatility_regime: str       # "LOW" / "NORMAL" / "HIGH" vs recent history
```

This would add ~50 tokens to the prompt but provides the AI with cross-candle market context it currently lacks entirely.

---

## 7. Opportunity 5: Reflection System Fires Too Infrequently

### The Discovery

In `knowledge.py`, the reflection trigger is hardcoded:

```python
# In agent.py, after each resolution:
self._resolutions_since_reflection += 1
if self._resolutions_since_reflection >= 10:
    await self._knowledge_manager.reflect(...)
    self._resolutions_since_reflection = 0
```

10 resolutions = ~50 minutes of trading. In iter_007, the bot lost $71 in 59 minutes — the entire session. Reflection would have fired once, at the very end, when the money was already gone.

### Why This Matters (AI Engineering Principle)

This is a **feedback latency** problem. In control theory, the quality of a controller depends on three things:

1. **Measurement accuracy** — can you observe the system state? (Yes — trades/outcomes are logged)
2. **Feedback delay** — how long between observation and correction? (50 minutes — TOO SLOW)
3. **Correction magnitude** — can you make meaningful adjustments? (Yes — observations modify AI behavior)

The system has good measurement (1) and good correction ability (3), but the feedback delay (2) is too long. By analogy: imagine driving a car where your steering inputs take 50 minutes to reach the wheels. You'd crash immediately.

In AI engineering, **adaptive feedback frequency** is a well-known pattern:

- **Control systems**: PID controllers increase sampling rate when the error signal is large
- **Reinforcement learning**: Exploration rate increases after unexpected rewards/penalties
- **Production ML**: Model retraining triggers more frequently when drift is detected

The same principle applies here: when the bot is losing, it needs to reflect more often to identify what's going wrong.

### The Technical Fix

```python
# Before: fixed 10-resolution trigger
if self._resolutions_since_reflection >= 10:
    await reflect()

# After: adaptive trigger based on recent performance
recent_pnl = sum(r.pnl for r in self._recent_resolutions[-5:])
trigger_threshold = 5 if recent_pnl < -10.0 else 10
if self._resolutions_since_reflection >= trigger_threshold:
    await reflect()
```

When the last 5 resolutions have net PnL < -$10, reflection fires every 5 resolutions (~25 min) instead of 10. This doubles the feedback speed during drawdowns while keeping the normal pace during profitable periods.

### Estimated Impact

- **Drawdown reduction**: Faster detection of regime shifts and strategy failures
- **Cost**: One extra reflection per bad session (~$0.01 in API costs)
- **Quality**: Observations are generated from smaller batches, potentially more focused
- **Risk**: Low — reflection produces observations, not hard rules. More observations ≠ over-correction because they're descriptive ("momentum plays lost 4/5 times") not imperative.

---

## 8. Opportunity 6: Sparse Calibration Data

### The Discovery

In `calibration.py`, the system uses 5%-wide confidence bins with a 15-sample minimum:

```python
BIN_WIDTH = 0.05   # 5% wide bins: [0.55, 0.60), [0.60, 0.65), ...
MIN_SAMPLES = 15   # Need 15 trades in a bin before trusting it
```

The bot makes ~5-10 trades per session. With confidence values typically clustering in the 0.60-0.75 range, it takes **many sessions** to get 15 samples in any single 5%-wide bin. Until then, the calibrator returns `is_reliable=False` and uses stated confidence as-is — providing zero correction.

I verified this by checking the calibration summary output: most bins had 1-5 samples after 7 iterations. Not a single bin had reached the 15-sample reliability threshold.

### Why This Matters (AI Engineering Principle)

**Calibration** is one of the most important concepts in AI engineering, especially for systems that make consequential decisions based on LLM confidence.

The fundamental problem: **LLMs don't have calibrated confidence**. When Claude says "I'm 70% confident," that number comes from the structured output schema, not from an internal probability distribution. The model is essentially guessing a number that "feels right" based on its training data.

Research on LLM calibration shows:
- Models tend to be **overconfident** on hard tasks and **underconfident** on easy tasks
- Confidence calibration varies significantly by domain and prompt structure
- **Post-hoc calibration** (tracking stated vs actual accuracy) is the most reliable fix

This system correctly implements post-hoc calibration — but the bins are too narrow and the threshold too high, making the calibration data useless in practice.

### The Technical Fix

Two changes:

**1. Wider bins (10% instead of 5%)**

```python
BIN_WIDTH = 0.10  # [0.50, 0.60), [0.60, 0.70), [0.70, 0.80), [0.80, 0.90)
```

This reduces the number of bins from 10 to 5 for the relevant range, concentrating samples. A bin that had 3 samples now has ~6 (aggregated from two adjacent 5% bins). Reaches reliability 2-3x faster.

Trade-off: lower resolution. You can't distinguish 0.62 from 0.67 confidence. But in practice, this distinction is noise anyway — the AI doesn't have that level of calibration precision.

**2. Lower minimum samples (10 instead of 15)**

With 10 samples, you get a reasonable estimate of win rate (standard error ≈ 15% at 10 samples vs 13% at 15 — marginal difference). This further speeds up the time to reliable calibration.

**3. Bayesian prior (advanced)**

Instead of using stated confidence as a blind default, start with a weak prior based on market base rates:

```python
# Before: trust stated confidence blindly until 15 samples
if not bin.is_reliable:
    calibrated_win_rate = stated_confidence  # no correction

# After: Bayesian blend — shrink toward base rate
base_rate = 0.50  # market base rate (coin flip)
shrinkage = min(1.0, bin.total / MIN_SAMPLES)
calibrated_win_rate = shrinkage * bin.win_rate + (1 - shrinkage) * base_rate
```

This gradually transitions from "assume 50% base rate" (skeptical prior) to "trust the observed win rate" as samples accumulate. It's a standard Bayesian shrinkage estimator used in sports analytics, credit scoring, and recommendation systems.

### Estimated Impact

- **Faster calibration**: Bins reach reliability in ~2-3 sessions instead of ~6-8
- **Better early decisions**: Bayesian prior prevents the system from blindly trusting high confidence in the first few sessions
- **Cost**: Zero — calibration is computed from existing data
- **Risk**: Moderate — wider bins lose granularity, but the granularity was useless with insufficient data anyway

---

## 9. Opportunity 7: Binary Exit Strategy

### The Discovery

In `position_monitor.py`, exit logic is two hard thresholds:

```python
STOP_LOSS = -0.60   # Exit if position is down 60%
TAKE_PROFIT = 0.80  # Exit if position is up 80%
```

No partial exits, no time-decay adjustment, no trailing stops. The exit tracker (`exit_tracker.py`) logs what would have happened if the position was held to resolution — but this data is **never fed back** into exit decisions.

From iter_007 analysis:
- 3/3 stop-loss exits saved money (correct decisions)
- But the -60% threshold is arbitrary — was -60% actually optimal? Would -40% or -50% have been better?
- Take-profit at +80% has a hidden cost: if the token would resolve to $1.00, you left $0.20 on the table

### Why This Matters (AI Engineering Principle)

This is a **reward signal optimization** problem. In trading AI systems, the entry decision gets most of the engineering attention, but **exit quality often matters more** because:

1. **Asymmetric impact**: A bad entry at $0.40 loses at most $0.40 per share. But a premature exit at $0.80 when the token resolves to $1.00 costs $0.20 per share in missed profit — and a late stop-loss at -60% instead of -40% costs an extra 20% of the position.

2. **Time value**: In a 5-minute candle, time remaining changes the optimal exit strategy dramatically. With 200 seconds left, a -30% position might recover. With 10 seconds left, it almost certainly won't.

3. **Regime dependency**: In a choppy (high-reversal) market, early exits are valuable because positions reverse frequently. In a trending market, holding to resolution is usually better.

The exit tracker already computes the data needed to optimize this — but the data sits in a JSONL file, never flowing back into the system.

### The Technical Approach

**Time-weighted stop-loss**: Tighten the stop-loss as time remaining decreases.

```python
# Conceptual formula
# With 240s left: stop at -60% (let it breathe)
# With 120s left: stop at -45%
# With 60s left:  stop at -30% (cut losses quickly)
# With 30s left:  stop at -20% (almost certainly won't recover)

time_factor = max(0.3, min(1.0, time_remaining / 240))
dynamic_stop = -0.60 * time_factor  # tightens from -60% to -18%
```

**Exit tracker feedback**: After each session, compute optimal thresholds from exit_analysis data:
- What % of stop-loss exits at -60% would have been winners at resolution? (false stops)
- What % of take-profit exits at +80% resolved to $1.00? (premature exits)
- Use these rates to suggest threshold adjustments for the next session

---

## 10. Opportunity 8: No Velocity/Acceleration Data

### The Discovery

This was the most impactful finding, directly motivated by iter_007's losses. In the feature vector (`prompts.py:format_feature_vector()`), the AI sees:

```
BTC move: +$45 (UP winning) — STRONG move
```

But it does NOT see:
- **Velocity**: Was BTC at +$10 thirty seconds ago (accelerating) or at +$60 (decelerating)?
- **Peak drawback**: Did BTC peak at +$80 and fall back to +$45 (exhaustion) or has it been steady?

The data exists. `MarketMonitor` records `PreFilterSnapshot` every second with `btc_move_from_open`. There's a deque of ~300 snapshots (5 minutes) available in `SharedState.prefilter_history`.

### Why This Matters (AI Engineering Principle)

This is a **feature engineering** gap — one of the most fundamental concepts in ML/AI engineering.

In any prediction problem, the quality of your features determines an upper bound on model performance. **No amount of model sophistication can overcome bad features.** A logistic regression with great features will outperform a transformer with bad features.

The current feature set gives the AI a **snapshot** (BTC position) but no **trajectory** (BTC direction and speed). In physics terms:

- **Position**: BTC is +$45 from open (we have this)
- **Velocity**: BTC is moving at +$2/second (we don't have this)
- **Acceleration**: BTC is decelerating at -$0.5/s² (we don't have this)

For prediction, velocity and acceleration are **more valuable** than position because they tell you where the price is **going**, not where it **is**. A car's current position doesn't tell you if it's about to turn — but its velocity and acceleration do.

### The Technical Evidence from iter_007

Every single loss in iter_007 followed this pattern:

```
Trade 7 (Cycle 33):
- BTC was +$64 from open at entry    ← AI saw this (STRONG move)
- BTC was DECELERATING               ← AI could NOT see this
- BTC crashed to -$124 from open     ← reversal the AI didn't predict
- Loss: -$19.24
```

If the AI had seen "BTC peaked at +$64 but velocity has dropped from +$3/s to +$0.5/s in the last 20 seconds," it would have recognized the exhaustion pattern and held off.

### The Technical Fix

Compute two signals from `prefilter_history`:

```python
def compute_btc_trajectory(prefilter_history: list[PreFilterSnapshot]) -> dict:
    if len(prefilter_history) < 10:
        return {}

    recent = prefilter_history[-10:]   # last ~10 seconds
    earlier = prefilter_history[-30:-20]  # 20-30 seconds ago

    # Velocity: rate of change in BTC move
    if len(recent) >= 2 and len(earlier) >= 2:
        current_velocity = (recent[-1].btc_move - recent[0].btc_move) / len(recent)
        earlier_velocity = (earlier[-1].btc_move - earlier[0].btc_move) / len(earlier)
        acceleration = current_velocity - earlier_velocity

    # Peak drawback: max BTC move vs current
    all_moves = [s.btc_move_from_open for s in prefilter_history]
    peak_move = max(all_moves, key=abs)
    current_move = all_moves[-1]
    drawback = abs(peak_move) - abs(current_move)

    return {
        "velocity": current_velocity,       # $/second
        "acceleration": acceleration,        # $/second²
        "peak_drawback": drawback,          # $ pulled back from peak
        "peak_move": peak_move,             # max BTC move this candle
    }
```

This adds ~40 tokens to the prompt:

```
BTC Trajectory: velocity +$1.2/s (decelerating from +$3.1/s),
                peak $+64 → current $+45 (drawback: $19)
```

### Estimated Impact

- **Quality**: Highest of all opportunities — directly addresses the #1 failure mode (reversal losses)
- **Cost**: ~40 extra tokens (~$0.0001)
- **Predictive power**: Velocity and drawback are among the strongest short-term predictors in high-frequency trading
- **Risk**: Low — additive signal, the AI can choose to weight it or not

---

## 11. Opportunity 9: Temperature = 0.0 Determinism

### The Discovery

In `config/default.yaml`:

```yaml
ai:
  temperature: 0.0  # Deterministic output
```

And in `decision_engine/engine.py`:

```python
response = await self._client.messages.create(
    model=self._model,
    temperature=self._temperature,  # 0.0
    ...
)
```

With temperature 0, Claude will produce the **exact same output** for the exact same input (modulo API-level randomness). This means:
- If the bot sees a similar setup twice, it will make the same decision twice
- There's no exploration — the system can get stuck in local optima
- Mistakes are **systematic**, not random — the same bad pattern repeats

### Why This Matters (AI Engineering Principle)

This touches the **exploration-exploitation tradeoff**, one of the fundamental concepts in AI and decision theory.

**Exploitation (temperature=0)**: Always pick the "best" action based on current knowledge. Maximizes short-term reward but can miss better strategies.

**Exploration (temperature>0)**: Sometimes pick suboptimal actions to discover better strategies. Costs short-term reward but improves long-term performance.

In reinforcement learning, this is formalized as epsilon-greedy, UCB, Thompson sampling, etc. In LLM-based systems, temperature serves a similar role:

- **Temperature 0.0**: Pure exploitation. The model always outputs its highest-probability tokens. Good for: factual Q&A, code generation, tasks with a single correct answer.
- **Temperature 0.1-0.3**: Mild exploration. The model occasionally picks non-obvious tokens, potentially finding different reasoning paths. Good for: creative tasks, decision-making under uncertainty.
- **Temperature 0.5+**: Heavy exploration. Outputs become varied and sometimes incoherent. Bad for most production applications.

For a trading bot, temperature 0.0 means:
- The AI will develop systematic biases (e.g., always preferring UP when BTC moved $30+) that never get corrected through experiential variety
- Shadow predictions (HOLD cycles) are less useful for calibration because they're always the same for similar inputs
- The reflection system sees less variety in AI behavior, making it harder to identify which strategies work

### The Recommendation

```yaml
ai:
  temperature: 0.1  # Mild exploration — same core reasoning, slight variety
```

Temperature 0.1 introduces subtle variation without compromising coherence. The model might:
- Occasionally size a position at 25 shares instead of 30 (exploring position sizing)
- Rate confidence at 0.63 instead of 0.65 (exploring confidence expression)
- Frame reasoning slightly differently (potentially catching patterns it missed at temp=0)

### How to Test This Safely

Use **shadow predictions**: When the AI HOLDs, it still predicts a direction. Compare shadow prediction accuracy at temperature 0.0 vs 0.1 over 50+ candles. If accuracy is similar, the exploration doesn't hurt. If accuracy improves, the variety is helping the model find better reasoning paths.

### Estimated Impact

- **Quality**: Potentially significant long-term improvement through strategy diversity
- **Cost**: Zero (same number of tokens)
- **Risk**: Low at temperature 0.1 — the model is still highly coherent
- **Measurement**: Easy to A/B test with shadow predictions

---

## 12. Opportunity 10: No Ensemble or Disagreement Signal

### The Discovery

The system has two AI models (Haiku for screening, Sonnet for decisions) plus an ML model — but their outputs are never compared. No one tracks:

- How often Haiku says "trade" but Sonnet says "hold" (screening false positive rate)
- How often ML and Sonnet disagree on direction (ensemble disagreement)
- Whether disagreement correlates with worse outcomes (disagreement as risk signal)

### Why This Matters (AI Engineering Principle)

**Ensemble methods** are one of the oldest and most reliable techniques in ML. The core insight: if you have multiple independent predictors, their **agreement/disagreement** is itself a powerful signal.

- **High agreement**: All models converge on the same answer → higher confidence is warranted
- **High disagreement**: Models see different signals → uncertainty is high, and conservative positioning is warranted

This is why techniques like random forests (ensemble of decision trees), boosting, and model averaging consistently outperform single models. The disagreement signal provides information that no individual model can generate on its own.

In this system, there are three "models":
1. **Haiku** (fast screener): Sees compact context, makes binary trade/no-trade
2. **Sonnet** (full decision): Sees rich context, outputs structured decision
3. **ML Scorer** (logistic regression): Sees numerical features, outputs UP probability

These three models see **different data** and use **different reasoning processes**. Their disagreement is extremely valuable:

| Haiku | Sonnet | ML | Interpretation |
|-------|--------|-----|---------------|
| Trade | BUY UP | 70% UP | Strong consensus → higher confidence |
| Trade | BUY UP | 65% DOWN | ML disagrees → reduced confidence |
| Trade | HOLD | — | Haiku too permissive → tune screening |
| Trade | BUY DOWN | 80% UP | Directional conflict → very risky |

### The Technical Approach

**Step 1: Track agreement rates**

```python
# Log every screening→decision pair
screening_agreement_log.append({
    "haiku_said_trade": True,
    "sonnet_action": decision.action,        # BUY/SELL/HOLD
    "sonnet_direction": decision.token_side,
    "ml_direction": "up" if ml_pred > 0.5 else "down",
    "ml_confidence": abs(ml_pred - 0.5) * 2,
    "outcome": winner,  # filled after resolution
})
```

**Step 2: Compute disagreement metrics**

```python
# After each session, compute:
haiku_pass_rate = trades_haiku_approved / total_haiku_calls
sonnet_trade_rate = trades_sonnet_executed / trades_haiku_approved
haiku_precision = trades_that_won / trades_haiku_approved

ml_sonnet_agree_rate = times_ml_and_sonnet_agreed / total_decisions
ml_sonnet_agree_win_rate = ...  # win rate when they agree
ml_sonnet_disagree_win_rate = ...  # win rate when they disagree
```

**Step 3: Use disagreement as a signal**

If historical data shows that trades where ML and Sonnet disagree have 30% win rate vs 65% when they agree, you can add a post-decision gate:

```python
if ml_direction != sonnet_direction and ml_confidence > 0.6:
    logger.warning("ML-AI disagreement: ML says %s with %.0f%%, AI says %s",
                   ml_direction, ml_confidence * 100, sonnet_direction)
    # Option: reduce position size by 30-50%
    # Option: flag for extra caution in reasoning
```

### Estimated Impact

- **Quality**: High — disagreement is one of the most underused signals in multi-model systems
- **Cost**: Zero for tracking; minimal for logging
- **Time to value**: Needs ~50 trades to see meaningful patterns
- **Risk**: Low — start with logging only, add gates later

---

## 13. Implementation Priority Matrix

Based on the analysis, here's the recommended implementation order:

### Tier 1: Quick Wins (< 1 hour each, immediate impact)

| # | Opportunity | Effort | Impact | Risk |
|---|---|---|---|---|
| 2 | Pass Haiku reasoning to Sonnet | 5 min | High | Near-zero |
| 8 | Add BTC velocity/peak-drawback | 30 min | Very High | Low |
| 5 | Adaptive reflection frequency | 30 min | Medium-High | Low |

### Tier 2: Moderate Effort (1-2 hours, significant impact)

| # | Opportunity | Effort | Impact | Risk |
|---|---|---|---|---|
| 6 | Wider calibration bins + Bayesian prior | 45 min | Medium | Moderate |
| 1 | Trim prompt token waste | 1 hour | Medium | Low |
| 3 | ML scorer feature contributions in prompt | 30 min | Medium | Low |

### Tier 3: Strategic (multi-session projects)

| # | Opportunity | Effort | Impact | Risk |
|---|---|---|---|---|
| 7 | Time-weighted exit strategy | 2 hours | High | Moderate |
| 4 | Cross-candle microstructure memory | 3 hours | High | Moderate |
| 10 | Ensemble disagreement tracking | 2 hours | Medium-High | Low |
| 9 | Temperature experimentation | 15 min | Unknown | Low |

### Key Principle: Measure Before Optimizing

Before implementing any change, add **logging/metrics** for the current state. Then implement the change and compare. This is the scientific method applied to AI engineering:

1. **Baseline**: Measure current performance (win rate, PnL, AI cost per trade)
2. **Hypothesis**: "Adding velocity data will reduce reversal losses by 30%"
3. **Implement**: Make the change
4. **Measure**: Run 2-3 sessions and compare against baseline
5. **Iterate**: Keep what works, revert what doesn't

Every AI engineering decision should follow this cycle. Intuition about what "should" work is often wrong — only data tells the truth.

---

## 14. Implementation Status

All 10 opportunities were implemented in v0.5.0. Here's the mapping:

| # | Opportunity | Status | Files Modified |
|---|---|---|---|
| 1 | Prompt token waste | **Implemented** | `prompts.py` — static text moved to system prompt, feature vector compacted |
| 2 | Haiku → Sonnet context | **Implemented** | `ai_decision.py` — screening reason injected as "Pre-Screening Note" |
| 3 | ML scorer feature contributions | **Implemented** | `ai_decision.py` — top 3 feature drivers shown in ML line |
| 4 | Cross-candle microstructure | **Implemented** | `shared_state.py` + `agent.py` + `ai_decision.py` — CandleMicrostructure saved at rotation |
| 5 | Adaptive reflection | **Implemented** | `agent.py` — threshold 5 when losing (PnL < -$10), else 10 |
| 6 | Calibration bins | **Implemented** | `calibration.py` — BIN_WIDTH 5%→10%, MIN_SAMPLES 15→10 |
| 7 | Time-weighted exits | **Implemented** | `position_monitor.py` — dynamic_stop_loss() with linear time decay |
| 8 | BTC velocity/drawback | **Implemented** | `ai_decision.py` — _compute_btc_trajectory() from prefilter snapshots |
| 9 | Temperature 0.1 | **Implemented** | `config/default.yaml` — decision model temp 0.0→0.1, screening stays 0.0 |
| 10 | Ensemble disagreement | **Implemented** | `ai_decision.py` + `agent.py` — tracking + dashboard JSON |

---

*This analysis was conducted by systematically reading every Python source file, tracing data flow between components, cross-referencing with archived trading results, and applying AI engineering principles from production ML systems, reinforcement learning, and LLM application design.*
