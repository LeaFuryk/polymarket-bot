# simulator — Trade Execution Simulation

Simulates order execution against live orderbook snapshots for paper trading.

## Modules

| File | Class/Contents | Responsibility |
|------|---------------|----------------|
| `constants.py` | `BPS_DIVISOR`, `FILL_PRICE_*`, etc. | All magic numbers as named constants |
| `engine.py` | `ExecutionSimulator` | Market order fills with realistic slippage & fees |
| `orderbook.py` | `SimulatedOrderBook` | Pending limit orders, TTL expiry, fill matching |
| `portfolio.py` | `Portfolio` | Dual-position tracking (Up/Down), cash, PnL |

## Execution Pipeline

1. **Decision arrives** — `TradingDecision` from the decision engine
2. **Market orders** → `ExecutionSimulator.execute()` computes slippage + fees → `SimulatedFill`
3. **Limit orders** → `SimulatedOrderBook.add_order()` queues them; `check_fills()` matches against subsequent orderbook snapshots
4. **Fill applied** → `Portfolio.apply_fill()` updates position, cash, fees
5. **Resolution** → `Portfolio.resolve_market(winner)` settles at $1/$0

## Slippage Model

```
slippage_bps = base_bps + (order_size / total_liquidity) * proportional_factor * 10000
```

- Empty orderbook (no quotes): returns `base_bps`
- Zero liquidity (quotes exist, no depth): `base_bps * THIN_BOOK_PENALTY_FACTOR`
- Fill prices clamped to `[0.001, 0.999]`

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `BPS_DIVISOR` | 10,000 | Basis points → decimal |
| `THIN_BOOK_PENALTY_FACTOR` | 3.0 | Slippage multiplier for zero-depth books |
| `FILL_PRICE_MIN/MAX` | 0.001 / 0.999 | Prediction market price bounds |
| `WINNING_TOKEN_PAYOUT` | 1.0 | Resolution payout per winning share |
| `OVERSELL_TOLERANCE` | 1e-9 | Float tolerance for sell clamping |
