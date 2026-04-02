# Microstructure Spec Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the microstructure section of PromptState with the updated spec — fix 4 existing fields, add 3 new fields, fix volume freshness.

**Architecture:** Changes span domain models (add fields), OrderBook (fix imbalance), adapter (fetch both last trade prices + fresh volume), and service (wire new fields + fix delta references).

**Tech Stack:** Pure Python, existing hexagonal architecture.

---

## File Map

| File | Changes |
|---|---|
| `polybot/domain/models.py` | Add `bid_volume`/`ask_volume` to OrderBook, add 3 fields to Microstructure, add `down_last_trade_price`+`volume` to MarketSnapshot |
| `polybot/adapters/polymarket.py` | Fetch DOWN last trade price + fresh volume in `get_snapshot()` |
| `polybot/services/market_state.py` | Wire new fields, use `last_trade_price` for yes_price, add no_price/spread/no_delta |
| `tests/domain/test_orderbook.py` | Test new volume-based imbalance |
| `tests/adapters/test_polymarket.py` | Test expanded snapshot |
| `tests/services/test_market_state.py` | Test new microstructure fields |

---

### Task 1: Fix OrderBook.imbalance to use raw volume

**Files:**
- Modify: `polybot/domain/models.py:125-137`
- Modify: `tests/domain/test_orderbook.py`

- [ ] **Step 1: Write failing test**

```python
# In tests/domain/test_orderbook.py, add:

def test_imbalance_uses_raw_volume(self):
    """Imbalance uses raw size, not price-weighted depth."""
    book = OrderBook(
        bids=(OrderBookLevel(0.01, 1000),),  # depth=10, volume=1000
        asks=(OrderBookLevel(0.99, 1000),),  # depth=990, volume=1000
        timestamp=0.0,
    )
    # Raw volume: (1000-1000)/(1000+1000) = 0.0
    # Depth-weighted would be: (10-990)/(10+990) = -0.98
    assert book.imbalance == pytest.approx(0.0)
```

- [ ] **Step 2: Run test — should FAIL** (current uses depth-weighted)

Run: `uv run pytest tests/domain/test_orderbook.py::TestOrderBook::test_imbalance_uses_raw_volume -v`

- [ ] **Step 3: Add `bid_volume`/`ask_volume` properties, fix `imbalance`**

In `polybot/domain/models.py`, in class `OrderBook`:

```python
@property
def bid_volume(self) -> float:
    return sum(level.size for level in self.bids)

@property
def ask_volume(self) -> float:
    return sum(level.size for level in self.asks)

@property
def imbalance(self) -> float:
    """(bid_vol - ask_vol) / (bid_vol + ask_vol). Range [-1, 1]."""
    total = self.bid_volume + self.ask_volume
    if total == 0:
        return 0.0
    return (self.bid_volume - self.ask_volume) / total
```

Keep `bid_depth` and `ask_depth` — they're still used elsewhere.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`

- [ ] **Step 5: Commit**

---

### Task 2: Expand MarketSnapshot with down_last_trade_price and volume

**Files:**
- Modify: `polybot/domain/models.py:158-163`
- Modify: `polybot/adapters/polymarket.py:87-98`
- Modify: `tests/adapters/test_polymarket.py`

- [ ] **Step 1: Add fields to MarketSnapshot**

```python
@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    up_book: OrderBook
    down_book: OrderBook
    last_trade_price: float | None       # UP token last trade
    down_last_trade_price: float | None  # DOWN token last trade
    volume: float                        # fresh cumulative volume from Gamma
```

- [ ] **Step 2: Update PolymarketAdapter.get_snapshot()**

Fetch both UP and DOWN last trade prices + fresh volume in parallel:

```python
async def get_snapshot(self, market: Market) -> MarketSnapshot:
    """Fetch complete market state."""
    (up_book, down_book), up_price, down_price, volume = await asyncio.gather(
        self.get_orderbooks(market),
        self.get_last_trade_price(market.up_token_id),
        self.get_last_trade_price(market.down_token_id),
        self.get_market_volume(market.slug),
    )
    return MarketSnapshot(
        market=market,
        up_book=up_book,
        down_book=down_book,
        last_trade_price=up_price,
        down_last_trade_price=down_price,
        volume=volume,
    )
```

- [ ] **Step 3: Add `get_market_volume` to PolymarketAdapter**

```python
async def get_market_volume(self, slug: str) -> float:
    """Fetch fresh cumulative volume from Gamma API."""
    try:
        resp = await self._gamma_client.get("/events", params={"slug": slug})
        resp.raise_for_status()
        events = resp.json()
        if not events:
            return 0.0
        mkt = events[0].get("markets", [{}])[0]
        return float(mkt.get("volumeClob", mkt.get("volume", 0)))
    except Exception:
        self._log.exception("Failed to fetch volume for %s", slug)
        return 0.0
```

- [ ] **Step 4: Fix test_get_snapshot**

Update `_make_snapshot` helper and test assertions to include new fields.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v`

- [ ] **Step 6: Commit**

---

### Task 3: Add new Microstructure fields to domain model

**Files:**
- Modify: `polybot/domain/models.py:206-212`

- [ ] **Step 1: Update Microstructure dataclass**

```python
@dataclass(frozen=True)
class Microstructure:
    spread_bps: float
    ob_imbalance: float
    polymarket_yes_price: float | None
    polymarket_no_price: float | None
    polymarket_spread: float | None
    polymarket_yes_delta: float | None
    polymarket_no_delta: float | None
    polymarket_vol_delta: float | None
```

- [ ] **Step 2: Run tests — fix all places that construct Microstructure**

Run: `uv run pytest tests/ -v` — fix any failures from missing fields.

- [ ] **Step 3: Commit**

---

### Task 4: Wire everything in MarketStateService

**Files:**
- Modify: `polybot/services/market_state.py:50-53, 98-115, 180-200`
- Modify: `tests/services/test_market_state.py`

- [ ] **Step 1: Update `_update_candle_open_ref` to track both prices**

```python
self._ref_candle_start: float = 0.0
self._ref_yes_price: float | None = None
self._ref_no_price: float | None = None
self._ref_volume: float | None = None
```

```python
def _update_candle_open_ref(
    self, candle_start: float, snapshot: MarketSnapshot, market: Market
) -> None:
    if candle_start != self._ref_candle_start:
        self._ref_yes_price = None
        self._ref_no_price = None
        self._ref_volume = None

        if snapshot.last_trade_price is None:
            return
        self._ref_candle_start = candle_start
        self._ref_yes_price = snapshot.last_trade_price
        self._ref_no_price = snapshot.down_last_trade_price
        self._ref_volume = snapshot.volume
```

- [ ] **Step 2: Rewrite `_build_microstructure`**

```python
def _build_microstructure(self, tick: BtcTick, snapshot: MarketSnapshot) -> Microstructure:
    mid = tick.price
    spread_bps = (tick.ask - tick.bid) / mid * 10_000 if mid > 0 else 0.0

    yes_price = snapshot.last_trade_price
    no_price = snapshot.down_last_trade_price

    # Polymarket spread: 1 - yes - no (liquidity proxy)
    poly_spread = None
    if yes_price is not None and no_price is not None:
        poly_spread = 1.0 - yes_price - no_price

    # Deltas vs candle-open reference
    yes_delta = None
    if yes_price is not None and self._ref_yes_price is not None:
        yes_delta = yes_price - self._ref_yes_price

    no_delta = None
    if no_price is not None and self._ref_no_price is not None:
        no_delta = no_price - self._ref_no_price

    vol_delta = None
    if self._ref_volume is not None:
        vol_delta = snapshot.volume - self._ref_volume

    return Microstructure(
        spread_bps=spread_bps,
        ob_imbalance=snapshot.up_book.imbalance,
        polymarket_yes_price=yes_price,
        polymarket_no_price=no_price,
        polymarket_spread=poly_spread,
        polymarket_yes_delta=yes_delta,
        polymarket_no_delta=no_delta,
        polymarket_vol_delta=vol_delta,
    )
```

- [ ] **Step 3: Update get_state() call** — remove `market` param since snapshot now has volume:

```python
self._update_candle_open_ref(candle_start, snapshot, market)
...
microstructure=self._build_microstructure(tick, snapshot),
```

- [ ] **Step 4: Write tests**

```python
async def test_microstructure_uses_last_trade_price(self):
    service = _make_service(tick=_make_tick(), partial=_make_partial())
    state = await service.get_state()
    # yes_price should be last_trade_price (0.56), not midpoint (0.50)
    assert state.microstructure.polymarket_yes_price == pytest.approx(0.56)

async def test_microstructure_no_price(self):
    service = _make_service(tick=_make_tick(), partial=_make_partial())
    state = await service.get_state()
    assert state.microstructure.polymarket_no_price is not None

async def test_microstructure_spread(self):
    service = _make_service(tick=_make_tick(), partial=_make_partial())
    state = await service.get_state()
    # spread = 1 - yes - no
    yes = state.microstructure.polymarket_yes_price
    no = state.microstructure.polymarket_no_price
    assert state.microstructure.polymarket_spread == pytest.approx(1.0 - yes - no)

async def test_no_delta_computed(self):
    service = _make_service(tick=_make_tick(), partial=_make_partial())
    state = await service.get_state()
    assert state.microstructure.polymarket_no_delta == pytest.approx(0.0)
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v`

- [ ] **Step 6: Commit**

---

### Task 5: Codex review

- [ ] **Step 1: Run Codex review**

Run: `/codex:rescue --model gpt-5.4` on all changed files

- [ ] **Step 2: Fix any issues**

- [ ] **Step 3: Final test run**

Run: `uv run pytest tests/ -v`
