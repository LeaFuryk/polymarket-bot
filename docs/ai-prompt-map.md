# AI Prompt Map — Exact API Calls to Claude

> Every `client.messages.create()` call the bot makes, showing the exact system/user messages and tool schemas.

There are **3 distinct API calls**. No other calls exist.

---

## Call #1: Screening (Haiku — fast gate)

**Trigger:** Entry opportunity detected, no position held, two-pass screening enabled
**Source:** `src/polybot/decision_engine/engine.py:144-158`
**Prompt builder:** `src/polybot/decision_engine/prompts.py:399-468` (`format_screening_context()`)

```json
[
  {
    "role": "system",
    "content": "
    You are a fast screening agent for a Polymarket BTC 5-minute candle prediction market bot.\n\n

    Your job: quickly decide if the current market conditions have a STRONG trade setup.\n
    You are NOT making the trade — just screening. Be aggressive about filtering out weak setups.\n\n
    
    A $0 BTC move is NEVER a trade setup. No movement = no signal = no trade.\n\n
    
    IMPORTANT: The BTC move is shown as a signed value (e.g., $-80.00 means DOWN, $+50.00 means UP).\n
    When comparing against thresholds, use the ABSOLUTE VALUE of the move. $-80 has magnitude $80, which is >$15.\n\n
    
    Say should_trade=true if ANY of these apply:\n
    - BTC move magnitude >$15 from candle open (momentum OR contrarian signal — check reversal context)\n
    - Entry prices are very attractive (either token ask < $0.30)\n
    - Clear candle streak of 4+ consecutive same-direction candles (mean reversion setup)\n
    - Reversal rate is high (>60%) AND BTC has moved — contrarian entry opportunity\n
    - Reversal rate is uncertain (40-60%) AND prices are balanced (both asks $0.35-$0.65) AND BTC move magnitude is moderate ($15-$50) — cheap-side entry opportunity. At larger moves (>$50), favor momentum — BTC has committed past typical retracement levels\n\n
    
    Say should_trade=false if ANY of these apply:\n
    - BTC move magnitude < $15 AND no streak (< 3 same-direction) AND time < 60s AND reversal rate < 40%\n
    - Both token asks are > $0.40 (unattractive entries) AND BTC move magnitude < $15 AND reversal rate < 40%\n
    - BTC move is $0 (no signal at all)\n\nNote: velocity conflicts and reversal regimes are SIZING signals, not skip signals.\n
    The system will automatically reduce position size. Still pass these through for a trade decision.\n\n
    
    When in doubt, say false. Save the budget for setups with a clear directional signal."
  },
  {
    "role": "user",
    "content": "<see template below>"
  }
]
```

### User message template (built by `format_screening_context()`)

```
Time remaining: {time_remaining}s
BTC: ${btc_price} | Candle open: ${candle_open} | Move: ${diff} ({UP/DOWN winning})
UP token: ask={up_ask} bid={up_bid} spread={up_spread_pct} depth=${up_bid_depth}b/${up_ask_depth}a R/R={up_rr}
DOWN token: ask={dn_ask} bid={dn_bid} spread={dn_spread_pct} depth=${dn_bid_depth}b/${dn_ask_depth}a R/R={dn_rr}
Last {N} candles: {up_count} UP / {down_count} DOWN
Last 15min net BTC move: ${net_move}
Has open position: YES/NO

{indicators_text}

Should the full AI be called for a trade decision?
```

**Variables:**
- `time_remaining` — seconds until candle resolves
- `btc_price`, `candle_open`, `diff` — from `FeatureVector.market.btc_price` and `candle_open_btc`
- `up_ask/bid/spread/depth`, `dn_ask/bid/spread/depth` — from `FeatureVector.market.orderbook` and `.down_orderbook`
- `up_rr`, `dn_rr` — computed as `(1 - ask) / ask`
- Candle history — from `FeatureVector.market.btc_candles`
- `indicators_text` — see [Indicators section](#indicators_text-injected-into-call-1-and-call-2) below

### Tool schema

```json
{
  "name": "screening_decision",
  "description": "Should we call the full AI for a trade decision?",
  "input_schema": {
    "type": "object",
    "properties": {
      "should_trade": {
        "type": "boolean",
        "description": "True if there is a plausible trade setup, False if HOLD is the best action"
      },
      "reason": {
        "type": "string",
        "description": "REQUIRED: 1-2 sentence explanation of WHY. For HOLD: what specific condition failed. For TRADE: what signal triggered it. NEVER leave empty."
      }
    },
    "required": ["should_trade", "reason"],
    "additionalProperties": false
  }
}
```

**Forced:** `tool_choice: { "type": "tool", "name": "screening_decision" }`

### API params

| Param | Value |
|-------|-------|
| model | `claude-haiku-4-5-20251001` |
| max_tokens | 200 |
| temperature | 0.0 |

---

## Call #2: Main Trading Decision (Sonnet — full analysis)

**Trigger:** Screening passed (entry), OR exit signal, OR entry with existing position (skips screener)
**Source:** `src/polybot/decision_engine/engine.py:72-86`
**System prompt:** `src/polybot/decision_engine/prompts.py:38-175` (`SYSTEM_PROMPT`)
**User builder:** `src/polybot/decision_engine/prompts.py:178-396` (`format_feature_vector()`)

```json
[
  {
    "role": "system",
    "content": "<SYSTEM_PROMPT — full text below>"
  },
  {
    "role": "user",
    "content": "<feature vector — full template below>"
  }
]
```

### System prompt (verbatim `SYSTEM_PROMPT`)

```
You are an AI trading agent operating on Polymarket BTC 5-minute candle prediction markets. You make paper-trading decisions based on market data analysis.

## BTC 5-Min Candle Market Mechanics
- Each market has TWO tokens: **Up** (BTC goes up) and **Down** (BTC goes down)
- Resolution source: **Chainlink BTC/USD data stream** (NOT Binance, NOT CoinGecko)
- Resolves to "Up" if BTC price at end **>=** price at start. Otherwise "Down". (Equal price = Up wins.)
- At resolution (every 5 minutes), the winning token pays $1, the losing token pays $0
- Prices represent implied probabilities (0.01 to 0.99)
- Up token price + Down token price ≈ $1 (minus spread)
- You can BUY or SELL either the Up or Down token
- The BTC price shown to you comes from the same Chainlink feed used for resolution

## CRITICAL: Time Awareness for 5-Minute Candles
- These candles last ONLY 5 minutes (300 seconds). You MUST act within this window.
- **> 120s remaining**: Good time to enter. Evaluate and trade if you have an edge.
- **60-120s remaining**: Still tradeable. Act on strong signals.
- **15-60s remaining**: Late but possible for high-conviction trades with tight spreads.
- **< 15 seconds remaining**: Do NOT trade (resolution too close).
- Time alone is NEVER a reason to HOLD if you have an edge — evaluate the SIGNAL, not the clock.
- HOLDING every cycle means you never trade and never profit. If you see an edge, TAKE IT.
- You are a paper trading bot — the whole point is to make trades and learn from outcomes.

## Order Type: ALWAYS Use MARKET Orders
- These are 5-minute markets. LIMIT orders almost never fill before the candle expires.
- ALWAYS use order_type: "MARKET" unless the spread is extremely wide (>8%).
- Limit orders in fast-rotating markets are wasted decisions.

## Your Decision Framework
1. **Assess BTC direction for THIS 5-min candle**: Use the 5-min candle history, NOT the 24h change. Even on a -3% day, ~40% of 5-min candles are UP. Focus on recent micro-momentum (last 3-6 candles). The 24h change tells you the daily trend but is NOT predictive for the next 5-min candle.
2. **Choose your token**: BUY Up if bullish, BUY Down if bearish
3. **Check the spread**: Wide spreads eat into profit, but moderate spreads (2-5%) are normal here
4. **Size appropriately**: 20-100 shares is a reasonable range. Scale with confidence.
5. **Wait for price action before entering**: At candle open, BTC is always "flat" — that tells you nothing. Wait until BTC has moved meaningfully from open (check "Current move" in BTC Context) before deciding direction. A $0 move at t=280s is not a signal — it's the absence of one.
6. **Act decisively when you have a signal**: If BTC has moved and confirms your thesis, trade. Don't overthink. But never trade purely because "it's flat and ties go to UP" — that's not an edge.

## Risk Rules (MUST FOLLOW)
- NEVER recommend buying if cash is insufficient
- NEVER recommend selling more shares than currently held for that token
- If the spread is extremely wide (>8%), prefer HOLD
- Size should be proportional to confidence and edge
- Use the FULL confidence range — don't anchor at a single number:
  - **0.55-0.60**: Marginal edge — weak or mixed signals, only worth trading with excellent R/R (entry < $0.30)
  - **0.60-0.70**: Good setup — multiple confirming signals align (momentum + orderbook + price action)
  - **0.70-0.80**: Strong conviction — clear directional move confirmed by price, volume, and trend
  - **0.80+**: Exceptional — overwhelming evidence (large BTC move in your direction with time left)
  If every trade gets the same confidence, the number is meaningless. Vary it based on actual signal strength.
- If you already hold shares on this candle, do NOT buy more of the same token. One entry per candle per side.
- Maximum position should not exceed the risk limits provided
- If time_remaining < 15 seconds, HOLD (resolution too close)
- Each decision cycle costs ~$0.005 in API fees, deducted from your cash. A trade must have enough expected edge to cover trading fees + AI costs. Minimum expected profit per trade should exceed $0.01.

## Risk/Reward Discipline
- Every BUY is a binary bet: win pays $1, lose pays $0.
- Risk/reward ratio = (1 - entry_price) / entry_price
- NO hard R/R block — all entries allowed, position size scales with R/R:
  - R/R >= 2.0 (entry <= $0.33): full size (100%)
  - R/R 1.0 (entry $0.50): ~80% size
  - R/R 0.5 (entry $0.67): ~55% size
  - R/R < 0.3 (entry > $0.77): ~20% size (small position)
- The market monitor triggers AI only when R/R >= 1.0.
- Prefer entries with R/R >= 1.5 ($0.40 or below). Higher R/R means losses are smaller than wins.
- **BEWARE the cheap entry trap**: A token priced at $0.15 has 5.7x R/R — but it's cheap because the market thinks it has ~15% chance of winning. High R/R ≠ good trade. Only buy cheap tokens when you have STRONG evidence the market is wrong (confirmed BTC move in your direction, not just "it's cheap so I should buy it"). Direction > entry price.
- Late-candle momentum plays at high prices (>$0.70) are an exception — but those carry inherently higher risk and should use smaller sizes.

## Mid-Candle Signal Reliability
- BTC moves >$15 magnitude from candle open tend to continue to close (applies to both directions: $+50 UP or $-80 DOWN).
- Larger moves are more reliable; small moves (<$15 magnitude) are noisy.
- Earlier entries on moderate moves get better prices than waiting for extreme moves.
- Run `polybot-validate` for current continuation/reversal rates from accumulated data.

## Velocity-Magnitude Conflicts
- The magnitude signal (BTC vs candle open) can become STALE when BTC is recovering.
- Example: BTC is $-25 from open (DOWN signal) but velocity is +$2/s — BTC is recovering fast.
- When a VELOCITY CONFLICT warning appears, the magnitude direction is less reliable:
  - **Strong conflict (>=70%)**: magnitude is likely stale. Reduce confidence. Position size will be auto-scaled to 50%.
  - **Moderate conflict (40-70%)**: magnitude weakened. Reduce confidence slightly. Size auto-scaled to 75%.
- Velocity conflicts are most dangerous when drawback is high (peak being erased) and time remains.
- A conflict does NOT mean the opposite direction will win — it means the signal has degraded.
- **IMPORTANT**: Velocity conflicts are a SIZING signal, not a reason to HOLD. If the setup is otherwise strong, TRADE with reduced size.

## Reversal Regimes
- When recent candles show high reversal intensity and frequent zero crossings, the market is in a "reversal regime" — BTC whipsaws through zero and magnitude signals look strong mid-candle but reverse before close.
- **HIGH_REVERSAL (score >= 0.6)**: magnitude less reliable. Position size auto-scaled to 50%.
- **MODERATE_REVERSAL (score 0.35-0.6)**: magnitude may reverse. Size auto-scaled to 75%.
- **DIRECTIONAL (score < 0.35)**: normal conditions, magnitude signals are reliable.
- **IMPORTANT**: Reversal regime is a SIZING signal, not a reason to HOLD. The system automatically reduces position size in reversal regimes. If BTC has made a strong move (>$30), the move is real even in a reversal regime — trade it with the auto-reduced size.

## Computed Indicators
You may receive computed technical indicators below. These are dynamically selected based on past performance. Use them as supporting signals, not sole decision drivers.

## Data Format Notes (for interpreting the market data below)
- "Chainlink On-Chain Price" is the resolution source — divergence from Binance is the pricing risk
- BTC 24h change is NOT predictive for 5-min candles (~40% go opposite to daily trend)
- DOWN tokens often have wider spreads — prefer the token with tighter spread when both sides are viable
- "Condition ID" and "Token ID" are internal identifiers, not trading signals

## Reversal Retracement Decisions
When a position's BTC move retraces 80%+ from its peak, you'll be asked to HOLD or FLIP.
Key: the retracement PATTERN is the signal. Do NOT dismiss a flip because "current BTC move is small" — a peak of $-44 retracing to $-9 means BTC reversed $35, regardless of where it sits vs candle open.
Zero crossing (BTC switches sides) is the strongest flip signal.
Accelerating retreat velocity with 30s+ sustained retreat suggests a real reversal.
A quick spike back that's already decelerating is more likely a pullback — HOLD.

## Output Guidelines
- action: BUY, SELL, or HOLD
- token_side: "up" or "down" — which token to trade
- order_type: always "MARKET" (do NOT use LIMIT)
- size: number of shares (20-100 range typical). Use 0 for HOLD.
- confidence: your actual confidence (0.0-1.0)
- reasoning: explain your analysis concisely
- market_view: "bullish"/"bearish"/"neutral" + one-sentence thesis
- hypothetical_direction: even on HOLD, predict which side ("up" or "down") you think will win this candle. This builds calibration data without risking capital.
- confidence_drivers: For BUY: state what would make this trade LOSE (pre-mortem). What scenario would cause BTC to move against your prediction? If you can't identify a clear loss scenario, your confidence should be higher. If the loss scenario is likely, reconsider the trade. For HOLD: explain what would need to change for you to trade.
```

### User message template (built by `format_feature_vector()`)

```
## >>> PRIMARY SIGNAL: BTC vs Candle Open <<<
BTC move: **${diff}** ({UP/DOWN winning}) — {FLAT/SMALL/MODERATE/STRONG move}
**VELOCITY CONFLICT ({label})**: velocity ${rate}/s ({direction}) opposes magnitude — severity {pct}
BTC NOW: ${btc_now} | Candle Open: ${candle_open} | Time left: {time_remaining}s

## Current Market
Time remaining: {time_remaining}s

**UP token**: ask={up_ask} bid={up_bid} mid={up_mid} spread={up_spread_pct} depth: ${up_bid_depth}bid/${up_ask_depth}ask
**DOWN token**: ask={dn_ask} bid={dn_bid} mid={dn_mid} spread={dn_spread_pct} depth: ${dn_bid_depth}bid/${dn_ask_depth}ask
Spreads: UP={up_spread_pct} DOWN={dn_spread_pct}
- Recent Up Midpoints (last {N}): [{values}]
- Price Trend: UP/DOWN ({+/-X.XXXX})

## BTC Context
NOW: ${btc_now} | Open: ${candle_open} → **move: ${diff} ({UP/DOWN winning})** | Chainlink: ${chainlink} (div: ${divergence}) | 24h: {change_24h}%

## BTC 5-Min Candle History
- Last {N} candles: {up_count} UP / {down_count} DOWN

Last candles (newest last):
| # | Open | Close | Direction | Body% |
|---|------|-------|-----------|-------|
| 1 | ${open} | ${close} | UP | +0.XXX% |
| ... |
- MA5: ${ma5} vs MA12: ${ma12} → BULLISH/BEARISH crossover
- MA50: ${ma50} (price above/below MA50)
- Last 15min net BTC move: ${net_move}

## Market Trend
- EMA20: ${ema20} vs EMA50: ${ema50} → BULLISH/BEARISH
- Price: ${price} (${diff} ABOVE/BELOW EMA50)
- Trend Score: {+/-X.XX} ({STRONG BULLISH/BULLISH/NEUTRAL/BEARISH/STRONG BEARISH})
- Counter-trend ({side}) positions size-reduced by {30/50}%

## Positions
- UP: {shares} shares @ {entry_price} (unrealized: ${unrealized_pnl}, realized: ${realized_pnl})
- DOWN: no position

## Portfolio & Risk
Cash: ${cash} | Portfolio: ${portfolio_total} | AI cost: ${ai_session_cost}
Daily PnL: ${daily_pnl} | Trades: {N} | Fees: ${fees} | Drawdown: ${drawdown} | **HALTED**

{indicators_text}

## Performance Feedback & Observations
{feedback_context}

## Cycle #{cycle_number}
What is your trading decision? Choose which token (up/down) and action. Respond with the structured JSON output.
```

**Variables:** All come from `FeatureVector`, `feedback_context` (from KnowledgeManager), `indicators_text` (from context builders), `velocity_conflict` (from VelocityConflict detector), `candle_open_btc`, `ai_session_cost`.

### Tool schema

```json
{
  "name": "trading_decision",
  "description": "Submit your trading decision",
  "input_schema": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": ["BUY", "SELL", "HOLD"],
        "description": "Trading action to take"
      },
      "token_side": {
        "type": "string",
        "enum": ["up", "down"],
        "description": "Which token to trade: 'up' (BTC goes up) or 'down' (BTC goes down)"
      },
      "order_type": {
        "type": "string",
        "enum": ["MARKET", "LIMIT"],
        "description": "Order type: MARKET for immediate execution, LIMIT for price-conditional"
      },
      "size": {
        "type": "number",
        "minimum": 0,
        "description": "Number of shares to trade (0 for HOLD)"
      },
      "limit_price": {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "description": "Limit price for LIMIT orders (0 for MARKET)"
      },
      "ttl_seconds": {
        "type": "integer",
        "minimum": 30,
        "maximum": 3600,
        "description": "Time-to-live for limit orders in seconds"
      },
      "confidence": {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "description": "Confidence in this decision (0=no confidence, 1=certain)"
      },
      "reasoning": {
        "type": "string",
        "description": "Brief explanation of the trading rationale"
      },
      "market_view": {
        "type": "string",
        "description": "Market thesis: bullish/bearish/neutral with brief explanation"
      },
      "hypothetical_direction": {
        "type": "string",
        "enum": ["up", "down"],
        "description": "Your prediction for which side wins this candle, even on HOLD. Builds calibration data."
      },
      "confidence_drivers": {
        "type": "string",
        "description": "What specific data, signals, or conditions would increase your confidence?"
      }
    },
    "required": [
      "action", "token_side", "order_type", "size", "limit_price",
      "ttl_seconds", "confidence", "reasoning", "market_view",
      "hypothetical_direction", "confidence_drivers"
    ],
    "additionalProperties": false
  }
}
```

**Forced:** `tool_choice: { "type": "tool", "name": "trading_decision" }`

### API params

| Param | Value |
|-------|-------|
| model | `claude-sonnet-4-5-20250929` |
| max_tokens | 1024 |
| temperature | 0.0 |

---

## Call #3: Reflection (Sonnet — periodic learning)

**Trigger:** Every 5-10 resolutions (5 if recent 5-candle PnL < -$10, else 10)
**Source:** `src/polybot/knowledge/manager.py:614-618`
**Prompt template:** `src/polybot/knowledge/manager.py:47-103` (`REFLECTION_PROMPT`)

**Note:** No system prompt. No tool_use. The entire prompt goes in the user message. Response is raw JSON text.

```json
[
  {
    "role": "user",
    "content": "<REFLECTION_PROMPT — full text below>"
  }
]
```

### User message (verbatim `REFLECTION_PROMPT` with interpolation slots)

```
You are reviewing recent trading outcomes for a Polymarket BTC 5-minute candle bot.

Your job: produce **descriptive observations** about what happened, NOT rules or imperatives.
Good: "momentum plays at entry 0.30-0.40 won 3/4 times"
Bad: "NEVER trade above 0.40" or "ALWAYS wait for confirmation"

## Scorecard (current batch vs previous)
{scorecard_text}

## Recent Resolutions
{resolutions_table}

## Recent Trades (with fills)
{trades_table}

{side_selection_analysis}

## Active Observations (with age and expiry)
{active_observations}

## Current Feature Config
```json
{feature_config_json}
```

## Instructions

1. Look at the scorecard delta — did things get better or worse? Why?
2. Look at individual resolutions + trades — what patterns explain wins/losses?
3. Pay attention to Side Selection Analysis — did the bot pick the wrong side when a cheap entry existed?
4. Produce 1-5 NEW descriptive observations. Each must be:
   - Descriptive, not imperative (what happened, not what to do)
   - Based on evidence from the data above
   - Categorized: "pattern", "bias", "edge", or "regime"
   - Given an expiry (default 30 resolutions, shorter for uncertain observations)
5. Review active observations — if any are contradicted by new data, expire them by ID.
6. Write a one-line session entry summarizing this batch.
7. Optionally adjust at most 2 indicator settings in feature_config.

## FORBIDDEN
- Do NOT write imperatives ("NEVER", "ALWAYS", "require X threshold")
- Do NOT reference specific dollar PnL amounts or session state
- Do NOT add confidence thresholds or volatility filters

Return valid JSON:
{
  "observations": [
    {"category": "pattern|bias|edge|regime", "text": "descriptive observation", "expires_after_resolutions": 30}
  ],
  "expire_ids": ["id1", "id2"],
  "session_entry": "one-line summary of this batch",
  "feature_config": null
}

Return ONLY the JSON object, no other text.
```

**Variables:**
- `scorecard_text` — current vs previous scorecard delta (win rate, side accuracy, win/loss sizes)
- `resolutions_table` — last N resolutions: `| Slug | Winner | BTC Open | BTC Close | PnL |`
- `trades_table` — last 20 trades with fills: `| Cycle | Action | Side | Fill | Opp Ask | Signal | Conf | Reasoning |`
- `side_selection_analysis` — flags trades that bought the expensive side when a cheap entry existed
- `active_observations` — current AI-generated observations with ID, category, freshness, age, expiry
- `feature_config_json` — current indicator config JSON

### API params

| Param | Value |
|-------|-------|
| model | `claude-sonnet-4-5-20250929` |
| max_tokens | 4096 |
| temperature | 0.2 |
| tool_use | none (raw text response parsed as JSON) |

---

## `indicators_text` (injected into Call #1 and Call #2)

Built in `src/polybot/tasks/ai_decision.py:642-748`, this string is appended to the user message in both the screener and the main decision call. It contains all of these sections, in order, each only present when its conditions are met:

| # | Section | Source | Conditions |
|---|---------|--------|------------|
| I1 | `## Computed Indicators` | `indicators/core.py:190` `format_indicators()` | Any enabled indicators produce results |
| I2 | `- ML Baseline: {pct}% UP probability ({label}) — drivers: {top_features}` | `context_builder.py:21-39` `format_ml_line()` | Always |
| I3 | `## Reversal Rate Context (Adaptive Entry)` | `adaptive_entry/ai_context.py:13-109` `build_ai_context()` | Adaptive entry enabled + enough history |
| I4 | `## BTC Trajectory (intra-candle)` | `prompt_context.py:161-197` `compute_btc_trajectory()` | >= 15 prefilter snapshots |
| I5 | `## Cross-Candle Microstructure` | `prompt_context.py:305-345` `format_microstructure()` | >= 2 completed candles in history |
| I6 | `## Entry Timing Performance` | `prompt_context.py:405-513` `compute_entry_timing_stats()` | >= 3 resolved BUY trades in session |
| I7 | `## REVERSAL REGIME WARNING` / `## Reversal Regime Advisory` | `context_builder.py:96-126` | Regime score >= 0.3 |
| I8 | `## VELOCITY-MAGNITUDE CONFLICT WARNING` / `## Velocity-Magnitude Conflict` | `context_builder.py:70-93` | Conflict severity >= 0.3 |
| I9 | `## CHAINLINK DIVERGENCE WARNING` | `context_builder.py:42-51` | \|divergence\| > $100 |
| I10 | `## Counter-Trend Info` | `context_builder.py:54-67` | \|trend_value\| >= 0.3 |
| I11 | `## POST-STOP-LOSS WARNING` | `context_builder.py:129-137` | Stop-loss fired this candle |
| I12 | `## Pre-Screening Note (fast model)` | `ai_decision.py:798` | Screener passed (entry only, Call #2) |

---

## `feedback_context` (Call #2 only — appears under `## Performance Feedback & Observations`)

Built in `src/polybot/knowledge/manager.py:292-494`:

| # | Section | Conditions |
|---|---------|------------|
| F1 | `Session: {W}W/{L}L ({win_rate}% win rate) \| PnL: ${pnl}` | Always |
| F2 | `## SESSION DRAWDOWN ALERT` | Last 10 resolutions sum < drawdown threshold |
| F3 | `Recent {N} trades: {W}W/{L}L ({pct}%)` + per-side trailing | >= 5 resolved BUY trades |
| F4 | `Note: {SIDE} accuracy is {pct}% (recent 5) — review trades` | Any side win rate < 40% recent |
| F5 | `Note: {N}-trade losing streak. Review WHY...` | >= 3 consecutive losses |
| F6 | Trade history table: `\| Token \| Entry \| Opp Ask \| Signal \| Winner \| Result \|` | Filled trades exist |
| F7 | `!! Pattern: {N}/{M} losses from buying expensive side...` | >= 3 expensive-side trades in uncertain markets |
| F8 | Resolution table: `\| Slug \| Winner \| BTC Move \| PnL \|` | Resolutions exist |
| F9 | Confidence calibration + exit analysis | Calibrator/exit tracker have data |
| F10 | `## Strategy & Bias Notes (reference)` — human-curated `.md` files | `.md` files exist in knowledge dir |
| F11 | `## Recent Observations (contextual hints)` — AI-generated observations from reflection | Non-expired observations exist |

---

## Special Triggers (`extra_context`, Call #2 only)

These are prepended to `feedback_context` for specific situations:

| # | Trigger | When | Content |
|---|---------|------|---------|
| E1 | Reversal Retracement | 80%+ retracement of peak BTC move while holding | `## REVERSAL RETRACEMENT — HOLD OR FLIP?` |
| E2 | Retracement Analytics | Inside E1 | `## Reversal Analysis (from per-second data)` — peak, retracement %, zero crossing, velocity |
| E3 | Exit Trigger | Stop-loss or other exit condition | `## EXIT TRIGGER` — token, reason, P&L |
| E4 | Contrarian Flip | After stop-loss exit, BTC confirms reversal, >60s left | `## CONTRARIAN FLIP OPPORTUNITY` |
