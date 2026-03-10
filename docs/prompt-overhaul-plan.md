# Prompt Overhaul Plan

> **Goal:** Cut AI latency from 15-18s to <5s, make prompts data-driven instead of rule-driven.
> **Principle:** Code decides deterministic things. AI decides judgment things.

---

## Current Problems

| Problem | Impact |
|---------|--------|
| System prompt is 175 lines of trading philosophy | ~1500 tokens read on every call |
| Hard rules in prompt ("if spread > 8% HOLD") | Unreliable + should be code |
| Sizing rules duplicated (prompt AND code) | Wastes tokens, confuses AI |
| User message dumps raw text tables | ~1500 tokens of unstructured data |
| Feedback context (F1-F11) injected every call | ~500 tokens of historical text |
| 12 optional indicator sections as prose | Variable but often 200-400 tokens |
| **Total input** | **~2500-3500 tokens → 15-18s latency** |

---

## Architecture: Before vs After

```
CURRENT (rule-heavy):
  Monitor → raw data → AI reads 175-line rulebook + messy data → decision → code sizing
                        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
                        15-18s, 2500+ tokens, rules AI may ignore

AFTER (data-driven):
  Monitor → code pre-filters → structured JSON snapshot → AI judges → code sizes
            ~~~~~~~~~~~~~~~~   ~~~~~~~~~~~~~~~~~~~~~~~~   ~~~~~~~~~
            hard rules          <600 tokens               3-5s, pure reasoning
```

---

## What Moves to Code (pre-AI filters)

These are currently in the system prompt as instructions to the AI. They should be `if` statements that run before the AI is ever called.

| Current prompt rule | Code replacement |
|---|---|
| "If time < 15 seconds, HOLD" | `if time_remaining < 15: skip()` |
| "If spread > 8%, prefer HOLD" | `if spread_pct > 0.08: skip()` |
| "NEVER buy if cash insufficient" | `if cash < estimated_cost: skip()` |
| "NEVER sell more than held" | `if sell_size > position_shares: cap()` |
| "One entry per candle per side" | `if already_entered_this_side: skip()` |
| "BTC move $0 = no signal" | `if abs(btc_move) < 1.0: skip()` |
| "Minimum expected profit > $0.01" | `if edge < 0.01: skip()` |

## What Moves to Code (post-AI sizing)

These are currently in the system prompt telling AI how to size. They should be mechanical adjustments applied after the AI returns its direction + confidence.

| Current prompt rule | Code replacement |
|---|---|
| R/R scaling (2.0→100%, 1.0→80%, 0.5→55%) | `size *= rr_scale(entry_price)` |
| Velocity conflict sizing (50-75%) | Already in code! Remove from prompt. |
| Reversal regime sizing (50-75%) | Already in code! Remove from prompt. |
| Counter-trend sizing (30-50%) | Already in code! Remove from prompt. |
| "20-100 shares reasonable range" | `size = clamp(ai_size, 20, 100)` |

---

## New Prompt Architecture

### Call #1: Screening (Haiku) — optional

**Purpose:** Binary gate — is this snapshot worth a full analysis?

> **Note:** If Sonnet latency drops to ~4-5s with the new data-driven prompts, consider
> removing this call entirely. The screening overhead (network round-trip + ~1s Haiku)
> may not justify the savings of skipping Sonnet on weak setups. Start with screening
> enabled, measure, then decide based on data.

**System prompt (~25 lines):**

```
You are a fast screening agent for a Polymarket BTC 5-minute candle market.

Each candle is a binary bet: UP token pays $1 if BTC closes >= open, DOWN pays $1 otherwise.
You receive a structured market snapshot. Decide if it's worth a full analysis.

## Indicator Reference

- time_remaining_s: seconds until candle resolves (300 = full candle, 0 = expired)
- btc_move: BTC price change from candle open in USD (positive = UP winning)
- btc_peak_move: largest favorable BTC move this candle (shows max conviction)
- btc_trough_move: largest adverse BTC move this candle
- zero_crossings: times BTC crossed candle open price (0 = directional, 3+ = choppy/reversal-prone)
- velocity: BTC rate of change in $/s (last 15s window)
- acceleration: change in velocity (positive = move strengthening)
- up_ask, up_bid: UP token best ask/bid (price = implied probability of UP winning)
- down_ask, down_bid: DOWN token best ask/bid
- spread_pct: bid-ask spread as fraction of midpoint (lower = more liquid)
- reversal_rate: fraction of recent candles where mid-candle leader reversed and lost
- streak_count, streak_direction: consecutive candles in same direction
- ml_score: ML model's UP probability (0.0-1.0)
- ml_drivers: top contributing features with signed weights
- has_position: whether we already hold tokens on this candle

Return true if the snapshot shows a strong enough setup to justify a full AI analysis.
Return false otherwise.
```

**User message:** Just the flat cross-candle fields + latest trajectory row. No full trajectory needed for screening.

```json
{
  "time_remaining_s": 247,
  "btc_move": -42.35,
  "btc_peak_move": 12.50,
  "btc_trough_move": -56.58,
  "zero_crossings": 2,
  "velocity": -1.8,
  "acceleration": -0.3,
  "up_ask": 0.38, "up_bid": 0.26,
  "down_ask": 0.75, "down_bid": 0.62,
  "spread_pct": 0.037,
  "reversal_rate": 0.45,
  "streak_count": 3, "streak_direction": "down",
  "ml_score": 0.31,
  "ml_drivers": "velocity: -0.4, spread: +0.1, momentum: -0.3",
  "has_position": false
}
```

**Tool schema:** Same as current (`should_trade: bool, reason: string`).

**Token estimate:** ~250 input tokens (system cached after first call).

---

### Call #2: Main Decision (Sonnet)

**Purpose:** Predict direction, choose token, set confidence. AI uses judgment across all signals.

**System prompt (~25 lines):**

```
You are a trading agent for Polymarket BTC 5-minute candle markets.
Each candle is a binary bet: winning token pays $1, losing token pays $0.

## Indicator Glossary

- trajectory: candle evolution as [elapsed_s, btc_move, up_ask, down_ask, velocity, spread_pct]
- reversal_rate: fraction of recent candles where mid-candle leader reversed and lost (0-1)
- streak_count/streak_direction: consecutive candles in same direction
- trend_score: EMA regime score (-1 bearish to +1 bullish)
- ma5_vs_ma12: short-term BTC crossover (bullish/bearish)
- decision_history: your last decisions with inputs, outputs, and W/L results. minutes_ago shows recency. Empty on session start.
- position: current holdings or null
- cash: available USD

Sizing is handled for you. Focus on DIRECTION and CONFIDENCE.
```

**Tools provided:**

```json
[
  {
    "name": "get_ml_prediction",
    "description": "An independent ML model (logistic regression) that predicts UP probability from market indicators. Returns its prediction score, the feature weights driving it, its recent accuracy, and last 5 predictions with results. Use as a second opinion — if ML and your read agree, that's high conviction. If they disagree, check accuracy to see if ML is hot or cold.",
    "input_schema": {
      "type": "object",
      "properties": {},
      "required": []
    }
  },
  {
    "name": "make_decision",
    "description": "Submit your trading decision",
    "input_schema": {
      "type": "object",
      "properties": {
        "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
        "token_side": {"type": "string", "enum": ["up", "down"]},
        "size": {"type": "number", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string", "description": "1-2 sentences max, 30 words"},
        "hypothetical_direction": {"type": "string", "enum": ["up", "down"]}
      },
      "required": ["action", "token_side", "size", "confidence", "reasoning", "hypothetical_direction"]
    }
  }
]
```

**Messages array:** 4 messages — user snapshot, pre-filled assistant tool call, pre-filled tool result, then AI responds.

```json
[
  {
    "role": "user",
    "content": "{\"time_remaining_s\":247,\"btc_peak_move\":12.50,\"btc_trough_move\":-56.58,\"zero_crossings\":2,\"trajectory\":[[0,0.00,0.50,0.50,0.0,0.02],[30,2.10,0.51,0.49,0.2,0.02],[60,5.80,0.53,0.47,0.4,0.02],[90,8.20,0.55,0.45,0.3,0.03],[120,12.50,0.58,0.42,0.7,0.03],[150,10.10,0.56,0.44,-0.2,0.03],[180,6.30,0.53,0.47,-0.4,0.03],[200,3.50,0.51,0.49,-0.3,0.04],[210,1.20,0.50,0.50,-0.2,0.04],[220,-2.30,0.49,0.51,-0.4,0.04],[230,-8.50,0.46,0.54,-0.6,0.04],[231,-9.10,0.45,0.55,-0.7,0.04],[232,-10.00,0.45,0.56,-0.8,0.04],[233,-12.30,0.44,0.57,-1.0,0.04],[234,-15.80,0.42,0.58,-1.2,0.04],[235,-20.10,0.41,0.60,-1.3,0.04],[236,-25.50,0.40,0.62,-1.5,0.03],[237,-30.20,0.39,0.65,-1.6,0.03],[238,-35.80,0.38,0.68,-1.7,0.03],[239,-38.90,0.38,0.70,-1.8,0.04],[240,-42.35,0.38,0.75,-1.8,0.04]],\"reversal_rate\":0.45,\"streak_count\":3,\"streak_direction\":\"down\",\"trend_score\":-0.35,\"ma5_vs_ma12\":\"bearish\",\"decision_history\":[{\"input\":{\"btc_move\":-38.5,\"velocity\":-1.6,\"ml_score\":0.28,\"reversal_rate\":0.40},\"output\":{\"side\":\"down\",\"confidence\":0.75,\"reasoning\":\"Strong downward momentum\"},\"result\":\"W\"},{\"input\":{\"btc_move\":8.2,\"velocity\":0.3,\"ml_score\":0.55,\"reversal_rate\":0.45},\"output\":{\"side\":\"up\",\"confidence\":0.60,\"reasoning\":\"Slight upward, ML neutral\"},\"result\":\"L\"}],\"position\":null,\"cash\":47.50}"
  },
  {
    "role": "assistant",
    "content": [
      {"type": "tool_use", "id": "ml_001", "name": "get_ml_prediction", "input": {}}
    ]
  },
  {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "ml_001",
        "content": "{\"score\":0.31,\"accuracy\":0.65,\"weights\":{\"velocity\":-0.40,\"spread\":0.10,\"momentum\":-0.30,\"depth_imbalance\":-0.15},\"recent\":[{\"predicted\":\"down\",\"result\":\"W\"},{\"predicted\":\"down\",\"result\":\"W\"},{\"predicted\":\"up\",\"result\":\"L\"},{\"predicted\":\"down\",\"result\":\"W\"},{\"predicted\":\"up\",\"result\":\"W\"}]}"
      }
    ]
  }
]
```

The AI then responds by calling `make_decision` with its trade.

**Why this works:**
- `get_ml_prediction` tool definition (in the `tools` array) is cached with the system prompt — free after first call
- The tool's `description` field teaches the AI what ml_scorer is and how to interpret it — no need for ml_scorer docs in the system prompt
- The pre-filled assistant + tool_result messages add no extra API round-trip
- Clean separation: market data (user message) vs ML opinion (tool result) vs trade action (make_decision)

**Token estimate:** ~500-600 input tokens (system + tool definitions cached after first call).

---

### Call #3: Reflection (Sonnet)

**Purpose:** Review recent outcomes, produce observations. This call is infrequent (every 5-10 candles) so latency matters less.

**Changes from current:**
- Keep the current reflection prompt structure (it's already mostly data-driven)
- Replace prose trade tables with structured JSON arrays
- Add the trajectory data for losing trades so the AI can see WHY it lost

**No major overhaul needed** — reflection runs between candles, not during execution.

---

## Trajectory: Adaptive Candle History

### The idea

Instead of giving AI a single snapshot (what the market looks like RIGHT NOW), give it the trajectory of the entire candle up to the current moment. This is the biggest signal improvement possible — the AI can see the **shape** of the move.

### Indicator split: candle-local vs cross-candle

Not all indicators belong inside the trajectory array. The split:

| Category | Where | Examples | Why |
|----------|-------|----------|-----|
| **Candle-local** | Inside `trajectory[]` | btc_move, up_ask, down_ask, velocity, spread_pct | These change every second within this candle |
| **Cross-candle** | Flat fields outside | reversal_rate, streak_count, trend_score, ml_score, ma5_vs_ma12 | These describe BTC's broader regime across candles — constant within a single candle |

This separation helps the AI understand what's "this candle's story" vs "the bigger picture."

### Adaptive sampling (3 tiers)

Uniform 10s sampling wastes resolution on old data and misses recent inflection points. Instead, use 3 tiers that prioritize recent data:

| Tier | Window | Interval | Rows | What it captures |
|------|--------|----------|------|------------------|
| **Recent** | Last ~10s | 1s | 10 | Current momentum, micro-reversals, exact shape of latest move |
| **Medium** | ~10s to ~110s ago | 10s | 10 | Mid-candle evolution, where peaks/troughs occurred |
| **Early** | ~110s to ~300s ago | 30s | 10 | Broad opening shape, initial direction |
| **Total** | | | **30** | Full candle coverage with adaptive density |

### Row format

Each row: `[elapsed_s, btc_move, up_ask, down_ask, velocity, spread_pct]`

6 values per row × 30 rows = ~180 tokens.

### Example (candle at t=240s)

```json
"trajectory": [
  // --- Early tier (30s intervals, candle open → ~130s) ---
  [0,    0.00,  0.50, 0.50,  0.0, 0.02],
  [30,  +2.10,  0.51, 0.49, +0.2, 0.02],
  [60,  +5.80,  0.53, 0.47, +0.4, 0.02],
  [90,  +8.20,  0.55, 0.45, +0.3, 0.03],
  [120, +12.50, 0.58, 0.42, +0.7, 0.03],
  // --- Medium tier (10s intervals, ~130s → ~230s) ---
  [140, +10.10, 0.56, 0.44, -0.2, 0.03],
  [150, +8.30,  0.55, 0.45, -0.3, 0.03],
  [160, +6.30,  0.53, 0.47, -0.4, 0.03],
  [170, +4.10,  0.52, 0.48, -0.3, 0.04],
  [180, +3.50,  0.51, 0.49, -0.3, 0.04],
  [190, +2.80,  0.51, 0.49, -0.1, 0.04],
  [200, +1.20,  0.50, 0.50, -0.2, 0.04],
  [210, -2.30,  0.49, 0.51, -0.4, 0.04],
  [220, -8.50,  0.46, 0.54, -0.6, 0.04],
  [230, -15.80, 0.42, 0.58, -1.2, 0.04],
  // --- Recent tier (1s intervals, last ~10s) ---
  [231, -17.50, 0.42, 0.59, -1.3, 0.04],
  [232, -20.10, 0.41, 0.60, -1.3, 0.04],
  [233, -23.30, 0.40, 0.61, -1.4, 0.04],
  [234, -25.50, 0.40, 0.62, -1.5, 0.03],
  [235, -28.80, 0.39, 0.63, -1.5, 0.03],
  [236, -30.20, 0.39, 0.65, -1.6, 0.03],
  [237, -33.10, 0.38, 0.67, -1.7, 0.03],
  [238, -35.80, 0.38, 0.68, -1.7, 0.03],
  [239, -38.90, 0.38, 0.70, -1.8, 0.04],
  [240, -42.35, 0.38, 0.75, -1.8, 0.04]
]
```

Notice how the last 10 rows (1s intervals) show the sell-off accelerating — something invisible at 10s uniform sampling. Meanwhile the early 30s intervals still show the opening rally that peaked at t=120.

### Why adaptive beats uniform

| Approach | Rows | Resolution on last 10s | Tokens | Miss recent inflections? |
|----------|------|------------------------|--------|--------------------------|
| Uniform 10s | 30 | 1 row | ~150 | Yes — a 10s gap hides micro-reversals |
| Uniform 1s | 300 | 10 rows | ~1500 | No — but way too many tokens |
| **Adaptive 3-tier** | **30** | **10 rows** | **~180** | **No — best of both worlds** |

### Why not every second?

- 300 rows × 6 values = ~1800 tokens — kills the latency benefit
- Most of the early candle data is redundant at 1s resolution
- Adaptive gives 10x recent resolution with the same row count as uniform 10s

### Edge cases

- **Early in candle (t < 30s):** Only recent tier exists. All 30 rows at 1s intervals from what's available.
- **Mid candle (t < 120s):** Recent + medium tiers. Early tier has fewer rows, fill remaining with medium.
- **Full candle (t ≥ 240s):** All 3 tiers fully populated as shown above.

---

## Decision History: AI Self-Calibration

### The idea

Send the last 5 decisions with their full context: what the AI saw, what it decided, and what happened. This lets the AI review its own reasoning and recalibrate in real-time — not just "W, L, W" but "I saw X, I reasoned Y, and I was wrong because Z."

### Format

Each entry is a compressed version of the input snapshot + AI output + resolution:

```json
"decision_history": [
  {
    "minutes_ago": 25,
    "input": {
      "time_remaining": 195,
      "btc_move": -38.5,
      "velocity": -1.6,
      "ml_score": 0.28,
      "spread_pct": 0.04,
      "reversal_rate": 0.40,
      "trend_score": -0.30
    },
    "output": {"side": "down", "confidence": 0.75},
    "result": "W",
    "resolution_move": -52.10
  },
  {
    "minutes_ago": 15,
    "input": {
      "time_remaining": 220,
      "btc_move": +8.2,
      "velocity": +0.3,
      "ml_score": 0.55,
      "spread_pct": 0.06,
      "reversal_rate": 0.45,
      "trend_score": -0.20
    },
    "output": {"side": "up", "confidence": 0.60},
    "result": "L",
    "resolution_move": -12.30
  }
]
```

### What the AI can learn from this

Looking at the two entries above, the AI can see:
- "15 min ago I picked UP on a weak move (+8.2, velocity +0.3), low confidence (0.60), and LOST."
- "25 min ago I picked DOWN on a strong move (-38.5, velocity -1.6), high confidence (0.75), and WON."
- "Both had similar reversal_rate (~0.40-0.45). The difference was move strength."
- "I should require stronger conviction signals before entering."

### Compressed fields

| Field | Why included |
|-------|-------------|
| `minutes_ago` | Recency — recent decisions are more relevant than stale ones |
| `time_remaining` | Was it an early or late entry? |
| `btc_move` | How big was the signal? |
| `velocity` | Was momentum behind the move? |
| `ml_score` | What did ML think? |
| `spread_pct` | Was liquidity good? |
| `reversal_rate` | What regime was it? |
| `trend_score` | What was the macro direction? |

`output.reasoning` is intentionally excluded — the AI can infer "why" from the input fields + side + confidence. Dropping it saves ~75-100 tokens across 5 entries.

8 input fields + 2 output fields + 2 result fields + 1 recency = ~75 tokens per entry × 5 = **~375 tokens**.

### Storage

Decision history lives in the existing `knowledge/` system:
- After each candle resolves, append `{minutes_ago, input, output, result}` to a rolling buffer
- `build_decision_history(last_n=5) → list[dict]` in the snapshot builder
- `minutes_ago` computed at build time from decision timestamp vs now
- `output` stores only `{side, confidence}` — reasoning is dropped to save tokens
- Data comes from: snapshot at decision time (already logged) + AI response (already logged) + resolution (already tracked)

**Cold start:** When `decision_history` is empty (first candles of a session), an empty array `[]` is sent. The system prompt notes this is normal on session start.

---

## Combined API Call Example

Putting it all together — system prompt + tools + user message + pre-filled ml_scorer tool result:

```python
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=300,
    temperature=0,
    system="You are a trading agent for Polymarket BTC 5-minute candle markets...",  # cached
    tools=[
        {
            "name": "get_ml_prediction",
            "description": "An independent ML model (logistic regression) that predicts UP probability...",
            "input_schema": {"type": "object", "properties": {}, "required": []}
        },
        {
            "name": "make_decision",
            "description": "Submit your trading decision",
            "input_schema": { ... }
        }
    ],
    messages=[
        # 1. Market snapshot (user message)
        {
            "role": "user",
            "content": json.dumps({
                "time_remaining_s": 247,
                "btc_peak_move": 12.50,
                "btc_trough_move": -56.58,
                "zero_crossings": 2,
                "trajectory": [
                    [0, 0.00, 0.50, 0.50, 0.0, 0.02],
                    [30, 2.10, 0.51, 0.49, 0.2, 0.02],
                    # ... 30 rows adaptive sampling ...
                    [240, -42.35, 0.38, 0.75, -1.8, 0.04]
                ],
                "reversal_rate": 0.45,
                "streak_count": 3,
                "streak_direction": "down",
                "trend_score": -0.35,
                "ma5_vs_ma12": "bearish",
                "decision_history": [
                    {
                        "minutes_ago": 25,
                        "input": {"btc_move": -38.5, "velocity": -1.6, "ml_score": 0.28, "reversal_rate": 0.40},
                        "output": {"side": "down", "confidence": 0.75},
                        "result": "W"
                    },
                    {
                        "minutes_ago": 15,
                        "input": {"btc_move": 8.2, "velocity": 0.3, "ml_score": 0.55, "reversal_rate": 0.45},
                        "output": {"side": "up", "confidence": 0.60},
                        "result": "L"
                    }
                ],
                "position": None,
                "cash": 47.50
            })
        },
        # 2. Pre-filled: AI "called" get_ml_prediction
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "ml_001", "name": "get_ml_prediction", "input": {}}
            ]
        },
        # 3. Pre-filled: ML scorer result
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "ml_001",
                    "content": json.dumps({
                        "score": 0.31,
                        "accuracy": 0.65,
                        "weights": {"velocity": -0.40, "spread": 0.10, "momentum": -0.30, "depth_imbalance": -0.15},
                        "recent": [
                            {"predicted": "down", "result": "W"},
                            {"predicted": "down", "result": "W"},
                            {"predicted": "up", "result": "L"},
                            {"predicted": "down", "result": "W"},
                            {"predicted": "up", "result": "W"}
                        ]
                    })
                }
            ]
        }
        # 4. AI responds by calling make_decision
    ]
)
```

**API params:** `temperature=0` for deterministic, repeatable decisions.

**Token breakdown:**

| Component | Tokens | Cached? |
|-----------|--------|---------|
| System prompt | ~250 | Yes — free after first call |
| Tool definitions (get_ml_prediction + make_decision) | ~150 | Yes — cached with system |
| User message (trajectory + cross-candle + decision_history) | ~655 | No — changes every call |
| Pre-filled assistant tool_use | ~20 | No |
| Pre-filled tool_result (ml_scorer data) | ~100 | No |
| **Total input** | **~1175** | **~775 variable** |

---

## Token Budget Comparison

| Component | Current | After | Notes |
|-----------|---------|-------|-------|
| System prompt (screening) | ~400 | ~200 (cached) | |
| User message (screening) | ~300 | ~150 | |
| System prompt (main) | ~1500 | ~250 (cached) | Slim glossary — ml_scorer docs in tool description |
| Tool definitions | — | ~150 (cached) | get_ml_prediction + make_decision schemas |
| User message (main) | ~1500 | ~655 | trajectory ~180 + cross-candle ~100 + decision_history ~375 |
| Pre-filled tool result (ml_scorer) | — | ~120 | assistant tool_use + tool_result messages |
| **Total screening** | **~700** | **~350** | |
| **Total main decision** | **~3000** | **~1175** | ~60% reduction from current |

### Token breakdown of main decision input

| Section | Tokens | Cached? | Purpose |
|---------|--------|---------|---------|
| System prompt | ~250 | Yes | Indicator glossary + output instructions only |
| Tool definitions | ~150 | Yes | get_ml_prediction description teaches AI what ML is |
| Trajectory (30 rows × 6 values) | ~180 | No | Candle shape — what happened this candle |
| Cross-candle fields | ~100 | No | Regime context — streak, reversal_rate, trend |
| `decision_history` (5 entries) | ~375 | No | Self-calibration — inputs + side + confidence + result + recency |
| Pre-filled ml_scorer tool result | ~120 | No | ML score, weights, accuracy, recent predictions |
| **Total** | **~1175** | | **~775 variable (latency-relevant)** |

### Latency breakdown

| Component | Current | After | Notes |
|-----------|---------|-------|-------|
| System prompt read | ~3-4s | ~0s | Cached after first call (Anthropic prompt caching) |
| User message processing | ~8-10s | ~2-3s | ~775 variable tokens vs ~1500 tokens |
| Output generation | ~4-5s | ~1-2s | `temperature=0` + reasoning capped at 30 words |
| **Total Sonnet** | **15-18s** | **4-6s** | |
| Haiku screening | ~1-2s | ~1s | May be removed entirely (see below) |
| **Total pipeline** | **17-20s** | **4-6s** | Without screening; 5-7s with |

> **Note:** decision_history adds ~375 tokens (~2s) vs the minimal snapshot. This is a deliberate trade-off:
> better decisions (self-calibration) vs slightly more latency. If latency is too high, reduce to 3 entries (~225 tokens).
>
> **Important:** Benchmark with real API calls before committing. Run 50 calls with the exact payload format
> and measure p50/p95 latency. If p95 > 8s, reduce decision_history to 3 entries.

### Should we keep the Haiku screening pass?

| Option | Latency | Cost/candle | When it helps |
|--------|---------|-------------|---------------|
| **Keep screening** | +1-2s per call | Saves ~$0.001 on skipped Sonnet calls | High-volume: 50%+ of snapshots are clearly no-trade |
| **Drop screening** | 0s overhead | +$0.001 per skipped snapshot | If Sonnet is fast enough (~5s), the 1-2s screening overhead isn't worth it |

**Recommendation:** Start with screening enabled. After collecting latency data on the new prompts, drop it if Sonnet consistently hits <5s. Config flag: `screening_enabled: true | false`.

---

## Migration Plan

### Phase 1: Build the snapshot builder

Create `src/polybot/execution/snapshot.py` that produces the structured JSON from existing data:

**Trajectory builder:**
- Reads from the per-second snapshot data already being recorded in the `snapshots` table
- Implements adaptive 3-tier sampling:
  - `_recent_tier(snapshots, n=10)` → last 10 snapshots at 1s intervals
  - `_medium_tier(snapshots, n=10)` → every 10th snapshot before the recent tier
  - `_early_tier(snapshots, n=10)` → every 30th snapshot before the medium tier
- Each row: `[elapsed_s, btc_move, up_ask, down_ask, velocity, spread_pct]`
- Handles edge cases: early candle (< 30s), mid candle (< 120s)

**Indicator split:**
- `build_trajectory(snapshots) → list[list]` — candle-local data (inside the array)
- `build_cross_candle_context(candle_history, ml_result, ...) → dict` — cross-candle data (flat fields)
- `build_decision_history(last_n=5) → list[dict]` — compressed past decisions with input/output/result
- `build_ml_tool_result(ml_result) → dict` — ML score, accuracy, feature weights, recent predictions (for pre-filled tool result)
- `build_messages(snapshot, ml_result) → list[dict]` — assembles the full messages array: user snapshot + pre-filled assistant tool_use + pre-filled tool_result

**Cross-candle fields (in user message):** `reversal_rate`, `streak_count`, `streak_direction`, `trend_score`, `ma5_vs_ma12`, `decision_history`, `position`, `cash`, `time_remaining_s`

**Candle summary fields (in user message, derivable from trajectory but kept as convenience):** `zero_crossings`, `btc_peak_move`, `btc_trough_move`

**ML scorer fields (in pre-filled tool result):** `score`, `accuracy`, `weights`, `recent`

**Candle-local fields (in trajectory):** `btc_move`, `up_ask`, `down_ask`, `velocity`, `spread_pct`

### Phase 1b: Decision history storage

Extend the existing knowledge system to persist decision context for history:
- After each AI decision, store compressed input snapshot + AI output to a rolling buffer
- After each candle resolves, append the result (W/L, resolution_move)
- `DecisionRecord` dataclass: `{timestamp: float, input: dict, output: {side, confidence}, result: str, resolution_move: float}`
- `minutes_ago` computed dynamically at build time, not stored
- Storage: append to `data/knowledge/decision_history.jsonl` (one JSON line per resolved decision)
- Rolling window: keep last 100 decisions in file, load last 5 for snapshot

### Phase 2: New prompts

- Write new `SCREENING_PROMPT_V2` and `SYSTEM_PROMPT_V2` in `decision_engine/prompts.py`
- System prompt explains:
  - 2-part structure (trajectory[] + flat fields)
  - Adaptive sampling tiers
  - `decision_history` — what it contains, how to use it for self-calibration
- Define `get_ml_prediction` tool with description that teaches AI what ml_scorer is
- Build `build_messages()` that assembles: user snapshot → pre-filled tool_use → pre-filled tool_result
- Write `format_snapshot_json()` replacing `format_feature_vector()` and `format_screening_context()`
- Feature flag: `prompt_version: "v1" | "v2"` in config
- Add `screening_enabled: true | false` config flag

### Phase 3: Move rules to code

- Audit every rule in current system prompt
- Confirm each has a code equivalent (pre-filter or post-sizing)
- Add any missing code checks
- Remove from prompts

### Phase 3b: Latency benchmark

Before A/B testing, benchmark the new prompt with real API calls:
- Run 50 calls with the exact v2 payload format (trajectory + decision_history + ml tool result)
- Measure p50 and p95 latency with `temperature=0`
- If p95 > 8s: reduce `decision_history` to 3 entries, re-benchmark
- If p95 > 10s: drop `decision_history` entirely, rely on reflection for calibration
- Document results for Phase 4 comparison baseline

### Phase 4: A/B test

- Run v1 and v2 side-by-side (paper mode)
- Compare: latency, decision quality, fill rate, PnL
- Measure: does the AI make DIFFERENT decisions with less prompt context?
- Measure: does decision_history improve win rate? (compare with/without)
- Measure: does exposing ml_scorer weights/accuracy change AI behavior?
- Measure: Sonnet latency with new prompts — if consistently <5s, disable screening

### Phase 5: Deprecate v1

- Remove old prompt constants
- Remove `format_feature_vector()` and `format_screening_context()`
- Clean up indicator text builders that are no longer needed
- If screening disabled in Phase 4, remove screening prompt and Haiku call path

### Phase 5b: Streaming early-action execution

**Goal:** Fire orders as soon as `action` + `token_side` + `confidence` stream in, without waiting for `reasoning` to finish generating.

**How it works:**

The Anthropic API supports [fine-grained tool streaming](https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming) — setting `eager_input_streaming: true` on the `make_decision` tool streams the JSON fields as they're generated, token by token.

Since Claude generates tool JSON fields roughly in schema-property order, reordering the schema puts execution-critical fields first:

```
Stream arrives: {"action":"BUY","token_side":"down","confidence":0.78,"size":50,
                  ↑ fire order here (all 4 execution fields received)
                 "reasoning":"Strong downward momentum with...","hypothetical_direction":"down"}
                  ↑ reasoning arrives later — log it, but order is already placed
```

**Schema field ordering (execution-critical first):**

```json
{
  "properties": {
    "action": { ... },
    "token_side": { ... },
    "confidence": { ... },
    "size": { ... },
    "reasoning": { ... },
    "hypothetical_direction": { ... }
  },
  "required": ["action", "token_side", "confidence", "size", "reasoning", "hypothetical_direction"]
}
```

**Implementation:**

1. **Enable streaming on `make_decision` tool:**
   ```python
   {
       "name": "make_decision",
       "eager_input_streaming": True,
       "input_schema": { ... }  # action, token_side, confidence, size first
   }
   ```

2. **New streaming parser** — accumulates partial JSON chunks, attempts incremental parse after each chunk:
   ```python
   async for event in stream:
       if event is input_json_delta:
           buffer += event.partial_json
           parsed = try_parse_partial(buffer)
           if parsed and has_execution_fields(parsed) and not order_fired:
               await fire_order(parsed)  # action, token_side, confidence, size
               order_fired = True
   # After stream completes: extract full decision (with reasoning)
   ```

3. **Confidence gate still applies** — order only fires once `confidence` field is fully parsed and passes `min_confidence`. If confidence is below gate, wait for stream to finish and return HOLD as usual.

4. **Fallback on partial JSON** — if stream hits `max_tokens` or disconnects before execution fields arrive, treat as HOLD (same as current exception handling).

**Latency savings:** Reasoning is typically 15-30 tokens (~0.5-1s of generation). On a 4-6s total call, this saves ~10-20% of wall-clock time on the execution path. The real win is that the order hits the CLOB while Claude is still writing the explanation.

**Files touched:**
- `src/polybot/decision_engine/engine.py` — streaming `decide()` variant
- `src/polybot/decision_engine/schemas.py` — reorder properties, add `eager_input_streaming`
- `src/polybot/tasks/ai_decision.py` — consume streaming result, fire order on partial

### Phase 6: Fine-tuning (future)

Once enough data is collected (1000+ resolved decisions):
- Export (snapshot → correct_decision) pairs as fine-tuning dataset
- Fine-tune Sonnet on historical data — bakes domain knowledge into weights
- Shrink system prompt further (model already knows indicator meanings)
- `decision_history` still useful even with fine-tuning (recent self-calibration)
- Retrain monthly to avoid model drift as market regimes shift
