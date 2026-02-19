# Market Making Strategy — Implementation Plan

## Overview

Add a market making (MM) strategy that runs alongside the existing directional strategy. Instead of predicting BTC direction, the MM earns revenue by providing liquidity on both sides of the orderbook, collecting spread + Polymarket's liquidity rewards + 20% maker rebates on 5-min crypto markets.

Reference: https://docs.polymarket.com/market-makers/overview

---

## Revenue Sources

| Source | How it works |
|--------|-------------|
| **Spread** | Split $100 USDC → 100 UP + 100 DOWN tokens. Sell UP at 0.52 + DOWN at 0.52 = collect $1.04 for $1.00 of tokens = $0.04 profit per round trip |
| **Liquidity rewards** | Daily payout based on Q-score. Formula: `S(v,s) = ((v-s)/v)^2 * b`. Tighter quotes near midpoint = exponentially higher score. Two-sided quoting required. Sampled every minute, distributed daily at midnight UTC |
| **Maker rebates** | 20% rebate rate on 5-min crypto markets. Resting limit orders that get filled earn back 20% of taker fees. Paid daily in USDC |

## Key Concepts from Polymarket Docs

### Inventory via Split/Merge (not buying from orderbook)
- `splitPosition(collateral, conditionId, [1,2], amount)` — Convert USDC.e into equal UP + DOWN tokens
- `mergePositions(...)` — Convert equal UP + DOWN tokens back to USDC.e
- `redeemPositions(...)` — After resolution, convert winning tokens to USDC.e at 1:1
- All operations are gasless via Relayer Client

### Q-Score Formula (Liquidity Rewards)
```
S(v, s) = ((v - s) / v)^2 * b

v = max spread allowed for market (from CLOB API: max_incentive_spread)
s = actual spread from adjusted midpoint
b = in-game multiplier

Two-sided scoring:
  Qne = sum of bid orders (primary) + ask orders (complement)
  Qno = sum of ask orders (primary) + bid orders (complement)
  Qmin = min(Qne, Qno)  — penalizes one-sided quoting

Single-sided penalty:
  midpoint 0.10-0.90 → score / 3.0
  midpoint 0-0.10 or 0.90-1.0 → zero score (two-sided required)
```

### Order Types
- **GTC** (Good-Till-Cancelled) — Primary for resting quotes
- **GTD** (Good-Till-Date) — Auto-expire before resolution. Critical for 5-min markets
- **FOK** (Fill-or-Kill) — Aggressive rebalancing, full fill or nothing
- **FAK** (Fill-and-Kill) — Partial fills OK during rebalancing
- Batch API supports up to 15 orders per request

### Market-Specific Parameters (fetched from CLOB API)
- `min_incentive_size` — Minimum order size to qualify for rewards
- `max_incentive_spread` — Maximum spread for reward eligibility
- Tick size (0.1, 0.01, 0.001, or 0.0001) — Prices must conform

---

## Architecture

### New Files

```
src/polybot/
├── strategies/
│   ├── __init__.py
│   ├── directional.py       # Extract current logic from agent.py
│   └── market_maker.py      # New MM strategy
├── market_data/
│   ├── websocket.py          # NEW: Real-time orderbook + fill notifications
│   └── relayer.py            # NEW: Split/merge/redeem via Relayer Client
```

### Modified Files

```
src/polybot/agent.py          # Strategy selector, run both in parallel
src/polybot/config.py          # Add MarketMakerConfig
src/polybot/models.py          # Add MM-specific models
src/polybot/simulator/engine.py  # Add limit order simulation
dashboard/index.html           # Add MM metrics (spread earned, fills, Q-score)
```

---

## Phase 1: Infrastructure (WebSocket + Relayer)

### 1.1 WebSocket Client (`market_data/websocket.py`)

The current bot polls REST every 30s. MM needs real-time data.

```python
class PolymarketWebSocket:
    """Real-time orderbook updates and fill notifications."""

    async def connect(self, market_channel: str, user_channel: str):
        """Connect to wss://ws-subscriptions-clob.polymarket.com/ws/market"""

    async def on_orderbook_update(self, callback):
        """Market channel: orderbook deltas, price changes, trade events"""

    async def on_fill(self, callback):
        """User channel: order fills, cancellations, position changes"""
```

- Use `websockets` library
- Market channel for orderbook updates (public)
- User channel for fill notifications (authenticated)
- Auto-reconnect with exponential backoff
- Heartbeat/ping to detect stale connections

### 1.2 Relayer Client (`market_data/relayer.py`)

```python
class RelayerClient:
    """Gasless split/merge/redeem via Polymarket Relayer."""

    async def split_position(self, condition_id: str, amount: float):
        """Split USDC.e → equal UP + DOWN tokens"""

    async def merge_positions(self, condition_id: str, amount: float):
        """Merge equal UP + DOWN → USDC.e"""

    async def redeem_positions(self, condition_id: str):
        """Post-resolution: redeem winning tokens → USDC.e"""
```

- Wrap `py-clob-client` CTF/Relayer methods
- Handle USDC.e 6-decimal precision
- Track token balances locally (verify against on-chain)

### 1.3 Config Addition

```python
class MarketMakerConfig(BaseModel):
    enabled: bool = False
    strategy: str = "mm"                    # "mm" or "directional" or "both"
    split_amount: float = 200.0             # USDC to split per candle
    target_spread_bps: float = 200          # 2% target spread
    min_spread_bps: float = 100             # 1% floor (must exceed fees)
    max_inventory_imbalance: float = 0.7    # Max 70% on one side
    quote_refresh_seconds: float = 5.0      # How often to update quotes
    flatten_at_seconds: int = 60            # Cancel all at T-60s
    order_size: float = 25.0               # Per-side order size
    num_levels: int = 3                     # Orders per side at different prices
```

---

## Phase 2: Market Maker Core (`strategies/market_maker.py`)

### 2.1 Lifecycle per Candle

```
on_new_candle(market):
  1. Fetch market params (tick_size, min_incentive_size, max_incentive_spread)
  2. Split USDC → UP + DOWN tokens
  3. Compute initial fair value (0.50 at candle open, adjust with BTC)
  4. Post initial two-sided quotes (GTD, expire at T-30s)
  5. Start quote_loop

quote_loop (every 5-10s):
  1. Receive orderbook update from WebSocket
  2. Recompute fair value from BTC price trend
  3. Check inventory balance (fills shift your exposure)
  4. Compute new bid/ask prices:
     - fair_value ± half_spread (base)
     - skew toward shedding excess inventory
     - respect tick size
  5. Cancel stale orders
  6. Post new quotes (batch API, up to 15)

on_fill(fill_event):
  1. Update local inventory tracker
  2. Log fill for dashboard
  3. If imbalance > threshold → trigger rebalance
  4. If paired tokens available → merge to recover USDC

on_pre_resolution (T-60s):
  1. Cancel ALL open orders
  2. Merge any paired tokens → USDC
  3. Remaining unpaired tokens = directional risk (accept or dump)

on_resolution(winner):
  1. Redeem winning tokens → USDC
  2. Log P&L (spread earned + inventory P&L + rewards)
  3. Prepare for next candle
```

### 2.2 Fair Value Computation

The MM needs a fair value estimate to center quotes around. Options:

```python
def compute_fair_value(self, btc_price, candle_open, time_remaining):
    """Estimate probability of UP outcome for quote centering."""

    # Simple: current BTC vs candle open
    btc_change = btc_price - candle_open
    # Larger positive change → higher UP probability
    # Use a logistic function centered at 0
    z = btc_change / volatility_estimate
    up_prob = 1 / (1 + exp(-k * z))

    # Time decay: as resolution approaches, prices converge to 0 or 1
    # Widen spread as uncertainty decreases near resolution
    time_factor = time_remaining / 300  # 0→1

    return up_prob  # This is the fair value for UP token
```

This is where the **directional strategy's BTC analysis can feed the MM**: if the directional model has high confidence in DOWN, the MM can skew fair value slightly bearish, moving quotes to shed UP inventory.

### 2.3 Inventory Management

```python
class InventoryManager:
    up_tokens: float = 0.0
    down_tokens: float = 0.0
    usdc_reserved: float = 0.0

    @property
    def imbalance(self) -> float:
        """0.0 = perfectly balanced, 1.0 = fully one-sided"""
        total = self.up_tokens + self.down_tokens
        if total == 0: return 0.0
        return abs(self.up_tokens - self.down_tokens) / total

    @property
    def skew_direction(self) -> str:
        """Which side we're overweight"""
        return "up" if self.up_tokens > self.down_tokens else "down"

    def compute_quote_skew(self) -> float:
        """How much to shift quotes to shed excess inventory.
        Positive = lower UP ask (shed UP), negative = lower DOWN ask (shed DOWN)"""
        return (self.up_tokens - self.down_tokens) / max(self.up_tokens + self.down_tokens, 1) * skew_factor
```

### 2.4 Quote Calculation

```python
def compute_quotes(self, fair_value, inventory_skew, time_remaining):
    half_spread = self.target_spread / 2

    # Widen spread near resolution (less time to recover from adverse selection)
    time_factor = max(0.3, time_remaining / 300)
    adjusted_spread = half_spread / time_factor

    # Skew to shed inventory
    up_ask = fair_value + adjusted_spread - inventory_skew
    up_bid = fair_value - adjusted_spread - inventory_skew
    down_ask = (1 - fair_value) + adjusted_spread + inventory_skew
    down_bid = (1 - fair_value) - adjusted_spread + inventory_skew

    # Clamp to [0.01, 0.99] and round to tick size
    return snap_to_tick(up_bid, up_ask, down_bid, down_ask, tick_size)
```

---

## Phase 3: Strategy Orchestration in Agent

### 3.1 Strategy Selection

```python
# In agent.py
class TradingAgent:
    def __init__(self, config):
        if config.mm.strategy in ("mm", "both"):
            self._market_maker = MarketMaker(config, self._ws_client, self._relayer)
        if config.mm.strategy in ("directional", "both"):
            self._directional = DirectionalStrategy(config, ...)

    async def _run_cycle(self, market, snapshot):
        if self._market_maker:
            await self._market_maker.update(market, snapshot)
        if self._directional:
            await self._directional.decide(market, snapshot)
```

### 3.2 Shared Intelligence

The directional strategy's BTC analysis feeds the MM:
- Directional confidence → MM fair value skew
- BTC momentum indicators → MM spread width (widen in volatile markets)
- Knowledge files' pattern insights → MM parameter tuning

---

## Phase 4: Dashboard Integration

### New MM Metrics to Track

```python
# Per-candle MM stats
{
    "mm_spread_earned": 0.04,       # Revenue from spread capture
    "mm_fills": 8,                  # Total fills (both sides)
    "mm_up_fills": 4,               # Fills on UP side
    "mm_down_fills": 4,             # Fills on DOWN side
    "mm_inventory_pnl": -0.02,     # P&L from unhedged inventory at resolution
    "mm_total_pnl": 0.02,          # spread_earned + inventory_pnl
    "mm_avg_spread_bps": 180,       # Average quoted spread
    "mm_q_score": 0.45,            # Estimated Q-score for rewards
    "mm_tokens_split": 200,        # USDC split into tokens
    "mm_tokens_merged": 180,       # Tokens merged back to USDC
}
```

### Dashboard Panel

Add a "Market Making" panel showing:
- Spread P&L vs inventory P&L breakdown
- Fill rate (what % of quotes got filled)
- Inventory balance chart over candle lifetime
- Estimated daily rewards from Q-score

---

## Phase 5: Risk Management

### MM-Specific Risks

| Risk | Mitigation |
|------|-----------|
| **Adverse selection** | Widen spread when BTC moving fast. Use BTC volatility indicator to detect |
| **Inventory risk at resolution** | Hard flatten at T-60s. Accept small loss to avoid binary payoff gamble |
| **One-sided fills** | Skew quotes aggressively when imbalance > 50%. Pause quoting if > 70% |
| **API failures** | If WebSocket drops, cancel all orders immediately via REST. No blind quoting |
| **Negative spread** | Validate every quote: `bid < ask` and `up_ask + down_ask > 1.0` (no arb) |
| **Stale quotes** | GTD with expiry. If quote_loop fails to update for 15s, cancel all |

### Combined Risk with Directional

When running both strategies:
- Separate capital pools (e.g. 60% directional, 40% MM)
- Shared daily loss limit applies to combined P&L
- MM can be paused independently if losing money
- Directional positions and MM inventory don't interfere (different accounting)

---

## Implementation Order

1. **WebSocket client** — foundation for everything, useful for directional too
2. **Relayer client** — split/merge operations
3. **MM core with static quotes** — simplest version: split, post fixed-spread quotes, let them fill, flatten at T-60s
4. **Dynamic quoting** — BTC-based fair value, inventory skew, adaptive spread
5. **Dashboard integration** — MM-specific metrics and panels
6. **Strategy orchestration** — run both strategies in parallel with shared intelligence
7. **Rewards optimization** — tune quotes for Q-score maximization (tighter near midpoint, two-sided always)

---

## Open Questions

- **Capital allocation**: How much USDC to dedicate to MM vs directional? Start with 30% MM.
- **Live vs simulated**: Should MM start in simulation mode like directional? Probably yes — simulate fills against real orderbook first.
- **Authentication**: MM requires authenticated API access for placing orders and receiving fill notifications. Current bot may only use public endpoints. Need to verify `py-clob-client` supports authenticated order placement or if we need to add API key auth.
- **Minimum viable test**: Could start by just splitting + posting wide quotes on 1 candle to validate the mechanics before building the full loop.
