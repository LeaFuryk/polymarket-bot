# Trading Patterns — Market Data Analysis (159 candles, 16K snapshots)

These are statistical observations from historical market data. They describe patterns and tendencies, NOT absolute rules. Market conditions change — use these as context for your decisions, weighing them alongside current indicators.

## BTC Move Magnitude & Predictability

The size of the BTC move from candle open is the strongest predictor of outcome accuracy.

| BTC Move at 60s | Directional Accuracy | Notes |
|-----------------|---------------------|-------|
| $0-$20          | ~54% | Near coin flip — direction is mostly noise |
| $20-$50         | ~61% | Marginal edge, still unreliable |
| $50-$100        | ~65-70% | Moderate edge — better than smaller moves but reversals still common |
| $100-$200       | ~90% | Very strong signal |
| $200+           | ~89% | Near-certain direction, but rare |

Observation: The $50 threshold offers moderate improvement over smaller moves, but accuracy varies by market conditions. iter_008 (128 candles) showed at least 10 losses on $50+ moves, bringing the observed accuracy to ~65-70% — meaningful edge but far from certain. Moves below $50 at 60s elapsed have reversed ~40% of the time.

## Reversal Rates by Elapsed Time

Reversals (direction at entry time ≠ final winner) are common early and taper off.

| Elapsed Time | Reversal Rate |
|-------------|--------------|
| 20s         | ~42% |
| 30s         | ~39% |
| 60s         | ~33% |
| 90s         | ~29% |
| 120s        | ~20% |
| 150s+       | ~20% (plateau) |

Observation: Before 90s elapsed, roughly 1 in 3 candles still reverses. After 120s, reversals stabilize around 20%.

## Entry Timing — Two EV Peaks

Historical expected value per trade varies by entry timing. There are two favorable windows:

- **Early window (30-45s elapsed)**: Cheap prices, moderate accuracy. Best when BTC move is already strong ($50+). Historically highest EV setup: 45s elapsed + $50 BTC move.
- **Late window (120-165s elapsed)**: High accuracy, prices haven't fully caught up. Direction is more established.
- **Dead zone (60-105s)**: Prices have moved but accuracy hasn't caught up enough to compensate. Historically negative or flat EV.

## Entry Price & Win Rate (counterintuitive pattern)

Historically, expensive entries have won more often than cheap ones:

| Entry Ask Price | Typical R/R | Historical Win Rate |
|----------------|-------------|-------------------|
| $0.67+ (R/R <0.5) | Low payoff | ~85% (high conviction) |
| $0.50-$0.67 (R/R 0.5-1.0) | Moderate | ~58% |
| $0.40-$0.50 (R/R 1.0-1.5) | Good | ~56% |
| $0.25-$0.40 (R/R 1.5-3.0) | Great on paper | ~29% (contrarian trap) |

Observation: Cheap entries (high R/R) are often cheap because they're contrarian — betting against a strong directional move. They look attractive on R/R but historically lose 2 out of 3 times. Expensive entries reflect the market correctly pricing directional certainty. Consider the reason an entry is cheap before sizing up on it.

## Streak Patterns

| Streak Length | Next Candle Behavior |
|--------------|---------------------|
| 1 (isolated) | ~46% reverse (near random) |
| 2 consecutive | ~58% reverse (mild mean-reversion signal) |
| 3+ consecutive | ~62% continue (momentum signal) |

Observation: After 2 same-direction candles, there's a slight tendency to reverse. After 3+, momentum dominates and the streak tends to continue. The shift happens at streak=3.

## Orderbook Depth as Confirmation

When one side has >70% of the book depth at 60s elapsed, the heavy side has historically won ~80% of the time. Balanced books are not predictive.

Spread width correlates positively with outcome clarity — wider spreads have historically correlated with higher win rates (80-83% on wide spreads vs 65% on tight). This is likely because wide spreads occur during strong directional moves where the outcome is clearer.

## Candle Volatility

~30% of candles have 5+ direction flips during their lifetime. Only ~21% go cleanly in one direction without flipping. This means intra-candle noise is high — the BTC move magnitude matters more than moment-to-moment direction.

## Market Efficiency Trend

The market may be getting more efficient over time. Recent iterations show smaller average BTC moves ($75 in iter_006 vs $111-$122 in iter_003-005) and lower directional accuracy at 60s (58% in Q4 vs 73% in Q2-Q3). Consider being more selective when average moves shrink.

## Flat Candles

When BTC Open ≈ Close, the "UP" outcome wins by default. These are common on small moves.

## General Principles

1. **24h BTC change is not predictive** for 5-min candles. ~40% of candles go opposite to the daily trend.
2. **Micro-momentum matters**: The last 3-6 five-minute candles are a useful predictor.
3. **HOLD is often correct**: In this dataset, ~30% of candles had moves too small for a reliable directional bet.
4. **BTC move > entry price**: The magnitude of the BTC move from open is a better signal than the token price alone.
