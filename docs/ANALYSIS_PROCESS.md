# Post-Iteration Analysis Process

Standard methodology for analyzing each completed iteration. Run after every `polybot-archive` to extract actionable insights before starting the next iteration.

---

## Prerequisites

1. Archive completed: `archive/iter_NNN/` exists with `summary.json`
2. Trade logs available: `archive/iter_NNN/logs/trades_*.jsonl`
3. Resolution logs available: `archive/iter_NNN/logs/resolutions_*.jsonl`

---

## Phase 1: Summary Overview

**Source**: `archive/iter_NNN/summary.json`

Extract and record:
- Total candles, wins, losses, win rate
- Total PnL, fees, AI cost, net result
- Profit factor: `total_winner_pnl / abs(total_loser_pnl)`
- Comparison deltas from previous iteration

### Cross-Iteration Comparison Table

| Metric | iter_001 | iter_002 | ... | Current |
|--------|----------|----------|-----|---------|
| Net PnL | | | | |
| Win Rate | | | | |
| Candles | | | | |
| Avg Win | | | | |
| Avg Loss | | | | |
| Profit Factor | | | | |

---

## Phase 2: Deep Loss Analysis

**Source**: Match trades JSONL against resolutions JSONL for all candles where `total_pnl < 0`.

### 2.1 Build Loss Table

For each losing candle, extract:
- Candle slug and timestamp
- All BUY/SELL actions on that candle (token side, entry price, fill size, confidence, reasoning)
- BTC open, close, move direction and magnitude
- Winner (UP/DOWN)
- Total PnL
- Whether SELL exits occurred

### 2.2 Classify Each Loss

Assign one or more categories:

| Category | Criteria | Example |
|----------|----------|---------|
| **Multi-Trade Candle** | 2+ BUY entries on same candle (bought one side, sold, bought other) | Bought DOWN, sold, bought UP — both lost |
| **Chainlink Divergence** | Winner disagrees with Binance BTC direction; Chainlink divergence > $100 | BTC UP on Binance but winner = DOWN |
| **Counter-Trend** | Bot traded against prevailing market direction (trend score) | Bought DOWN in +0.47 bullish trend |
| **Reversal** | BTC direction at entry time reversed by candle close | BTC was -$40 at entry, closed +$60 |
| **Bad R/R** | Entry price > $0.60 with BTC move < $50 | Entry at $0.75 on $27 BTC move |
| **Premature Stop-Loss** | Bot exited a position that would have won if held | Sold DOWN at $0.46, DOWN ultimately won |

### 2.3 Aggregate by Category

Calculate total PnL impact per category. This reveals which patterns cause the most damage.

### 2.4 Weird Losses Investigation

Flag any candle where:
- The bot's predicted direction was correct (winner matches token side bought) BUT total_pnl < 0
- This indicates structural issues (multi-trade candles, premature exits, bad sizing)

For each weird loss, build a **full timeline reconstruction**:
1. Every trade action with timestamp, price, size
2. BTC price at each action
3. Why the bot exited
4. What would have happened if held

---

## Phase 3: Deep Winner Analysis

**Source**: Match trades JSONL against resolutions JSONL for all candles where `total_pnl > 0`.

### 3.1 Entry Price Buckets

| Bucket | Count | Total PnL | Avg PnL | ROI% |
|--------|-------|-----------|---------|------|
| < $0.40 | | | | |
| $0.40-0.55 | | | | |
| $0.55-0.70 | | | | |
| > $0.70 | | | | |

ROI% = `avg_pnl / (avg_entry_price * avg_size) * 100`

**Key question**: Are cheap entries (<$0.55) producing outsized returns per dollar risked?

### 3.2 Confidence Calibration

| Stated Confidence | Total Buys | Wins | Actual Win% | Gap | Assessment |
|-------------------|-----------|------|-------------|-----|------------|
| 0.60-0.64 | | | | | Under/Over/Calibrated |
| 0.66-0.70 | | | | | |
| 0.72-0.74 | | | | | |
| 0.76+ | | | | | |

**Key question**: Is the bot's confidence well-calibrated? Look for inversions (higher confidence = lower win rate).

### 3.3 Timing Analysis

| Time Remaining | Winner Count | Avg PnL | All Win% |
|---------------|-------------|---------|----------|
| >250s (very early) | | | |
| 200-250s | | | |
| 150-200s | | | |
| 100-150s | | | |
| <100s | | | |

**Key question**: Do early entries get better prices and higher PnL?

### 3.4 UP vs DOWN Side Analysis

Compare win count, win rate, total PnL, avg PnL per side. Check if the bot correctly adapts to the session's BTC trajectory.

### 3.5 BTC Move Magnitude

Group winners by absolute BTC move size. Find the sweet spot where the bot gets good entries before tokens fully reprice.

### 3.6 SELL Exit Quality

For each SELL on a winning candle:
- What % of max value was captured? (sell_price / 1.00)
- Is the bot leaving money on the table?

For each SELL on a losing candle:
- How much capital was saved vs holding to expiry?

### 3.7 Position Sizing Analysis

Group by fill size. Are larger positions producing better per-trade results? Is the bot sizing uniformly when it should be adapting?

---

## Phase 4: Actionable Recommendations

### 4.1 Loss Reduction Fixes

Rank by estimated $/iteration impact. For each:
- **Problem**: What pattern causes the loss
- **Fix**: Specific code change or rule
- **Impact**: Estimated $ saved per iteration
- **Risk to wins**: Does this fix accidentally block winning trades?

### 4.2 Win Amplification Opportunities

Same structure — opportunities to increase winning trades without adding risk:
- **Opportunity**: What the data shows
- **Fix**: Specific change
- **Impact**: Estimated $ gained per iteration
- **Why low-risk**: Explain why this doesn't increase downside

### 4.3 Priority Matrix

| Fix | Impact | Effort | Risk | Priority |
|-----|--------|--------|------|----------|
| | | | | |

---

## Phase 5: Dashboard Update

After completing analysis:

1. Add `deep_analysis` object to the iteration entry in `logs/iterations.json`
2. Include: summary stats, loss classifications, entry price buckets, confidence calibration, side analysis, timing buckets, exit quality, weird losses, actionable fixes
3. Dashboard renders this automatically via `buildDeepAnalysisSection()`

---

## Phase 6: Cross-Iteration Trends

After 3+ iterations, track trends:

### Persistent Patterns
- Which loss categories appear across multiple iterations?
- Are the same fixes needed repeatedly (indicating they haven't been implemented)?

### Improvement Trajectory
- Is profit factor improving?
- Is avg loss shrinking?
- Is win rate stable?

### Regression Detection
- Any metrics getting worse?
- New loss categories appearing?

---

## Output Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| `iterations.json` | `logs/iterations.json` | Dashboard data with deep_analysis |
| Analysis report | This document (as reference) | Standardized methodology |
| Dashboard view | `dashboard/index.html` → iteration detail | Visual presentation |

---

## Checklist

- [ ] Summary overview extracted and cross-iteration table updated
- [ ] All losing candles classified by category
- [ ] Weird losses (correct prediction but lost money) investigated with full timeline
- [ ] Winner analysis: entry price buckets, confidence calibration, timing, side, sizing
- [ ] Actionable fixes ranked by impact with risk assessment
- [ ] `deep_analysis` added to `logs/iterations.json`
- [ ] Dashboard verified — deep analysis section renders correctly
- [ ] CHANGELOG.md updated
- [ ] README.md updated if structural changes
