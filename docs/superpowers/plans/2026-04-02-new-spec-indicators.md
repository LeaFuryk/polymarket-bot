# New Spec Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 new indicators (`yes_ob`, `no_ob`, `trend_consistency`, `range_position`, `vol_timing`) and remove 2 obsolete fields (`ob_imbalance`, `polymarket_spread`) to align with the v2 spec.

**Architecture:** `trend_consistency` and `range_position` are stateless functions in `technicals.py`. `yes_ob`/`no_ob` are trivial wiring from existing OrderBook. `vol_timing` is stateful tracking in `MarketStateService`. Microstructure dataclass updated to match new prompt format.

**Tech Stack:** Pure Python, existing hexagonal architecture.

---

## File Map

| File | Changes |
|---|---|
| `polybot/services/technicals.py` | Add `trend_consistency()`, `range_position()` |
| `polybot/domain/models.py` | Update `Microstructure` (remove 2, add 3), update `Technicals` (add 2) |
| `polybot/services/market_state.py` | Wire new fields, add `vol_timing` tracking |
| `tests/services/test_technicals.py` | Tests for new indicators |
| `tests/services/test_market_state.py` | Tests for new microstructure + vol_timing |

---

### Task 1: Add trend_consistency and range_position to technicals

**Files:**
- Modify: `polybot/services/technicals.py`
- Modify: `tests/services/test_technicals.py`

- [ ] **Step 1: Write failing tests**

```python
# In tests/services/test_technicals.py

class TestTrendConsistency:
    def test_insufficient_data(self):
        assert trend_consistency([]) is None
        assert trend_consistency([100.0]) is None  # need log_ret which needs 2+ candles

    def test_all_up(self):
        # 11 rising closes → 10 positive log_rets → mean(signs) = 1.0
        closes = [100 + i for i in range(11)]
        result = trend_consistency(closes)
        assert result == pytest.approx(1.0)

    def test_all_down(self):
        closes = [200 - i for i in range(11)]
        result = trend_consistency(closes)
        assert result == pytest.approx(-1.0)

    def test_choppy(self):
        # Alternating up/down → mean ≈ 0
        closes = [100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100]
        result = trend_consistency(closes)
        assert result == pytest.approx(0.0, abs=0.01)

    def test_uses_last_10(self):
        # 20 closes, but only last 10 log_rets matter
        closes = [100 - i for i in range(10)] + [90 + i for i in range(11)]
        result = trend_consistency(closes)
        assert result == pytest.approx(1.0)


class TestRangePosition:
    def test_insufficient_data(self):
        assert range_position([], 67000.0) is None

    def test_at_high(self):
        candles = _make_candles(CLOSES[:40])
        high = max(c.high for c in candles)
        result = range_position(candles, high)
        assert result == pytest.approx(1.0)

    def test_at_low(self):
        candles = _make_candles(CLOSES[:40])
        low = min(c.low for c in candles)
        result = range_position(candles, low)
        assert result == pytest.approx(0.0)

    def test_mid_range(self):
        candles = _make_candles(CLOSES[:40])
        high = max(c.high for c in candles)
        low = min(c.low for c in candles)
        mid = (high + low) / 2
        result = range_position(candles, mid)
        assert result == pytest.approx(0.5, abs=0.05)
```

- [ ] **Step 2: Run tests — should FAIL**

Run: `uv run pytest tests/services/test_technicals.py -v -k "TrendConsistency or RangePosition"`

- [ ] **Step 3: Implement**

In `polybot/services/technicals.py`:

```python
import math

def trend_consistency(closes: Sequence[float], window: int = 10) -> float | None:
    """mean(sign(log_ret)) over last `window` candles. Range [-1, 1]."""
    if len(closes) < window + 1:
        return None
    recent = closes[-(window + 1):]
    signs = []
    for i in range(1, len(recent)):
        if recent[i - 1] <= 0:
            continue
        lr = math.log(recent[i] / recent[i - 1])
        signs.append(1.0 if lr > 0 else -1.0 if lr < 0 else 0.0)
    if not signs:
        return None
    return sum(signs) / len(signs)


def range_position(candles: Sequence[Candle], last_price: float, window: int = 40) -> float | None:
    """(last_price - session_low) / (session_high - session_low) over last `window` candles."""
    if not candles:
        return None
    recent = candles[-window:]
    session_high = max(c.high for c in recent)
    session_low = min(c.low for c in recent)
    rng = session_high - session_low
    if rng == 0:
        return 0.5
    return (last_price - session_low) / rng
```

- [ ] **Step 4: Run tests — should PASS**

Run: `uv run pytest tests/services/test_technicals.py -v`

- [ ] **Step 5: Commit**

---

### Task 2: Update domain models (Microstructure + Technicals)

**Files:**
- Modify: `polybot/domain/models.py`

- [ ] **Step 1: Update Microstructure**

Remove `ob_imbalance` and `polymarket_spread`. Add `yes_ob`, `no_ob`, `vol_timing`:

```python
@dataclass(frozen=True)
class Microstructure:
    spread_bps: float
    polymarket_yes_price: float | None
    polymarket_no_price: float | None
    yes_ob: float              # YES token orderbook imbalance
    no_ob: float               # NO token orderbook imbalance
    polymarket_yes_delta: float | None
    polymarket_no_delta: float | None
    polymarket_vol_delta: float | None
    vol_timing: float | None   # elapsed_pct at largest vol spike
```

- [ ] **Step 2: Update Technicals**

Add `trend_consistency` and `range_position`:

```python
@dataclass(frozen=True)
class Technicals:
    rsi14: float | None
    macd_hist: float | None
    bb_pct_b: float | None
    atr14_norm: float | None
    trend_consistency: float | None
    range_position: float | None
```

- [ ] **Step 3: Run tests — fix all construction sites**

Run: `uv run pytest tests/ -v` — fix every `Microstructure(...)` and `Technicals(...)` that breaks.

- [ ] **Step 4: Commit**

---

### Task 3: Wire new fields in MarketStateService

**Files:**
- Modify: `polybot/services/market_state.py`
- Modify: `tests/services/test_market_state.py`

- [ ] **Step 1: Add vol_timing tracking state**

In `__init__`:
```python
self._max_vol_spike: float = 0.0       # largest vol change observed this candle
self._vol_timing: float | None = None  # elapsed_pct when it happened
self._prev_volume: float | None = None # previous snapshot volume for spike detection
```

- [ ] **Step 2: Add vol spike tracking logic**

In `get_state()`, after fetching volume, before building PromptState:

```python
# Track vol_timing — elapsed_pct at largest aggregate vol spike
if self._prev_volume is not None and partial_snapshot:
    spike = abs(snapshot.volume - self._prev_volume)
    if spike > self._max_vol_spike:
        self._max_vol_spike = spike
        elapsed = (now - partial_snapshot.start_time) / CANDLE_INTERVAL
        self._vol_timing = max(0.0, min(elapsed, 1.0))
self._prev_volume = snapshot.volume
```

Reset on candle change in `_update_candle_open_ref`:
```python
if new_candle:
    self._max_vol_spike = 0.0
    self._vol_timing = None
    self._prev_volume = None
```

- [ ] **Step 3: Update _build_technicals**

```python
def _build_technicals(self, closed, tick):
    closes = [c.close for c in closed]
    return Technicals(
        rsi14=rsi(closes),
        macd_hist=macd_histogram(closes),
        bb_pct_b=bollinger_pct_b(closes),
        atr14_norm=atr_normalized(closed),
        trend_consistency=trend_consistency(closes),
        range_position=range_position(closed, tick.price),
    )
```

- [ ] **Step 4: Update _build_microstructure**

```python
def _build_microstructure(self, tick, snapshot):
    mid = tick.price
    spread_bps = (tick.ask - tick.bid) / mid * 10_000 if mid > 0 else 0.0

    yes_price = snapshot.last_trade_price
    no_price = snapshot.down_last_trade_price

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
        polymarket_yes_price=yes_price,
        polymarket_no_price=no_price,
        yes_ob=snapshot.up_book.imbalance,
        no_ob=snapshot.down_book.imbalance,
        polymarket_yes_delta=yes_delta,
        polymarket_no_delta=no_delta,
        polymarket_vol_delta=vol_delta,
        vol_timing=self._vol_timing,
    )
```

- [ ] **Step 5: Write tests**

```python
async def test_yes_ob_from_orderbook(self):
    service = _make_service(tick=_make_tick(), partial=_make_partial())
    state = await service.get_state()
    assert -1.0 <= state.microstructure.yes_ob <= 1.0

async def test_no_ob_from_orderbook(self):
    service = _make_service(tick=_make_tick(), partial=_make_partial())
    state = await service.get_state()
    assert -1.0 <= state.microstructure.no_ob <= 1.0

async def test_technicals_has_trend_consistency(self):
    service = _make_service(tick=_make_tick())
    state = await service.get_state()
    # No candle history → None
    assert state.technicals.trend_consistency is None

async def test_technicals_has_range_position(self):
    service = _make_service(tick=_make_tick())
    state = await service.get_state()
    assert state.technicals.range_position is None

async def test_vol_timing_none_initially(self):
    service = _make_service(tick=_make_tick(), partial=_make_partial())
    state = await service.get_state()
    assert state.microstructure.vol_timing is None
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/ -v`

- [ ] **Step 7: Commit**

---

### Task 4: Codex review

- [ ] **Step 1:** Run `/codex:rescue --model gpt-5.4` on all changed files
- [ ] **Step 2:** Fix any issues found
- [ ] **Step 3:** `uv run pytest tests/ -v` — ALL PASS
