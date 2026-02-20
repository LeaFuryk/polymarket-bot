# Trading Patterns

## Key Principles for 5-Min BTC Candle Markets

1. **24h BTC change is NOT predictive** for 5-min candles. ~40% of 5-min candles go opposite to the daily trend.
2. **Micro-momentum matters**: The last 3-6 five-minute candles are the best predictor of the next candle.
3. **Mean reversion after 3+ same-direction candles**: Increased probability of reversal, but context-dependent.
4. **Flat candles = UP wins**: When BTC Open = Close, "up" outcome wins by default.
5. **Entry price is everything**: For binary options, lower entry = better risk/reward. Never overpay.
6. **Intra-candle momentum signals**: When BTC is already moving significantly during the candle (e.g., -$81 or -0.121%), this creates continuation opportunity if entry price is favorable.

## Entry Pricing Discipline (Risk/Reward Ratio)

Every BUY is a binary bet: win = $1, lose = $0. Risk/reward ratio = (1 - entry) / entry.

| Entry Price | R/R Ratio | Size Scale | Status |
|-------------|-----------|------------|--------|
| $0.30 | 2.33 | 100% | Excellent |
| $0.33 | 2.00 | 100% | Full size threshold |
| $0.35 | 1.86 | ~86% | Good |
| $0.40 | 1.50 | ~71% | Acceptable |
| $0.43 | 1.33 | ~52% | Marginal (just above gate) |
| $0.435 | 1.30 | BLOCKED | Minimum R/R gate |
| $0.45 | 1.22 | BLOCKED | Bad R/R |
| $0.50 | 1.00 | BLOCKED | Coin flip |

**Entries with R/R < 1.3 (price > ~$0.435) are automatically blocked by risk management.**
Entries that pass the gate get size scaled: 50% at R/R 1.3, ramping to 100% at R/R 2.0.

*Intra-Candle Momentum*: When BTC already moved >0.10% during candle, continuation plays at 0.75-0.85 can work if <90s remaining — but these carry inherently higher risk.
*Late-Cycle Entries (<45s)*: Only for strong momentum continuation when BTC already moved >0.15% and entry 0.85-0.90

## Winning Trade Pattern Analysis

**Recent Session Winners**:
- **Cycle 46 (+6.7674)**: DOWN at 0.71 when BTC down $113 (-0.168%), 173s remaining. Strong mid-candle momentum.
- **Cycle 48 (+0.4179)**: UP at 0.90 (sold from prior position), captured small move.
- **Cycle 50 (+8.4320)**: DOWN continuation, BTC dropped $173 (-0.257%).
- **Cycle 56 (+5.9556)**: UP at 0.88, BTC rallied $122 (+0.183%).

**Key Insight**: Mid-to-late cycle momentum plays (90-180s remaining) with entry prices 0.70-0.90 work when BTC has already moved >0.10% in one direction. The market is pricing in continuation correctly.

## Losing Trade Pattern Analysis

**Recent Session Losers**:
- **Cycle 49 (-13.8301)**: UP position, BTC rallied $130 but then reversed. Likely held too long or entered on false momentum.
- **Cycle 53 (-0.0913)**: UP at 0.90, small loss on marginal move.
- **Cycle 54 (-36.0559)**: UP position, BTC only moved $50 (+0.075%). MAJOR LOSS - likely poor entry price or wrong direction on weak momentum.

**Critical Pattern**: The biggest loss (Cycle 54, -$36) came on a small UP move ($50). This suggests either:
1. Entered DOWN and lost badly, OR
2. Entered UP at terrible price (>0.95) and couldn't exit profitably
3. Position sizing was too large relative to edge

**Lesson**: Avoid entries when BTC movement is marginal (<0.10%). The $50 move that caused -$36 loss shows we're getting caught in noise.

## Exit Discipline

- Take profits at 0.25-0.35 after good entry — don't wait for extreme prices
- Exit when down >25% with >180s remaining
- **NEW**: Exit when down >15% with <90s remaining (limited recovery time)
- Don't let winners turn into losers
- For late-cycle momentum plays (>0.75 entry), hold to expiry if thesis intact
- **CRITICAL**: On small BTC moves (<$75 or <0.10%), exit quickly if not profitable within 60s

## Pre-Trade Checklist

1. Check BTC candle streak and regime (trending vs choppy vs exhaustion)
2. Validate entry price against thresholds
3. Check time remaining (no entries <45s EXCEPT strong momentum continuation)
4. Review ML baseline and calibration data
5. **Check current BTC price vs candle open** — if already moved >0.10%, consider continuation play
6. **NEW**: Verify BTC move magnitude — avoid trades when current move <$50 from open
7. **NEW**: Check recent volatility — in low-vol periods, require >0.15% move for continuation plays

## Strategy Selection Framework

- **Early candle (>180s)**: Use mean reversion after streaks, avoid trend-following
- **Mid candle (90-180s)**: Momentum continuation if BTC moved >0.10%, entry 0.70-0.85
- **Late candle (<90s)**: Only strong momentum (>0.15% move) at 0.85-0.90 entry
- **After 3+ consecutive candles**: Mean reversion ONLY (unless late-candle momentum override)
- **Choppy/low-vol markets**: Default to HOLD, require >0.20% move for any entry

## Market Regime Recognition

**High Volatility** (moves >$150/candle): Momentum continuation works well, use 0.70-0.85 entries
**Medium Volatility** ($75-$150/candle): Selective momentum plays, require >0.12% move
**Low Volatility** (<$75/candle): AVOID TRADING - noise dominates, mean reversion unreliable