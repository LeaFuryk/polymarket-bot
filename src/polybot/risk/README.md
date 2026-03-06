# risk — Pre-trade and Post-trade Risk Management

Two-stage risk checking: pre-trade (before AI call) and post-trade (before execution).

## Modules

| File | Class/Contents | Responsibility |
|------|---------------|----------------|
| `constants.py` | `DEFAULT_FILL_PRICE`, `DEPTH_RATIO_LIMIT`, etc. | Named constants |
| `manager.py` | `RiskManager` | Pre/post trade checks, daily tracking, drawdown |

## Risk Checks

### Pre-trade (before AI call — saves API cost)
| Check | Blocks when |
|-------|------------|
| `halt_check` | Trading is halted (daily loss breached) |
| `daily_loss_limit` | Daily PnL exceeds configured loss limit |
| `min_liquidity` | Both up/down orderbooks are thin |

### Post-trade (before execution)
| Check | Applies to | Blocks when |
|-------|-----------|------------|
| `max_spread` | BUY only | Spread % exceeds threshold |
| `max_position_size` | BUY only | Position value would exceed limit |
| `concentration_limit` | BUY only | Single-token exposure too high |
| `cash_sufficiency` | BUY only | Not enough cash (with fee buffer) |
| `short_sell_prevention` | SELL only | Selling more shares than held |
| `order_vs_depth` | BUY/SELL | Order > 50% of available depth |

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEFAULT_FILL_PRICE` | 0.5 | Fallback when best ask/bid unavailable |
| `CASH_BUFFER_FACTOR` | 1.005 | 0.5% fee buffer on cash check |
| `SHORT_SELL_TOLERANCE` | 1e-9 | Float tolerance for sell clamping |
| `DEPTH_RATIO_LIMIT` | 0.5 | Max fraction of depth per order |

## Design Notes

- SELL orders are never blocked by spread (exits should always be possible)
- Pre-trade checks use both orderbooks; post-trade checks use the token-specific book
- Daily counters reset automatically on UTC date change
