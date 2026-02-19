# Self Assessment

## Known Biases to Avoid

1. **24h Anchoring Bias**: Do NOT let the daily BTC change dominate your reasoning. The 24h change was cited in 76% of trades but has low predictive value for 5-min outcomes.

2. **Bearish Bias on Red Days**: Avoid betting bearish on every 5-min candle just because the daily candle is red. This loses money on the ~40% of candles that go up on bearish days.

3. **Low Confidence Trading**: Trades at 0.52-0.58 confidence are low quality. Only trade when confidence >= 0.6.

4. **Overtrading**: Not every cycle needs a trade. A well-timed HOLD is better than a low-edge trade that costs API fees.

5. **Ignoring Flat Markets**: When BTC is consolidating (Open = Close), "up" wins by default. Don't force directional calls in sideways action.

## Calibration Notes
- Confidence should reflect actual expected edge, not just a feeling
- Track whether high-confidence trades actually win more often
- If win rate < 50%, reduce trading frequency rather than increasing size

## Recent Performance Analysis

### This Session (3 markets)
- **Win Rate**: 2/2 trades closed = 100% (both "up" positions)
- **Net PnL**: +$2.09 (+$5.42 - $3.33)
- **Key Success**: Cycle 3-4 captured +$5.42 by buying "up" at 0.65 and selling at 0.76
- **Key Loss**: Cycle 7-8 lost -$3.33 by buying "up" at 0.48 and panic-selling at 0.43

### What Went Right
- Cycle 3-4: Bought "up" and took profit appropriately when price moved favorably
- Recognized flat market conditions (all candles had Open = Close)

### What Went Wrong
- Cycle 7-8: Sold at a loss (0.43) when entry was good (0.48). Should have held through to resolution since "up" won
- Premature exit cost $3.33 in realized losses on a winning outcome
- Need better conviction on good entries in flat markets

## Action Items
- In consolidating markets (flat candles), hold "up" positions bought below 0.50 through resolution
- Don't panic-sell good entries just because price dips slightly
- Consider enabling spread_trend indicator to better identify flat vs trending markets