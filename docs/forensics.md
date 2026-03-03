# Forensics System — Metric Glossary

All metrics produced by `polybot-forensics` and the `/api/forensics` endpoints.

## Feature A: Order Execution Metrics

| Metric | Definition | Unit |
|--------|-----------|------|
| `order_id` | CLOB order identifier | string |
| `candle_id` | Candle the order belongs to | int |
| `side` | Trade direction: BUY or SELL | string |
| `decision_ts` | Timestamp when AI made the decision | epoch seconds |
| `submit_ts` | Timestamp when order was submitted to CLOB | epoch seconds |
| `decision_to_submit_ms` | Latency from decision to submission: `(submit_ts - decision_ts) * 1000` | milliseconds |
| `decision_ask` | Best ask price at AI decision time (from snapshot) | price |
| `submit_ask` | Best ask price at order submission (from ob_at_submit) | price |
| `ask_drift_bps` | Price drift between decision and submission: `(submit_ask - decision_ask) / decision_ask * 10000` | basis points |
| `filled` | Whether the order was filled | boolean |
| `fill_source` | How fill was detected: `status_poll`, `size_matched`, `post_cancel`, `stealth_balance` | string |
| `fill_ts` | Timestamp when fill was confirmed | epoch seconds |
| `fill_latency_ms` | Time from submission to fill: `(fill_ts - submit_ts) * 1000` | milliseconds |
| `ttl_used` | Time-to-live configured for this order | seconds |
| `balance_delta` | Token balance change: `post_balance - pre_balance` | tokens |

### Aggregates

| Metric | Definition | Unit |
|--------|-----------|------|
| `fill_rate` | Proportion of orders that filled: `filled_count / total_orders` | ratio (0-1) |
| `p50_latency_ms` | Median fill latency | milliseconds |
| `p95_latency_ms` | 95th percentile fill latency | milliseconds |
| `by_fill_source` | Count of orders per fill detection method | dict |

## Feature B: TTL Counterfactuals

| Metric | Definition | Unit |
|--------|-----------|------|
| `actual_ttl` | TTL used when the order was placed | seconds |
| `grid` | Map of TTL values → whether the order would have filled at that TTL | dict[int, bool] |
| `rescue_ttl` | Minimum TTL that would have rescued this timed-out order | seconds |
| `rescued_at` | Number of timed-out orders rescued at each grid TTL level | dict[int, int] |
| `total_timeouts` | Total orders that timed out (cancelled without fill) | int |

## Feature C: Cost Breakdown

| Metric | Definition | Unit |
|--------|-----------|------|
| `fee_amount` | Exchange fee paid on this order | USDC |
| `slippage_bps` | Recorded slippage in basis points | basis points |
| `drift_cost` | Cost of price movement between decision and submission: `(submit_ask - decision_ask) * fill_size` | USDC |
| `total_cost` | Sum of fee + abs(drift_cost) | USDC |
| `total_fees` | Sum of all fees across orders | USDC |
| `total_slippage_cost` | Sum of slippage in dollar terms | USDC |
| `total_drift_cost` | Sum of absolute drift costs | USDC |
| `by_outcome` | Total cost grouped by win/loss outcome | dict |
| `by_side` | Total cost grouped by BUY/SELL | dict |

## Feature D: Blocked Order Analysis

| Metric | Definition | Unit |
|--------|-----------|------|
| `category` | Classified reason for blocking | string |
| `ttl_rescuable` | Whether a longer TTL could have saved this order | boolean |
| `reprice_rescuable` | Whether the book had favorable prices within 10s | boolean |
| `by_category` | Count of blocked orders per category | dict |
| `rescuable_ttl` | Total blocked orders rescuable by TTL extension | int |
| `rescuable_reprice` | Total blocked orders rescuable by repricing | int |

### Block Categories

| Category | Trigger Pattern |
|----------|----------------|
| `kill_switch` | "kill switch" in reason |
| `no_token_id` | "no token_id" in reason |
| `no_book` | "no ask" or "no bid" in reason |
| `max_size` | "exceeds max" in reason |
| `low_balance` | "wallet below min" or "insufficient balance" |
| `timeout` | "limit order timeout" in reason |
| `no_token_balance` | "no on-chain token balance" in reason |
| `error` | "execution error" in reason |
| `dry_run` | "dry run" in reason |
| `other` | Any unmatched reason |

## Feature E: Round-Trips

| Metric | Definition | Unit |
|--------|-----------|------|
| `entry_price` | Fill price of the BUY order | price |
| `exit_price` | Fill price of the matching SELL order | price |
| `size` | Size of the round-trip (min of entry/exit sizes) | tokens |
| `hold_duration_s` | Time held: `exit_ts - entry_ts` | seconds |
| `realized_pnl` | Profit/loss: `(exit_price - entry_price) * size` | USDC |
| `mfe` | Max Favorable Excursion — best mid price during hold | price |
| `mae` | Max Adverse Excursion — worst mid price during hold | price |
| `entry_to_mfe_s` | Time from entry to reaching MFE | seconds |
| `exit_efficiency` | Fraction of MFE potential captured: `realized_pnl / ((mfe - entry) * size)` | ratio |

## Feature F: Decision Context

| Metric | Definition | Unit |
|--------|-----------|------|
| `confidence` | AI confidence score at decision time | 0-1 |
| `rr_ratio` | Risk/reward ratio from nearest snapshot | ratio |
| `indicators` | Active indicator values at decision time | dict[str, float] |
| `ml_score` | ML model score (if model available) | float |
| `outcome` | Resolution result: "win" or "loss" | string |
