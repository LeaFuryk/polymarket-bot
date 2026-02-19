# Session History

Rolling log of recent sessions (capped at ~20 entries). Updated by reflection.

| Date | W/L | PnL | Key Takeaway |
|------|-----|-----|--------------|--|
| Recent | 2W-0L | +$2.09 | Flat market session: all 3 candles had BTC Open = Close at $66450, "up" won each time. Profitable trade buying "up" at 0.65 → 0.76 (+$5.42), but lost -$3.33 by panic-selling a good 0.48 entry at 0.43. In consolidating markets, hold "up" positions bought below 0.50 through resolution. Need better conviction on quality entries. |
| Previous | 0W-1L | -$41.04 | **CRITICAL LOSS**: Bought UP at 0.82 with 0.65 confidence after 4 of 6 candles went UP. Market mean-reverted and went DOWN ($66662→$66653). This violated the mean reversion principle: after 4+ consecutive same-direction candles, reversal probability increases significantly. Never buy continuation at >0.75 in exhaustion setups. Should have either faded the momentum (bet DOWN) or stayed out. Momentum exhaustion blindness cost $41. Need to enable mean_reversion indicator and add exhaustion detection logic. |
| Session 1 | 2W-1L-1BE | +$16.26 | **REDEMPTION SESSION**: Applied mean reversion lessons perfectly. After the -$41 loss on momentum continuation (Cycle 1), correctly faded exhaustion in Cycles 4 and 8, going 2-0 on mean reversion trades. Cycle 8 was textbook: bought DOWN at 0.25 after 4 UP candles, exited at 0.99 with 65s left (+$44.35). Cycle 4 also profitable at 0.74 entry (+$12.96). Key insight: In low-volatility environment (moves of $9-$38), mean reversion signal is HIGHLY reliable. The bot made 7 HOLD decisions showing improved discipline, though some may have been over-cautious with 0.45-0.55 confidence on clear setups. Enabled token_mean_reversion and confidence_calibration indicators. Net recovery: +$16.26 erases 40% of previous loss. Pattern confirmed: fade momentum after 4+ consecutive candles, especially at value prices <0.50. |
| Session 2 | 1W-3L-3BE | -$10.42 | **HARSH REALITY CHECK**: Mean reversion strategy collapsed in strong downtrend. All 7 markets went DOWN as BTC dropped $166 over 35 minutes ($66662→$66496). Multiple mean reversion setups FAILED: Cycle 14 bought UP at 0.36 after 2UP/4DOWN (-$21.62), Cycle 23 bought UP at 0.40 after 5-of-6 DOWN (-$40.40). Only 1 mean reversion trade won (Cycle 18: +$34.69), giving 25% win rate vs expected 60-75%. CRITICAL LESSON: Mean reversion is probabilistic, not guaranteed. When BTC is in sustained 20-30 minute directional trend, short-term exhaustion signals are unreliable. The bot showed dangerous pattern rigidity - repeating failed mean reversion setup in Cycles 22→23 instead of adapting. New rule: Check 30-minute trend context before mean reversion trades. Reduce confidence by 0.15-0.20 in trending markets. After 2 consecutive failed reversals, switch to HOLD mode. Entry pricing was better this session (0.36-0.53 range), but strategy-market mismatch caused losses. The previous session's 2-0 success created overconfidence (0.68 on all trades). Need dynamic confidence adjustment based on trend strength. Enabled session_streak to detect sustained directional runs. |
| Session 3 | 0W-4L-6BE | -$94.22 | **CATASTROPHIC FAILURE**: Worst session yet. 0% win rate on decided trades, lost $94.22. Despite Session 2 lessons about trend context, repeated exact same mistakes. All 10 markets continued the downtrend (BTC $66662→$66324, -$338 total drop). Took 4+ mean reversion trades at 0.68 confidence (Cycles 18, 19, 22, 23) that all failed. CRITICAL ERROR in Cycles 22→23: repeated identical failed setup (bought UP at 0.53 then 0.40 after 5-of-6 DOWN) without adapting. This is pattern rigidity at catastrophic level. Entry discipline collapsed: bought at 0.77 (Cycle 24), 0.85 (Cycle 26), 0.88 (Cycle 29) - all violate pricing rules. Session_streak was enabled but ignored - should have detected 6+ consecutive DOWN pattern and stopped mean reversion trades. Key lesson: When a pattern fails twice consecutively, market is telling you conditions have changed - MUST switch to HOLD mode. After 0-2 record, should have stopped trading or reduced sizes by 50%. Confidence calibration was completely broken: 0.68 on trades with <30% actual win probability. Need HARD STOPS: (1) After 2 failed mean reversions in trend, no more for session. (2) Entry price violations = automatic HOLD. (3) After 3 losses, reduce sizes 50% or stop. (4) 30-minute trend check is MANDATORY, not optional. The bot learned mean reversion works in choppy markets but failed to learn when NOT to use it. This session proves that pattern recognition without context awareness is dangerous. Total damage from Sessions 2-3: -$104.64. Mean reversion win rate in trending markets: 1W-7L (12.5%). Must implement regime detection before taking any mean reversion trades. |
| Session 4 | 7W-2L-4BE | +$62.38 | **BREAKTHROUGH SESSION**: Complete strategic reversal from Sessions 2-3. Recognized sustained downtrend early (BTC $66662→$66171, -$491 over 13 markets) and switched from mean reversion to trend-following. Result: 78% win rate (7W-2L) and +$62.38 profit, erasing 60% of previous two sessions' losses. KEY INSIGHT: 6+ consecutive candles in STRONG TREND (>$100 move) is a CONTINUATION signal, not exhaustion. All 7 wins came from trend-following DOWN at entry prices 0.40-0.88 (avg 0.52). Best trades: Cycle 33 at 0.40 (+$44.35), Cycle 43 at 0.43 (+$37.01), Cycle 39 at 0.55 (+$29.21). The 2 losses were: (1) Cycle 26: last mean reversion attempt at 0.85 (-$41.04), and (2) implied UP reversal attempts that failed. Made 7 HOLD decisions showing excellent discipline. CRITICAL LESSON: Must distinguish between exhaustion in CHOPPY markets (fade it) vs exhaustion in TRENDING markets (follow it). Entry discipline was excellent: all wins at <0.60, losses at >0.80. Confidence calibration (0.62-0.68) was ACCURATE for trend-following, unlike Sessions 2-3 where same confidence on mean reversion was wildly wrong. This session proves the bot CAN adapt strategies based on market regime. The key is early regime detection (30-minute trend check) and strategy switching. Trend-following in strong trends: 7W-0L when entry <0.60. Mean reversion in strong trends: 0W-2L. Strategy selection is more important than pattern recognition. Net position: -$36.38 total (Sessions 2-4 combined), down from -$104.64 after Session 3. Momentum is positive. |

## Current Feature Config
```json
{
  "indicators": [
    {
      "name": "token_momentum",
      "enabled": true,
      "params": {
        "window": 10
      }
    },
    {
      "name": "token_volatility",
      "enabled": true,
      "params": {
        "window": 20
      }
    },
    {
      "name": "token_ma_crossover",
      "enabled": false,
      "params": {
        "short_window": 5,
        "long_window": 20
      }
    },
    {
      "name": "token_mean_reversion",
      "enabled": true,
      "params": {
        "window": 20
      }
    },
    {
      "name": "orderbook_imbalance",
      "enabled": true,
      "params": {}
    },
    {
      "name": "spread_trend",
      "enabled": true,
      "params": {}
    },
    {
      "name": "token_price_divergence",
      "enabled": false,
      "params": {}
    },
    {
      "name": "btc_momentum",
      "enabled": true,
      "params": {
        "window": 10
      }
    },
    {
      "name": "btc_volatility",
      "enabled": true,
      "params": {
        "window": 20
      }
    },
    {
      "name": "btc_candle_momentum",
      "enabled": true,
      "params": {
        "window": 8
      }
    },
    {
      "name": "btc_candle_ma_cross",
      "enabled": true,
      "params": {}
    },
    {
      "name": "session_streak",
      "enabled": true,
      "params": {}
    },
    {
      "name": "confidence_calibration",
      "enabled": true,
      "params": {}
    }
  ]
}
```