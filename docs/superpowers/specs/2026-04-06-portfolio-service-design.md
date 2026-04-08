# Portfolio Service Design Spec

## Goal

Track portfolio state (cash, positions, PnL) for paper and live trading. Dual-position model (UP + DOWN shares simultaneously). In-memory, resets on restart. Saves session summary to `data/sessions.jsonl` on shutdown.

## Architecture

Hexagonal. `PortfolioService` is a pure domain service with no external dependencies. `SessionStore` port abstracts persistence. `JsonlSessionStore` adapter writes session summaries. Domain models (`Position`, `PortfolioState`) are frozen dataclasses.

## Domain Models

### `Position`

File: `polybot/domain/portfolio.py`

```python
@dataclass
class Position:
    side: str  # "UP" | "DOWN"
    shares: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
```

### `PortfolioState`

File: `polybot/domain/portfolio.py`

```python
@dataclass
class PortfolioState:
    cash: float
    up_position: Position
    down_position: Position
    wins: int = 0
    losses: int = 0
```

Methods:
- `total_value(up_price: float, down_price: float) -> float` — cash + up_shares * up_price + down_shares * down_price
- `unrealized_pnl(up_price: float, down_price: float) -> float` — current value of open positions minus cost basis
- `net_pnl(up_price: float, down_price: float) -> float` — realized + unrealized

## Service: `PortfolioService`

File: `polybot/services/portfolio_service.py`

Constructor: `__init__(initial_cash: float = 1000.0)`

Methods:
- `buy(side: str, amount_usd: float, price: float) -> None` — buy shares at price, deduct cash. Shares = amount_usd / price. Updates avg_entry_price weighted.
- `sell(side: str, shares: float, price: float) -> None` — sell shares at price, credit cash. Updates realized_pnl.
- `settle(winning_side: str) -> None` — resolution: winning shares pay $1 each, losing shares worth $0. Updates cash, realized_pnl, wins/losses counts, clears both positions.
- `state -> PortfolioState` — property returning current state.
- `session_summary(up_price: float, down_price: float) -> dict` — returns dict with: wins, losses, win_rate, realized_pnl, unrealized_pnl, net_pnl, final_balance, initial_cash, total_return_pct.

Validation:
- `buy` raises `ValueError` if insufficient cash
- `sell` raises `ValueError` if insufficient shares
- `settle` only acts on non-zero positions

## Port: `SessionStore`

File: `polybot/ports/session_store.py`

```python
@runtime_checkable
class SessionStore(Protocol):
    async def save_session(self, summary: dict) -> None: ...
```

## Adapter: `JsonlSessionStore`

File: `polybot/adapters/jsonl_session_store.py`

- Appends one JSON line to a file path (default `data/sessions.jsonl`)
- Adds `timestamp` field (epoch seconds) to each entry
- Creates file if it doesn't exist
- Async file write

## Wiring

In `polybot/__main__.py`:
- Create `PortfolioService(initial_cash=float(os.environ.get("POLYBOT_TRADING_INITIAL_CASH", "1000.0")))`
- Create `JsonlSessionStore("data/sessions.jsonl")`
- In `finally` block on shutdown: `await store.save_session(portfolio.session_summary(last_up_price, last_down_price))`
- Log session summary to console on shutdown

## What This Does NOT Include

- Order execution (placing trades on Polymarket)
- AI decision logic (when to buy/sell)
- Risk management (stop-loss, take-profit)
- Position monitoring
- Live exchange position sync

## Testing

- `Position`: test share accounting, avg price weighting
- `PortfolioState`: test value/PnL calculations
- `PortfolioService`: test buy/sell/settle lifecycle, validation errors, session summary
- `JsonlSessionStore`: test file append, JSON format
