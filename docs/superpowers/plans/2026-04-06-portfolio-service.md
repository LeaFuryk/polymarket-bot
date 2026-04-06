# Portfolio Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track portfolio state (cash, dual positions UP/DOWN, PnL, W/L) in-memory, with session summary saved to JSONL on shutdown.

**Architecture:** Hexagonal. Pure domain models (`Position`, `PortfolioState`) + `PortfolioService` with no external deps. `SessionStore` port for persistence, `JsonlSessionStore` adapter. Wired into `__main__.py` shutdown hook.

**Tech Stack:** Python 3.11, pytest, aiofiles (or plain async file IO)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `polybot/domain/__init__.py` | Create | Domain package init |
| `polybot/domain/portfolio.py` | Create | `Position` + `PortfolioState` dataclasses |
| `polybot/services/portfolio_service.py` | Create | Buy/sell/settle logic, session summary |
| `polybot/ports/session_store.py` | Create | `SessionStore` protocol |
| `polybot/adapters/jsonl_session_store.py` | Create | Append JSON lines to file |
| `polybot/__main__.py` | Modify | Wire portfolio + session store, save on shutdown |
| `tests/polybot/test_portfolio.py` | Create | Domain model tests |
| `tests/polybot/test_portfolio_service.py` | Create | Service lifecycle tests |
| `tests/polybot/test_jsonl_session_store.py` | Create | Adapter tests |

---

### Task 1: Domain models — Position and PortfolioState

**Files:**
- Create: `polybot/domain/__init__.py`
- Create: `polybot/domain/portfolio.py`
- Create: `tests/polybot/test_portfolio.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for portfolio domain models."""

from polybot.domain.portfolio import Position, PortfolioState


class TestPosition:
    def test_default_position(self):
        p = Position(side="UP")
        assert p.shares == 0.0
        assert p.avg_entry_price == 0.0
        assert p.realized_pnl == 0.0

    def test_position_with_values(self):
        p = Position(side="DOWN", shares=10.0, avg_entry_price=0.45, realized_pnl=2.5)
        assert p.shares == 10.0
        assert p.avg_entry_price == 0.45
        assert p.realized_pnl == 2.5


class TestPortfolioState:
    def test_total_value_no_positions(self):
        state = PortfolioState(
            cash=1000.0,
            up_position=Position(side="UP"),
            down_position=Position(side="DOWN"),
        )
        assert state.total_value(0.55, 0.45) == 1000.0

    def test_total_value_with_positions(self):
        state = PortfolioState(
            cash=900.0,
            up_position=Position(side="UP", shares=20.0, avg_entry_price=0.50),
            down_position=Position(side="DOWN", shares=10.0, avg_entry_price=0.40),
        )
        # 900 + 20*0.55 + 10*0.45 = 900 + 11 + 4.5 = 915.5
        assert state.total_value(0.55, 0.45) == 915.5

    def test_unrealized_pnl(self):
        state = PortfolioState(
            cash=900.0,
            up_position=Position(side="UP", shares=20.0, avg_entry_price=0.50),
            down_position=Position(side="DOWN"),
        )
        # Market value: 20 * 0.60 = 12.0, cost basis: 20 * 0.50 = 10.0, unrealized = 2.0
        assert state.unrealized_pnl(0.60, 0.40) == 2.0

    def test_unrealized_pnl_no_positions(self):
        state = PortfolioState(
            cash=1000.0,
            up_position=Position(side="UP"),
            down_position=Position(side="DOWN"),
        )
        assert state.unrealized_pnl(0.55, 0.45) == 0.0

    def test_net_pnl(self):
        state = PortfolioState(
            cash=900.0,
            up_position=Position(side="UP", shares=20.0, avg_entry_price=0.50, realized_pnl=5.0),
            down_position=Position(side="DOWN", shares=10.0, avg_entry_price=0.40, realized_pnl=-2.0),
        )
        # realized = 5.0 + (-2.0) = 3.0
        # unrealized: up = 20*(0.55-0.50)=1.0, down = 10*(0.45-0.40)=0.5 => 1.5
        # net = 3.0 + 1.5 = 4.5
        assert state.net_pnl(0.55, 0.45) == 4.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_portfolio.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement domain models**

Create `polybot/domain/__init__.py`: empty file.

Create `polybot/domain/portfolio.py`:

```python
"""Domain models for portfolio tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    """Shares held in one side of a binary market."""

    side: str  # "UP" | "DOWN"
    shares: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class PortfolioState:
    """Complete portfolio snapshot."""

    cash: float
    up_position: Position = field(default_factory=lambda: Position(side="UP"))
    down_position: Position = field(default_factory=lambda: Position(side="DOWN"))
    wins: int = 0
    losses: int = 0

    def total_value(self, up_price: float, down_price: float) -> float:
        """Cash + market value of all positions."""
        return (
            self.cash
            + self.up_position.shares * up_price
            + self.down_position.shares * down_price
        )

    def unrealized_pnl(self, up_price: float, down_price: float) -> float:
        """Current value of open positions minus cost basis."""
        up_unreal = self.up_position.shares * (up_price - self.up_position.avg_entry_price)
        down_unreal = self.down_position.shares * (down_price - self.down_position.avg_entry_price)
        return up_unreal + down_unreal

    def net_pnl(self, up_price: float, down_price: float) -> float:
        """Realized + unrealized PnL."""
        realized = self.up_position.realized_pnl + self.down_position.realized_pnl
        return realized + self.unrealized_pnl(up_price, down_price)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_portfolio.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/domain/ tests/polybot/test_portfolio.py
git commit -m "feat(polybot): add Position and PortfolioState domain models"
```

---

### Task 2: PortfolioService — buy, sell, settle

**Files:**
- Create: `polybot/services/portfolio_service.py`
- Create: `tests/polybot/test_portfolio_service.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for PortfolioService."""

import pytest

from polybot.services.portfolio_service import PortfolioService


class TestBuy:
    def test_buy_up_deducts_cash(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        assert svc.state.cash == 900.0

    def test_buy_up_adds_shares(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        assert svc.state.up_position.shares == 200.0  # 100 / 0.50

    def test_buy_down(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("DOWN", amount_usd=50.0, price=0.25)
        assert svc.state.down_position.shares == 200.0  # 50 / 0.25
        assert svc.state.cash == 950.0

    def test_buy_updates_avg_entry_price(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)  # 200 shares @ 0.50
        svc.buy("UP", amount_usd=100.0, price=0.60)  # 166.67 shares @ 0.60
        # weighted avg: (200*0.50 + 166.67*0.60) / (200 + 166.67)
        expected_avg = (100.0 + 100.0) / (200.0 + 100.0 / 0.60)
        assert svc.state.up_position.avg_entry_price == pytest.approx(expected_avg, rel=1e-4)

    def test_buy_insufficient_cash_raises(self):
        svc = PortfolioService(initial_cash=100.0)
        with pytest.raises(ValueError, match="Insufficient cash"):
            svc.buy("UP", amount_usd=200.0, price=0.50)


class TestSell:
    def test_sell_credits_cash(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)  # 200 shares
        svc.sell("UP", shares=100.0, price=0.60)
        assert svc.state.cash == pytest.approx(960.0)  # 900 + 100*0.60

    def test_sell_reduces_shares(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)  # 200 shares
        svc.sell("UP", shares=50.0, price=0.60)
        assert svc.state.up_position.shares == 150.0

    def test_sell_updates_realized_pnl(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)  # 200 shares @ 0.50
        svc.sell("UP", shares=100.0, price=0.60)
        # realized = 100 * (0.60 - 0.50) = 10.0
        assert svc.state.up_position.realized_pnl == pytest.approx(10.0)

    def test_sell_insufficient_shares_raises(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)  # 200 shares
        with pytest.raises(ValueError, match="Insufficient shares"):
            svc.sell("UP", shares=300.0, price=0.60)


class TestSettle:
    def test_settle_up_wins(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)  # 200 shares
        svc.settle("UP")
        # winning: 200 shares * $1 = $200 cash back
        assert svc.state.cash == pytest.approx(1100.0)  # 900 + 200
        assert svc.state.up_position.shares == 0.0
        assert svc.state.wins == 1

    def test_settle_down_wins_up_loses(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)  # 200 UP shares
        svc.buy("DOWN", amount_usd=50.0, price=0.40)  # 125 DOWN shares
        svc.settle("DOWN")
        # UP: worthless. DOWN: 125 * $1 = $125
        assert svc.state.cash == pytest.approx(850.0 + 125.0)  # (1000-100-50) + 125
        assert svc.state.up_position.shares == 0.0
        assert svc.state.down_position.shares == 0.0
        assert svc.state.wins == 1
        assert svc.state.losses == 1

    def test_settle_no_positions_is_safe(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.settle("UP")
        assert svc.state.cash == 1000.0
        assert svc.state.wins == 0

    def test_settle_clears_avg_entry(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.settle("UP")
        assert svc.state.up_position.avg_entry_price == 0.0


class TestSessionSummary:
    def test_session_summary_fields(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.settle("UP")  # win
        summary = svc.session_summary(up_price=0.50, down_price=0.50)
        assert summary["wins"] == 1
        assert summary["losses"] == 0
        assert summary["initial_cash"] == 1000.0
        assert "final_balance" in summary
        assert "net_pnl" in summary
        assert "total_return_pct" in summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_portfolio_service.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement PortfolioService**

```python
"""Service: portfolio state management — buy, sell, settle, summary."""

from __future__ import annotations

import logging

from polybot.domain.portfolio import PortfolioState, Position


class PortfolioService:
    """Tracks cash, positions, and PnL. In-memory, resets on restart."""

    def __init__(
        self,
        initial_cash: float = 1000.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._initial_cash = initial_cash
        self._log = logger or logging.getLogger(__name__)
        self._state = PortfolioState(
            cash=initial_cash,
            up_position=Position(side="UP"),
            down_position=Position(side="DOWN"),
        )

    @property
    def state(self) -> PortfolioState:
        return self._state

    def _get_position(self, side: str) -> Position:
        if side == "UP":
            return self._state.up_position
        return self._state.down_position

    def buy(self, side: str, amount_usd: float, price: float) -> None:
        """Buy shares. Deducts cash, updates position."""
        if amount_usd > self._state.cash:
            raise ValueError(f"Insufficient cash: need ${amount_usd:.2f}, have ${self._state.cash:.2f}")

        new_shares = amount_usd / price
        pos = self._get_position(side)

        if pos.shares > 0:
            total_cost = pos.shares * pos.avg_entry_price + amount_usd
            total_shares = pos.shares + new_shares
            pos.avg_entry_price = total_cost / total_shares
        else:
            pos.avg_entry_price = price

        pos.shares += new_shares
        self._state.cash -= amount_usd

        self._log.info(
            "BUY %s: %.1f shares @ $%.4f ($%.2f) | cash=$%.2f",
            side, new_shares, price, amount_usd, self._state.cash,
        )

    def sell(self, side: str, shares: float, price: float) -> None:
        """Sell shares. Credits cash, updates realized PnL."""
        pos = self._get_position(side)
        if shares > pos.shares:
            raise ValueError(f"Insufficient shares: need {shares:.1f}, have {pos.shares:.1f}")

        proceeds = shares * price
        realized = shares * (price - pos.avg_entry_price)

        pos.shares -= shares
        pos.realized_pnl += realized
        self._state.cash += proceeds

        if pos.shares == 0.0:
            pos.avg_entry_price = 0.0

        self._log.info(
            "SELL %s: %.1f shares @ $%.4f ($%.2f) | realized=$%.2f | cash=$%.2f",
            side, shares, price, proceeds, realized, self._state.cash,
        )

    def settle(self, winning_side: str) -> None:
        """Resolve a candle. Winning shares pay $1, losing shares worth $0."""
        up = self._state.up_position
        down = self._state.down_position

        has_up = up.shares > 0
        has_down = down.shares > 0

        if not has_up and not has_down:
            return

        if has_up:
            if winning_side == "UP":
                payout = up.shares * 1.0
                up.realized_pnl += payout - (up.shares * up.avg_entry_price)
                self._state.cash += payout
                self._state.wins += 1
            else:
                up.realized_pnl -= up.shares * up.avg_entry_price
                self._state.losses += 1
            up.shares = 0.0
            up.avg_entry_price = 0.0

        if has_down:
            if winning_side == "DOWN":
                payout = down.shares * 1.0
                down.realized_pnl += payout - (down.shares * down.avg_entry_price)
                self._state.cash += payout
                self._state.wins += 1
            else:
                down.realized_pnl -= down.shares * down.avg_entry_price
                self._state.losses += 1
            down.shares = 0.0
            down.avg_entry_price = 0.0

        self._log.info(
            "SETTLE %s wins | cash=$%.2f | W=%d L=%d",
            winning_side, self._state.cash, self._state.wins, self._state.losses,
        )

    def session_summary(self, up_price: float, down_price: float) -> dict:
        """Build session summary for persistence."""
        s = self._state
        final_balance = s.total_value(up_price, down_price)
        net = s.net_pnl(up_price, down_price)
        total_bets = s.wins + s.losses
        return {
            "initial_cash": self._initial_cash,
            "final_balance": round(final_balance, 4),
            "wins": s.wins,
            "losses": s.losses,
            "win_rate": round(s.wins / total_bets, 4) if total_bets > 0 else 0.0,
            "realized_pnl": round(s.up_position.realized_pnl + s.down_position.realized_pnl, 4),
            "unrealized_pnl": round(s.unrealized_pnl(up_price, down_price), 4),
            "net_pnl": round(net, 4),
            "total_return_pct": round((final_balance - self._initial_cash) / self._initial_cash * 100, 2),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_portfolio_service.py -v`
Expected: 13 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/services/portfolio_service.py tests/polybot/test_portfolio_service.py
git commit -m "feat(polybot): add PortfolioService with buy/sell/settle"
```

---

### Task 3: SessionStore port + JsonlSessionStore adapter

**Files:**
- Create: `polybot/ports/session_store.py`
- Create: `polybot/adapters/jsonl_session_store.py`
- Create: `tests/polybot/test_jsonl_session_store.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for JsonlSessionStore."""

import json
import tempfile
from pathlib import Path

from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.ports.session_store import SessionStore


class TestJsonlSessionStore:
    def test_implements_protocol(self):
        store = JsonlSessionStore("/tmp/test.jsonl")
        assert isinstance(store, SessionStore)

    async def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.jsonl"
            store = JsonlSessionStore(str(path))
            await store.save_session({"wins": 5, "losses": 3})
            assert path.exists()

    async def test_save_appends_json_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.jsonl"
            store = JsonlSessionStore(str(path))
            await store.save_session({"wins": 5})
            await store.save_session({"wins": 10})
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2
            assert json.loads(lines[0])["wins"] == 5
            assert json.loads(lines[1])["wins"] == 10

    async def test_save_adds_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sessions.jsonl"
            store = JsonlSessionStore(str(path))
            await store.save_session({"wins": 1})
            data = json.loads(path.read_text().strip())
            assert "timestamp" in data
            assert isinstance(data["timestamp"], float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_jsonl_session_store.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement port and adapter**

Create `polybot/ports/session_store.py`:

```python
"""Port: session summary persistence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
    """Persists session summaries."""

    async def save_session(self, summary: dict) -> None: ...
```

Create `polybot/adapters/jsonl_session_store.py`:

```python
"""Adapter: append session summaries as JSON lines."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path


class JsonlSessionStore:
    """Appends one JSON line per session to a file."""

    def __init__(self, path: str, logger: logging.Logger | None = None) -> None:
        self._path = Path(path)
        self._log = logger or logging.getLogger(__name__)

    async def save_session(self, summary: dict) -> None:
        """Append session summary with timestamp."""
        entry = {**summary, "timestamp": time.time()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        self._log.info("Session saved to %s", self._path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_jsonl_session_store.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/ports/session_store.py polybot/adapters/jsonl_session_store.py tests/polybot/test_jsonl_session_store.py
git commit -m "feat(polybot): add SessionStore port + JsonlSessionStore adapter"
```

---

### Task 4: Wire into __main__.py

**Files:**
- Modify: `polybot/__main__.py`

- [ ] **Step 1: Update __main__.py**

```python
"""Bot entry point — connects to collector WS, computes indicators, re-broadcasts on 8766."""

import asyncio
import logging
import os

from polybot.adapters.collector_client import CollectorClient
from polybot.adapters.jsonl_session_store import JsonlSessionStore
from polybot.adapters.sqlite_candle_repo import SqliteCandleRepository
from polybot.services.agent_service import AgentService
from polybot.services.portfolio_service import PortfolioService
from polybot.ws import Broadcaster, PolybotServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("polybot")


async def main() -> None:
    broadcaster = Broadcaster()
    server = PolybotServer(broadcaster)
    await server.start()

    repo = SqliteCandleRepository("data/collection.db")
    await repo.init()

    agent = AgentService(candle_repo=repo)

    initial_cash = float(os.environ.get("POLYBOT_TRADING_INITIAL_CASH", "1000.0"))
    portfolio = PortfolioService(initial_cash=initial_cash)
    session_store = JsonlSessionStore("data/sessions.jsonl")

    last_up_price = 0.50
    last_down_price = 0.50

    async def on_message(msg: dict) -> None:
        nonlocal last_up_price, last_down_price
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            row = agent.on_snapshot(msg)
            if row is not None:
                if row.get("up_best_bid") is not None and row.get("up_best_ask") is not None:
                    last_up_price = (row["up_best_bid"] + row["up_best_ask"]) / 2
                if row.get("down_best_bid") is not None and row.get("down_best_ask") is not None:
                    last_down_price = (row["down_best_bid"] + row["down_best_ask"]) / 2
                log.info(
                    "📊 %s | elapsed=%.0f%% | BTC $%.2f | rsi=%s | streak=%s | cash=$%.2f",
                    row["candle_id"],
                    (row["elapsed_pct"] or 0) * 100,
                    row["btc_price"] or 0,
                    row.get("rsi"),
                    row.get("consecutive_streak"),
                    portfolio.state.cash,
                )
        elif msg_type == "candle_close":
            await agent.on_candle_close(msg)
        await broadcaster.broadcast_json(msg)

    client = CollectorClient(on_message=on_message)

    try:
        await client.run()
    finally:
        summary = portfolio.session_summary(last_up_price, last_down_price)
        log.info(
            "📋 Session: W=%d L=%d | PnL=$%.2f | Balance=$%.2f | Return=%+.1f%%",
            summary["wins"],
            summary["losses"],
            summary["net_pnl"],
            summary["final_balance"],
            summary["total_return_pct"],
        )
        await session_store.save_session(summary)
        await client.stop()
        await repo.close()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 3: Lint**

Run: `uv run ruff check .`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add polybot/__main__.py
git commit -m "feat(polybot): wire PortfolioService + session save on shutdown"
```
