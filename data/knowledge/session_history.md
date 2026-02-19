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
| Session 5 | 1W-1L | -$6.09 | **REALITY CHECK ON TREND-FOLLOWING**: Small session (2 trades) showing that even validated strategies aren't perfect. Continuation of Session 4's downtrend environment. Cycle 2 won (+$33.56) buying UP at 0.44 - BTC moved DOWN $6 but "up" won by default (flat candle). Lucky win on excellent entry price. Cycle 3 lost (-$39.65) buying UP at 0.66 after mixed action. CRITICAL ERROR: Entry at 0.66 violated the <0.60 rule for trend-following. This was preventable loss due to entry discipline failure. KEY LESSONS: (1) Trend-following is probabilistic (78% Session 4, 50% Session 5) - not guaranteed. (2) Entry price discipline is CRITICAL - 0.66 entry had insufficient edge. (3) After 1 counter-trend candle (micro-reversal), next candle often resumes trend but not always. (4) Confidence should be reduced from 0.62-0.68 to 0.60-0.66 for trend-following. (5) Small sample (2 trades) but reinforces that no pattern is 100% reliable. Updated rules: STRICT <0.60 entry for trend-following, reduce confidence after micro-reversals. Overall progress remains positive: +$56.29 over Sessions 4-5 combined (from -$104.64 after Session 3). Trend-following record: 8W-3L (73% win rate) across Sessions 4-5. Strategy is validated but requires discipline. |
| Session 6 | 2W-2L-1BE | -$1.09 | **MOMENTUM CHASING ERROR**: Session with 50% win rate (2W-2L) and small loss. Key failure: Cycle 5 bought UP at 0.66 and added at 0.81 AFTER BTC had moved up $186 - classic momentum chasing at expensive prices. Market reversed DOWN $95 for -$22.71 loss. This violated entry discipline (<0.60 rule) and ignored exhaustion risk after large move. Cycle 3 also lost (-$39.65) with 0.66 entry. Wins came from: Cycle 2 (+$33.56) at 0.44 entry (flat candle, lucky), and Cycle 6 (+$27.91) with good 0.51 entry and smart profit-taking exit at 0.88. CRITICAL LESSONS: (1) Don't chase continuation after >$150 moves at prices >0.60. (2) Entry discipline violations (0.66, 0.81) caused both losses. (3) Profit-taking works - exiting at 0.88 was smart. (4) Confidence needs further reduction to 0.58-0.64 (from 0.60-0.66). (5) New pattern identified: EXHAUSTION RISK after large moves requires HOLD or reduced confidence. Updated rules: After >$150 move, avoid entries >0.60, reduce confidence by 0.10. Trend-following record across Sessions 4-6: 10W-5L (67% win rate, +$55.20 total). Strategy remains valid but requires STRICT entry discipline. The 0.66 and 0.81 entries were clear violations that caused preventable losses. Must add exhaustion check to pre-trade checklist. |
| Session 7 | 3W-2L-1BE | +$7.37 | **PROFIT-TAKING MASTERY**: Session demonstrating the power of exit discipline. 60% win rate (3W-2L) with +$7.37 profit. KEY BREAKTHROUGH: Profit-taking exits at 0.78 when bought at 0.41 had 100% success rate (2/2 wins). Cycle 19: bought DOWN at 0.41, sold at 0.78 for +$20.82. Cycle 20: bought DOWN at 0.41, sold at 0.78 for +$20.82 (avoided -$20.35 loss by exiting early). Cycle 23: bought DOWN at 0.23, sold at 0.23 for breakeven (avoided -$12.67 loss). CRITICAL LESSONS: (1) Exit discipline is as important as entry discipline. (2) Taking profits at 0.78-0.88 when bought at 0.23-0.51 captures optimal edge. (3) Exiting profitable positions with <120s remaining is smart strategy. (4) Early loss-cutting works - breakeven exit avoided loss. (5) Entry discipline maintained - all entries at 0.23-0.51 range. (6) Confidence calibration accurate - 0.62-0.64 with 60% win rate is well-aligned. Updated rules: (1) Take profits when position up 15-20%. (2) Exit profitable positions when time <120s. (3) Consider early exits when setup clearly wrong. Trend-following record across Sessions 4-7: 13W-7L (65% win rate, +$62.57 total). Profit-taking record: 3W-0L (100% success rate). The combination of entry discipline (0.23-0.55) + exit discipline (0.78-0.88) is the winning formula. Overall progress: +$62.57 over 4 sessions, validating the trend-following + profit-taking strategy. |
| Session 8 | 4W-2L-2BE | +$43.16 | **CONTINUED EXCELLENCE**: Strong session with 67% win rate (4W-2L) and +$43.16 profit. Profit-taking and loss-cutting discipline both validated. Cycle 10: bought UP at 0.37, sold at 0.71 for +$20.40 profit-taking WIN. Cycle 14: bought DOWN at 0.83, sold at 0.66 for loss-cutting (avoided larger loss). Cycle 12: bought DOWN at 0.29, won +$20.32 on $263 DOWN move. Cycle 16: bought UP at 0.29, won +$19.14 on $50 UP move (micro-trend continuation). CRITICAL LESSONS: (1) Profit-taking at 0.66-0.93 when bought at 0.23-0.51 continues to work (now 5/5 success rate across Sessions 7-8). (2) Loss-cutting at 0.66 when bought at 0.83 avoided larger loss - early exit discipline validated. (3) Small consistent moves ($11-$50) can continue in trending environments with 6+ consecutive candles - don't dismiss micro-trends. (4) Entry discipline mostly maintained: 3 excellent entries (0.29-0.37), 1 violation (0.83 that was quickly cut). (5) Win rate of 67% aligns perfectly with expected 65% for trend-following strategy. (6) Confidence calibration at 0.62 with 67% win rate is well-aligned. Updated insights: Recognize micro-trends (small consistent moves) as tradeable with excellent entry prices. Exit discipline (both profit-taking and loss-cutting) is as critical as entry discipline. Trend-following record across Sessions 4-8: 17W-9L (65% win rate, +$105.73 total). Profit-taking record: 5W-0L (100% success rate). Overall progress: +$105.73 over 5 sessions. The strategy is validated and consistently profitable: trend-following with strict entry discipline (0.23-0.55) + exit discipline (profit-taking at 0.66-0.93, loss-cutting when wrong). |

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
        "window": 15
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
      "enabled": true,
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
        "window": 15
      }
    },
    {
      "name": "btc_candle_momentum",
      "enabled": true,
      "params": {
        "window": 6
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