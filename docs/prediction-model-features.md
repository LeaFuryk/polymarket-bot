# Prediction Model Features — 5-Minute BTC Bet Outcome

> **Goal:** Collect and structure data to fine-tune a model that predicts the outcome (UP/DOWN) of Polymarket 5-minute BTC candle bets.
>
> **Target variable:** `winner` — binary ("up" if BTC close ≥ open, "down" otherwise)

---

## A. BTC Price History

The core signal — bet outcome is purely determined by BTC price movement.

| # | Feature | Type | Window | Description |
|---|---------|------|--------|-------------|
| 1 | `btc_1m_open` | float | Per 1-min candle | Open price of the 1-minute candle |
| 2 | `btc_1m_high` | float | Per 1-min candle | Highest price during the 1-minute window |
| 3 | `btc_1m_low` | float | Per 1-min candle | Lowest price during the 1-minute window |
| 4 | `btc_1m_close` | float | Per 1-min candle | Close price of the 1-minute candle |
| 5 | `btc_1m_volume` | float | Per 1-min candle | Trading volume during the 1-minute window. Volume confirms or denies a move — low-volume pumps tend to reverse, high-volume breaks tend to continue |
| 6 | `btc_return_1m` | float | Last 1 min | Close-to-close return (%). Captures immediate momentum |
| 7 | `btc_return_5m` | float | Last 5 min | 5-minute rolling return. Matches the bet window length — mean-reversion vs continuation signal |
| 8 | `btc_return_15m` | float | Last 15 min | Medium-term momentum. A 5-min move after a 15-min trend behaves differently than a reversal |
| 9 | `btc_return_30m` | float | Last 30 min | Longer-term trend context |
| 10 | `btc_return_1h` | float | Last 1 hour | Macro direction. Bets against the 1h trend have lower win rates |
| 11 | `btc_realized_vol_5m` | float | Last 5 min | Standard deviation of 1-min returns over 5 minutes. High vol = wider expected range, harder to predict direction |
| 12 | `btc_realized_vol_15m` | float | Last 15 min | Medium-term volatility regime |
| 13 | `btc_realized_vol_1h` | float | Last 1 hour | Macro volatility context |
| 14 | `btc_vwap_distance` | float | Session | `(price - VWAP) / VWAP` as %. Price far from VWAP tends to revert — acts as a mean-reversion anchor |
| 15 | `btc_range_1h` | float | Last 1 hour | `(high - low) / low` across the last hour. If price is at the edge of its range, continuation is less likely |

---

## B. Polymarket Orderbook

The orderbook is a prediction market — it aggregates all other participants' models, information, and intuition. Changes in the first minute are especially informative.

| # | Feature | Type | Granularity | Description |
|---|---------|------|-------------|-------------|
| 16 | `up_mid_price` | float | Per-minute snapshot | Midpoint of UP token best bid/ask. This IS the crowd's probability estimate for UP winning |
| 17 | `down_mid_price` | float | Per-minute snapshot | Midpoint of DOWN token. Should roughly equal `1 - up_mid_price` minus the vig |
| 18 | `up_spread_pct` | float | Per-minute snapshot | `(ask - bid) / mid * 100`. Wide spread = market uncertainty, low predictability. Tight = consensus |
| 19 | `down_spread_pct` | float | Per-minute snapshot | Same for DOWN token. Asymmetric spreads between UP/DOWN signal directional uncertainty |
| 20 | `up_bid_depth` | float | Per-minute snapshot | Total $ liquidity on the bid side for UP token. Deep bids = strong buy interest |
| 21 | `up_ask_depth` | float | Per-minute snapshot | Total $ liquidity on the ask side. Deep asks = selling pressure or market makers hedging |
| 22 | `down_bid_depth` | float | Per-minute snapshot | Bid-side liquidity for DOWN token |
| 23 | `down_ask_depth` | float | Per-minute snapshot | Ask-side liquidity for DOWN token |
| 24 | `book_imbalance_up` | float | Per-minute snapshot | `(bid_depth - ask_depth) / (bid_depth + ask_depth)` for UP. Positive = buyers aggressive, crowd expects UP to win |
| 25 | `book_imbalance_down` | float | Per-minute snapshot | Same for DOWN token |
| 26 | `cross_book_flow` | float | Per-minute snapshot | `up_bid_depth / (up_bid_depth + down_bid_depth)`. When UP book gets thicker while DOWN thins, money flows to UP conviction |
| 27 | `mid_velocity_up` | float | First 30-60s | Rate of change of UP mid price in early window. Early movers tend to be informed traders |
| 28 | `spread_delta` | float | From bet open | Change in spread since bet opened. Spread narrowing = market converging on outcome |

---

## C. Temporal / Session

Time is a cheap, high-value feature. The same BTC pattern at 3am UTC vs 2pm UTC has very different follow-through probability.

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 29 | `hour_utc` | int (0-23) | Hour of day in UTC. BTC volatility is session-dependent — US open (13:30 UTC), Asian session, London open each have distinct behavior |
| 30 | `day_of_week` | int (0-6) | Monday=0, Sunday=6. Weekends are thinner and more susceptible to manipulation. Monday opens can gap |
| 31 | `minute_of_hour` | int (0-59) | Position within the hour. Institutional algos often execute at :00, :15, :30, :45 boundaries |
| 32 | `is_us_market_hours` | bool | True if 13:30-20:00 UTC. Higher volume, more directional moves, different dynamics than off-hours |
| 33 | `is_event_proximity` | bool | True if within 2 hours of FOMC, CPI, NFP, or options expiry. Volatility regime completely changes around these — model should learn to be cautious or exploit |

---

## D. Momentum / Technical Indicators

Compressed representations of price dynamics. All derived from BTC 1-min candles — no extra data collection needed.

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 34 | `rsi_14` | float (0-100) | RSI on 14 × 1-min candles. Overbought (>70) predicts short-term pullback; oversold (<30) predicts bounce |
| 35 | `ema_9` | float | 9-period EMA on 1-min closes. Fast-moving average — captures immediate trend |
| 36 | `ema_21` | float | 21-period EMA on 1-min closes. Slower trend anchor |
| 37 | `ema_cross_state` | int (-1, 0, 1) | `1` if EMA9 > EMA21 (bullish), `-1` if below (bearish), `0` if within 0.01% (flat). Crossover events are high-signal |
| 38 | `streak_count` | int | Consecutive same-direction 5-min candles. 5+ green candles in a row statistically favors reversal |
| 39 | `streak_direction` | str | "up" or "down" — direction of the current streak |
| 40 | `body_wick_ratio` | float | Average `abs(close - open) / (high - low)` over last 3 candles. Long wicks = rejection. Full bodies = conviction |
| 41 | `roc_5m` | float | Rate of change over last 5 minutes: `(price_now - price_5m_ago) / price_5m_ago * 100`. Captures acceleration |
| 42 | `roc_15m` | float | Rate of change over 15 minutes. Deceleration (ROC shrinking) signals trend exhaustion |

---

## E. Volatility Regime

Explicit volatility features allow the model to learn regime-conditional behavior — what works in calm markets fails in chaotic ones.

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 43 | `atr_14_1m` | float | Average True Range, 14-period on 1-min candles. Normalizes what "a big move" means in current conditions |
| 44 | `atr_14_5m` | float | ATR on 5-min candles. Broader volatility context |
| 45 | `bollinger_position` | float (-1 to 1) | `(price - BB_mid) / (BB_upper - BB_mid)`. Value near ±1 = at band edge, potential reversal. 0 = at midline |
| 46 | `vol_of_vol` | float | Std dev of rolling 5-min realized vol over 1 hour. Rising vol-of-vol = regime transition (calm → chaotic), when models are most likely to break |
| 47 | `funding_rate` | float | BTC perpetual funding rate from Binance. Extreme positive = overleveraged longs (liquidation cascade risk downward). Extreme negative = overleveraged shorts |

---

## F. Outcome / Labels

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 48 | `winner` | str | **Primary label.** "up" or "down" — binary classification target |
| 49 | `btc_move_magnitude` | float | `btc_close - btc_open` in $. Secondary label for regression or confidence weighting. A bet won by $0.50 is noise; one won by $500 is a clear signal |
| 50 | `polymarket_verified` | bool | Whether the outcome was confirmed by Polymarket on-chain resolution (Chainlink). Use as ground truth when it diverges from Binance-derived winner |

---

## Example: Training Data Table

One row per **bet × minute** (5 rows per bet, each with its own BTC candle and orderbook snapshot).

> The table below shows a single 5-minute bet (`bet_id = 42`) spanning 14:00:00–14:05:00 UTC.
> BTC was trending up and the bet resolved **UP** (close ≥ open).

| bet_id | minute_index | minute_ts | btc_1m_open | btc_1m_high | btc_1m_low | btc_1m_close | btc_1m_volume | btc_return_1m | btc_return_5m | btc_realized_vol_5m | rsi_14 | ema_cross_state | up_mid_price | up_spread_pct | book_imbalance_up | cross_book_flow | hour_utc | streak_count | atr_14_1m | winner | btc_move_magnitude |
|--------|-------------|-----------|-------------|-------------|------------|--------------|---------------|---------------|---------------|----------------------|--------|-----------------|--------------|---------------|-------------------|-----------------|----------|--------------|-----------|--------|---------------------|
| 42 | 0 | 1711198800 | 67,210.50 | 67,225.00 | 67,195.30 | 67,220.10 | 12.45 | +0.014% | +0.082% | 0.031% | 55.2 | 1 | 0.52 | 2.10% | +0.08 | 0.54 | 14 | 2 | 18.70 | up | +45.80 |
| 42 | 1 | 1711198860 | 67,220.10 | 67,248.90 | 67,218.00 | 67,241.50 | 18.30 | +0.032% | +0.095% | 0.034% | 57.8 | 1 | 0.55 | 1.80% | +0.12 | 0.57 | 14 | 2 | 19.10 | up | +45.80 |
| 42 | 2 | 1711198920 | 67,241.50 | 67,260.00 | 67,235.20 | 67,252.30 | 15.60 | +0.016% | +0.108% | 0.032% | 60.1 | 1 | 0.58 | 1.50% | +0.18 | 0.60 | 14 | 2 | 18.90 | up | +45.80 |
| 42 | 3 | 1711198980 | 67,252.30 | 67,265.40 | 67,240.10 | 67,258.70 | 10.20 | +0.010% | +0.112% | 0.028% | 61.5 | 1 | 0.61 | 1.20% | +0.22 | 0.63 | 14 | 2 | 18.50 | up | +45.80 |
| 42 | 4 | 1711199040 | 67,258.70 | 67,270.00 | 67,245.00 | 67,256.30 | 8.90 | -0.004% | +0.098% | 0.025% | 59.8 | 1 | 0.63 | 1.00% | +0.25 | 0.65 | 14 | 2 | 18.20 | up | +45.80 |

### Reading the example

- **Minutes 0→2**: BTC climbing steadily, volume confirms (+18.3 BTC in minute 1). `up_mid_price` rises from 0.52 → 0.58 as the crowd prices in the move. `book_imbalance_up` grows from +0.08 → +0.18 — buyers getting aggressive.
- **Minutes 3→4**: Momentum fading — volume drops (10.2 → 8.9), `btc_return_1m` flattens, but the trend holds. The orderbook has mostly priced it in (`up_mid` at 0.63).
- **Result**: BTC opened at 67,210.50 and closed at 67,256.30 → **UP wins** by $45.80.

### Alternative flat structure (one row per bet)

For models that prefer a single row per prediction, flatten the 5 minutes into columns:

| bet_id | btc_open | btc_close | winner | m0_btc_close | m0_up_mid | m1_btc_close | m1_up_mid | m2_btc_close | m2_up_mid | m3_btc_close | m3_up_mid | m4_btc_close | m4_up_mid | rsi_14_at_open | streak_count | hour_utc |
|--------|----------|-----------|--------|--------------|-----------|--------------|-----------|--------------|-----------|--------------|-----------|--------------|-----------|----------------|--------------|----------|
| 42 | 67,210.50 | 67,256.30 | up | 67,220.10 | 0.52 | 67,241.50 | 0.55 | 67,252.30 | 0.58 | 67,258.70 | 0.61 | 67,256.30 | 0.63 | 55.2 | 2 | 14 |
| 43 | 67,256.30 | 67,231.00 | down | 67,248.00 | 0.48 | 67,240.20 | 0.44 | 67,235.10 | 0.40 | 67,232.50 | 0.38 | 67,231.00 | 0.36 | 62.0 | 0 | 14 |

---

## Data Sources

| Feature Group | Source | Already Captured? |
|---------------|--------|-------------------|
| A. BTC Price (OHLC) | Binance 1-min klines or derive from per-second `snapshots.btc_price` | Price: yes (per-second). Volume: **no** — needs Binance klines |
| B. Orderbook | `snapshots` table (top-of-book per second) | Yes — best bid/ask, depth, spread. Full L2: no |
| C. Temporal | Derived from `snapshots.timestamp` | Yes — no extra collection needed |
| D. Momentum | Derived from BTC 1-min candles | Yes — compute at query time |
| E. Volatility | Derived from BTC candles + Binance funding API | ATR/Bollinger: yes. Funding rate: **no** — needs Binance futures API |
| F. Labels | `candles.winner`, `candles.btc_open`, `candles.btc_close` | Yes |

---

## Collection Priority

1. **A + F** — BTC candles + labels. Strong baseline, minimal effort.
2. **+ C** — Temporal features are free to derive from timestamps.
3. **+ D + E** — All derived from group A, no extra ingestion.
4. **+ B** — Orderbook data is your unique edge that public BTC datasets don't have.
5. **+ Funding rate** — Single new API call, high signal for 5-min windows.
