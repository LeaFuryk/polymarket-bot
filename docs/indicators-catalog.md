# Indicators Catalog

> Every data point, computed metric, and signal available in the bot.
> Organized by: what it measures, where it comes from, and whether it should go to the AI.

---

## Raw Data (recorded per-second in `snapshots` table)

These are the foundation — everything else is derived from these.

| Field | What it measures | Source | Type |
|-------|-----------------|--------|------|
| `btc_price` | Current BTC/USD price | Chainlink feed / Binance | float ($) |
| `btc_move_from_open` | BTC price - candle open price | computed | float ($, signed) |
| `up_best_bid` | Highest buy offer for UP token | CLOB orderbook | float (0-1) |
| `up_best_ask` | Lowest sell offer for UP token | CLOB orderbook | float (0-1) |
| `up_mid` | (up_bid + up_ask) / 2 | computed | float (0-1) |
| `up_spread_pct` | (up_ask - up_bid) / up_mid | computed | float (0-1) |
| `up_bid_depth` | Total USD volume on UP bid side | CLOB orderbook | float ($) |
| `up_ask_depth` | Total USD volume on UP ask side | CLOB orderbook | float ($) |
| `down_best_bid` | Highest buy offer for DOWN token | CLOB orderbook | float (0-1) |
| `down_best_ask` | Lowest sell offer for DOWN token | CLOB orderbook | float (0-1) |
| `down_mid` | (down_bid + down_ask) / 2 | computed | float (0-1) |
| `down_spread_pct` | (down_ask - down_bid) / down_mid | computed | float (0-1) |
| `down_bid_depth` | Total USD volume on DOWN bid side | CLOB orderbook | float ($) |
| `down_ask_depth` | Total USD volume on DOWN ask side | CLOB orderbook | float ($) |
| `time_remaining` | Seconds until candle resolves | computed | float (0-300) |
| `rr_up` | Risk/reward for UP: (1 - ask) / ask | computed | float |
| `rr_down` | Risk/reward for DOWN: (1 - ask) / ask | computed | float |
| `prefilter_passed` | Whether prefilter gate passed | code | bool |
| `prefilter_reasons` | Why prefilter rejected (if applicable) | code | string |

---

## BTC Price Indicators (derived from per-second BTC prices)

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `btc_move` | Current BTC displacement from candle open | `btc_price - candle_open` | -∞ to +∞ ($) | Yes — primary signal |
| `btc_peak_move` | Largest positive BTC move this candle | `max(btc_move_history)` | 0 to +∞ ($) | Yes — shows max conviction |
| `btc_trough_move` | Largest negative BTC move this candle | `min(btc_move_history)` | -∞ to 0 ($) | Yes — shows max adverse |
| `velocity` | BTC rate of change ($/s) over last 15s | `(btc_now - btc_15s_ago) / 15` | -∞ to +∞ ($/s) | Yes — momentum direction |
| `acceleration` | Change in velocity over last 15s | `(velocity_now - velocity_15s_ago) / 15` | -∞ to +∞ | Yes — is move strengthening? |
| `zero_crossings` | Times BTC crossed the candle open price | count of sign changes in `btc_move` series | 0-∞ (int) | Yes — choppiness measure |
| `retracement_pct` | How much of peak move has been given back | `1 - (btc_move / btc_peak_move)` | 0-1+ | Yes — reversal detection |
| `time_at_peak` | Seconds since the peak move occurred | `now - peak_timestamp` | 0-300 (s) | Maybe — staleness of peak |
| `btc_range` | High-low range this candle | `btc_peak_move - btc_trough_move` | 0 to +∞ ($) | Maybe — volatility proxy |

**Source:** `tasks/prompt_context.py:161-197` (`compute_btc_trajectory()`)

---

## BTC Candle History Indicators (from 5-min OHLCV candles)

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `streak_count` | Consecutive candles in same direction | count of same-direction candles from latest | 0-∞ (int) | Yes — mean reversion signal |
| `streak_direction` | Direction of current streak | "up" or "down" | enum | Yes |
| `ma5` | 5-candle moving average of close | mean(last 5 closes) | float ($) | Maybe — via trend_score |
| `ma12` | 12-candle moving average of close | mean(last 12 closes) | float ($) | Maybe — via trend_score |
| `ma5_vs_ma12` | Short-term crossover | "bullish" if ma5 > ma12, else "bearish" | enum | Yes — trend direction |
| `ma50` | 50-candle moving average of close | mean(last 50 closes) | float ($) | No — too slow for 5-min |
| `ema20` | 20-candle exponential MA | EMA formula | float ($) | Maybe — via trend_score |
| `ema50` | 50-candle exponential MA | EMA formula | float ($) | Maybe — via trend_score |
| `trend_score` | Composite regime indicator | 0.4×ema_sig + 0.35×price_sig + 0.25×candle_sig | -1 to +1 | Yes — macro regime |
| `up_candle_ratio` | Fraction of last 12 candles that were UP | count(up) / 12 | 0-1 | Maybe — via trend_score |
| `net_15min_move` | BTC net change over last 3 candles | `candle[-1].close - candle[-3].open` | float ($) | Maybe — medium-term momentum |

**Source:** `decision_engine/prompts.py:268-343`

---

## Orderbook / Microstructure Indicators

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `spread_pct` | Tightness of the UP token market | `(ask - bid) / mid` | 0-1 | Yes — liquidity proxy |
| `bid_depth` | USD volume backing the bid | sum of bid levels × prices | float ($) | Yes — support strength |
| `ask_depth` | USD volume at the ask | sum of ask levels × prices | float ($) | Yes — resistance strength |
| `depth_imbalance` | Relative buying vs selling pressure | `(bid_depth - ask_depth) / (bid_depth + ask_depth)` | -1 to +1 | Yes — orderflow signal |
| `spread_trend` | Is spread widening or narrowing? | compare current vs N candles ago | widening/narrowing/stable | Maybe |
| `cross_candle_spread` | Spread trend across candles | `tasks/prompt_context.py:305-345` | descriptive | No — redundant with spread_pct |

**Source:** `models/core.py` (`OrderbookSnapshot` properties), `tasks/prompt_context.py:305-345`

---

## Adaptive Entry / Reversal Indicators

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `reversal_rate` | Fraction of candles where mid-candle leader lost | rolling window over recent resolutions | 0-1 | Yes — regime classification |
| `signal_type` | Market regime classification | based on reversal_rate thresholds | MOMENTUM/UNCERTAIN/CONTRARIAN | Maybe — via reversal_rate |
| `fakeout_noise` | Noise level in early candle readings | from adaptive entry history | float | No — too specialized |

**Source:** `adaptive_entry/ai_context.py:13-109`

---

## ML Scorer Indicators

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `ml_score` | ML model's probability that UP wins | logistic regression on feature vector | 0-1 | Yes — independent signal |
| `ml_drivers` | Top feature contributions with direction | feature importance with signed weights | string | Yes — explains ml_score |
| `ml_confidence` | How confident the ML model is | `abs(ml_score - 0.5) * 2` | 0-1 | Maybe — via ml_score distance from 0.5 |

**Source:** `ml_scorer/` module, `tasks/context_builder.py:21-39`

---

## Velocity / Conflict Indicators

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `velocity_conflict_severity` | Disagreement between magnitude and velocity direction | composite score | 0-1 | No — used for code sizing |
| `velocity_conflict_label` | Human-readable conflict description | from severity thresholds | string | No — code handles sizing |
| `drawback_pct` | How much of peak move has been erased | `1 - (current_move / peak_move)` | 0-1+ | Yes — same as retracement_pct |

**Source:** `tasks/context_builder.py:70-93`

---

## Reversal Regime Indicators

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `regime_score` | Reversal intensity of recent candles | composite of reversal frequency + zero crossings | 0-1 | No — used for code sizing |
| `regime_label` | HIGH_REVERSAL / MODERATE / DIRECTIONAL | from score thresholds | enum | No — code handles sizing |

**Source:** `tasks/context_builder.py:96-126`

---

## External / Reference Indicators

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `chainlink_price` | On-chain BTC/USD (resolution source) | Chainlink data feed | float ($) | No — btc_price already uses this |
| `chainlink_divergence` | Gap between Binance and Chainlink | `binance_price - chainlink_price` | float ($) | Only if > $100 (rare) |
| `btc_24h_change_pct` | BTC 24-hour change | from price feed | float (%) | No — not predictive for 5-min |

**Source:** `models/core.py` (`BtcPrice` fields)

---

## Performance / Calibration Data

| Indicator | What it measures | Computation | Range | Send to AI? |
|-----------|-----------------|-------------|-------|-------------|
| `last_outcomes` | Recent trade results | list of W/L from resolved trades | string[] | Yes — self-calibration |
| `session_win_rate` | Overall session accuracy | wins / total_trades | 0-1 | Maybe — in last_outcomes |
| `side_accuracy` | Per-side (UP/DOWN) win rate | wins_per_side / trades_per_side | 0-1 | No — reflection handles this |
| `confidence_calibration` | Actual WR at each confidence level | binned historical analysis | table | No — reflection handles this |

**Source:** `knowledge/manager.py:292-494`, `tasks/ai_decision.py:627-629`

---

## Position State

| Field | What it measures | Range | Send to AI? |
|-------|-----------------|-------|-------------|
| `position.token` | Which token is held | "up" / "down" / null | Yes |
| `position.shares` | How many shares held | float | Yes |
| `position.entry_price` | Average entry price | 0-1 | Yes |
| `position.unrealized_pnl` | Current unrealized P&L | float ($) | Yes |
| `cash` | Available USD | float ($) | Yes |

---

## Recommended AI Snapshot (what goes to the AI)

Based on the analysis above, here's the minimal set that gives AI everything it needs for judgment:

```json
{
  "time_remaining_s": 247,

  "btc_move": -42.35,
  "btc_peak_move": 12.50,
  "btc_trough_move": -56.58,
  "zero_crossings": 2,
  "velocity": -1.8,
  "acceleration": -0.3,

  "up_ask": 0.38,
  "up_bid": 0.26,
  "down_ask": 0.75,
  "down_bid": 0.62,
  "spread_pct": 0.037,
  "depth_imbalance": -0.72,

  "reversal_rate": 0.45,
  "streak_count": 3,
  "streak_direction": "down",
  "trend_score": -0.35,
  "ma5_vs_ma12": "bearish",

  "ml_score": 0.31,
  "ml_drivers": "velocity: -0.4, spread: +0.1, momentum: -0.3",

  "position": null,
  "cash": 47.50,

  "trajectory": [
    [0,    0.00,  0.50, 0.50,  0.0],
    [10,  +5.20,  0.52, 0.48, +0.5],
    [20, +12.50,  0.58, 0.42, +0.7],
    [30,  +8.10,  0.55, 0.45, -0.4],
    [40,  -2.30,  0.49, 0.51, -1.0],
    [50, -42.35,  0.38, 0.75, -1.8]
  ],

  "last_outcomes": ["W", "L", "W", "W", "L"]
}
```

### What's excluded (and why)

| Excluded | Why |
|----------|-----|
| `regime_score`, `regime_label` | Code uses these for sizing. AI doesn't need to know. |
| `velocity_conflict_severity` | Code uses this for sizing. The raw velocity + acceleration tells AI the same thing. |
| `chainlink_divergence` | Rare (>$100 gap). When it happens, code can add a one-line flag. |
| `btc_24h_change_pct` | Not predictive for 5-min candles. Noise. |
| `confidence_calibration` | Belongs in reflection, not per-decision. |
| `side_accuracy` | Belongs in reflection. |
| `spread_trend` | Redundant — trajectory shows spread evolution. |
| `fakeout_noise` | Too specialized. Reversal_rate covers the same ground. |
| `ma50`, `ema20`, `ema50` | Collapsed into `trend_score` (one number instead of three). |
| R/R ratio | Code computes and applies sizing. AI sees the raw prices. |
| All prose warnings (I7-I11) | Rules moved to code. AI gets the underlying data. |
