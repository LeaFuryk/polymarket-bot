# Full Prompt Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Print the complete v3 spec user prompt every 30s from `__main__.py`, matching the exact format the model will receive.

**Architecture:** Add MA5/MA12/trend_score + velocity conflict + reversal regime to `technicals.py`. Track UP midpoint history in `MarketStateService`. Add cycle counter. Rewrite `format_prompt()` to output the full multi-section prompt.

**Tech Stack:** Pure Python, existing hexagonal architecture.

---

## File Map

| File | Changes |
|---|---|
| `polybot/services/technicals.py` | Add `ma_crossover()`, `trend_score()`, `velocity_conflict()`, `reversal_regime()` |
| `polybot/services/market_state.py` | Track midpoint history list, cycle counter |
| `polybot/__main__.py` | Rewrite `format_prompt()` to full spec format |
| `tests/services/test_technicals.py` | Tests for new functions |

---

### Task 1: Add MA crossover and trend score to technicals

**Files:**
- Modify: `polybot/services/technicals.py`
- Modify: `tests/services/test_technicals.py`

- [ ] **Step 1: Write failing tests**

```python
class TestMACrossover:
    def test_insufficient_data(self):
        assert ma_crossover([100.0] * 4) is None  # need 12+ closes

    def test_bullish(self):
        # Rising prices → MA5 > MA12
        closes = [100 + i * 2 for i in range(15)]
        result = ma_crossover(closes)
        assert result is not None
        assert result[0] > result[1]  # ma5 > ma12
        assert result[2] == "BULLISH"

    def test_bearish(self):
        closes = [200 - i * 2 for i in range(15)]
        result = ma_crossover(closes)
        assert result[2] == "BEARISH"


class TestTrendScore:
    def test_insufficient_data(self):
        assert trend_score([]) is None

    def test_all_up(self):
        candles = _make_candles([100 + i for i in range(13)])
        result = trend_score(candles)
        assert result is not None
        assert result > 0.3

    def test_all_down(self):
        candles = _make_candles([200 - i for i in range(13)])
        result = trend_score(candles)
        assert result < -0.3
```

- [ ] **Step 2: Run tests — FAIL**

- [ ] **Step 3: Implement**

```python
def ma_crossover(closes: Sequence[float]) -> tuple[float, float, str] | None:
    """MA5 vs MA12 crossover. Returns (ma5, ma12, 'BULLISH'|'BEARISH') or None."""
    if len(closes) < 12:
        return None
    ma5 = sum(closes[-5:]) / 5
    ma12 = sum(closes[-12:]) / 12
    signal = "BULLISH" if ma5 > ma12 else "BEARISH"
    return (ma5, ma12, signal)


def trend_score(candles: Sequence[Candle], window: int = 12) -> float | None:
    """Weighted directional score. Range [-1, 1]. Needs 12+ candles."""
    if len(candles) < window:
        return None
    recent = candles[-window:]
    up_count = sum(1 for c in recent if c.close >= c.open)
    up_ratio = up_count / len(recent)
    candle_sig = (up_ratio - 0.5) * 2  # [-1, 1]

    closes = [c.close for c in candles]
    ma5 = sum(closes[-5:]) / 5
    ma12 = sum(closes[-12:]) / 12
    price_now = closes[-1]

    ema_sig = max(-1.0, min(1.0, (ma5 - ma12) / 100))
    price_sig = max(-1.0, min(1.0, (price_now - ma12) / 150))

    score = max(-1.0, min(1.0, 0.4 * ema_sig + 0.35 * price_sig + 0.25 * candle_sig))
    return score
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

---

### Task 2: Add velocity conflict and reversal regime to technicals

**Files:**
- Modify: `polybot/services/technicals.py`
- Modify: `tests/services/test_technicals.py`

Simplified implementations that work with our current data (Chainlink ticks aggregated into candles). The legacy versions used microstructure_history which we don't have.

- [ ] **Step 1: Write failing tests**

```python
class TestVelocityConflict:
    def test_no_data(self):
        result = velocity_conflict(None, None, [])
        assert result == ("NONE", 0.0)

    def test_no_conflict_aligned(self):
        # BTC up from open, recent candles also up → aligned
        candles = _make_candles([100 + i for i in range(6)])
        result = velocity_conflict(105.0, 100.0, candles)
        assert result[0] == "NONE"

    def test_moderate_conflict(self):
        # BTC down from open, but last 3 candles recovering up
        down_then_up = [100, 99, 98, 97, 98, 99, 100]
        candles = _make_candles(down_then_up)
        result = velocity_conflict(97.0, 100.0, candles)
        # Magnitude says DOWN but recent velocity says UP
        assert result[0] in ("MODERATE", "STRONG")


class TestReversalRegime:
    def test_no_data(self):
        assert reversal_regime([]) == ("DIRECTIONAL", 0.0)

    def test_directional(self):
        # All same direction → low score
        candles = _make_candles([100 + i for i in range(10)])
        label, score = reversal_regime(candles)
        assert label == "DIRECTIONAL"
        assert score < 0.35

    def test_high_reversal(self):
        # Alternating up/down → high reversal
        candles = _make_candles([100, 102, 99, 103, 98, 104, 97, 105, 96, 106])
        label, score = reversal_regime(candles)
        assert label in ("MODERATE", "HIGH")
```

- [ ] **Step 2: Run tests — FAIL**

- [ ] **Step 3: Implement**

```python
def velocity_conflict(
    last_price: float | None,
    candle_open: float | None,
    candles: Sequence[Candle],
) -> tuple[str, float]:
    """Detect conflict between BTC magnitude direction and recent velocity.

    Returns (label, severity) where label is NONE/MODERATE/STRONG
    and severity is 0.0-1.0.
    """
    if last_price is None or candle_open is None or len(candles) < 3:
        return ("NONE", 0.0)

    magnitude = last_price - candle_open
    if abs(magnitude) < 5:
        return ("NONE", 0.0)  # flat — no conflict possible

    mag_dir = 1.0 if magnitude > 0 else -1.0

    # Recent velocity: direction of last 3 candle closes
    recent = candles[-3:]
    vel = recent[-1].close - recent[0].open
    if abs(vel) < 2:
        return ("NONE", 0.0)  # no clear velocity

    vel_dir = 1.0 if vel > 0 else -1.0

    if mag_dir == vel_dir:
        return ("NONE", 0.0)  # aligned

    # Conflict — severity based on how much velocity opposes magnitude
    severity = min(1.0, abs(vel) / abs(magnitude))
    if severity >= 0.7:
        return ("STRONG", severity)
    elif severity >= 0.4:
        return ("MODERATE", severity)
    return ("NONE", severity)


def reversal_regime(candles: Sequence[Candle]) -> tuple[str, float]:
    """Detect reversal regime from candle direction patterns.

    Returns (label, score) where label is DIRECTIONAL/MODERATE/HIGH
    and score is 0.0-1.0.
    """
    if len(candles) < 4:
        return ("DIRECTIONAL", 0.0)

    recent = candles[-12:] if len(candles) >= 12 else candles

    # Count direction changes
    directions = [1 if c.close >= c.open else -1 for c in recent]
    reversals = sum(1 for i in range(1, len(directions)) if directions[i] != directions[i - 1])
    max_reversals = len(directions) - 1
    reversal_rate = reversals / max_reversals if max_reversals > 0 else 0.0

    # Measure how much candles retrace (body vs range)
    intensities = []
    for c in recent:
        rng = c.high - c.low
        body = abs(c.close - c.open)
        if rng > 0:
            intensities.append(1.0 - body / rng)  # high intensity = small body vs range
    avg_intensity = sum(intensities) / len(intensities) if intensities else 0.0

    score = max(0.0, min(1.0, 0.5 * reversal_rate + 0.5 * avg_intensity))

    if score >= 0.6:
        return ("HIGH", score)
    elif score >= 0.35:
        return ("MODERATE", score)
    return ("DIRECTIONAL", score)
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

---

### Task 3: Track UP midpoint history and cycle counter in MarketStateService

**Files:**
- Modify: `polybot/services/market_state.py`

- [ ] **Step 1: Add state to `__init__`**

```python
self._midpoint_history: list[float] = []  # UP token midpoints this candle
self._cycle_count: int = 0
```

- [ ] **Step 2: Reset midpoint history on candle change**

In `_update_candle_open_ref`, when `new_candle`:
```python
self._midpoint_history = []
```

- [ ] **Step 3: Append midpoint in `get_state()`**

After getting snapshot, before building PromptState:
```python
mid = snapshot.up_book.midpoint
if mid is not None:
    self._midpoint_history.append(mid)

self._cycle_count += 1
```

- [ ] **Step 4: Expose via PromptState**

No model change needed — the prompt formatter reads from `MarketStateService` directly. Store as instance attributes that `format_prompt` can access.

Actually, better: pass them into `PromptState` or return them alongside. Simplest: add to `get_state()` return as a richer object. But to keep it simple, we'll access them via the service in `__main__.py`.

- [ ] **Step 5: Run tests — PASS**

- [ ] **Step 6: Commit**

---

### Task 4: Rewrite format_prompt in __main__.py

**Files:**
- Modify: `polybot/__main__.py`

- [ ] **Step 1: Rewrite `format_prompt`**

The function receives `state: PromptState` plus additional context from the service (midpoint history, cycle count, closed candles for the history table, snapshot for orderbook details).

Refactor `poll_state` to pass all needed data to the formatter:

```python
async def poll_state(service: MarketStateService) -> None:
    await asyncio.sleep(2)
    while True:
        state = await service.get_state()
        if state is not None:
            prompt = format_prompt(
                state=state,
                midpoint_history=service._midpoint_history[-10:],
                closed_candles=service._candles.closed_candles(),
                cycle=service._cycle_count,
            )
            print(prompt)
            print("---")
        else:
            print("Waiting for data...")
        await asyncio.sleep(30)
```

The `format_prompt` function builds the full multi-section prompt:

```
## PRIMARY SIGNAL
BTC move: $<diff> (<who> winning) — <label>
BTC NOW: $<price> | Candle open: $<open> | Time left: <secs>s

## Pre-computed Flags
- Velocity conflict: <label>
- Reversal regime:   <label> (score <score>) → size auto-scaled <pct>%

## Market
UP token:   ask=<> bid=<> mid=<> spread=<>% depth: $<>bid/$<>ask  R/R=<>
DOWN token: ask=<> bid=<> mid=<> spread=<>% depth: $<>bid/$<>ask  R/R=<>

Recent UP midpoints (last 10): [<values>]
Midpoint trend: <UP|DOWN> (<delta>)

## Candle History (newest last)
Last <N> candles: <up> UP / <down> DOWN

| # | Open | Close | Dir | Body% |
|---|------|-------|-----|-------|
...

MA5: $<> vs MA12: $<> → <BULLISH|BEARISH> crossover
Trend score: <score> (<label>)

## Session Context
Trend consistency: <val> (<description>)
Range position:    <val> (<description>)
YES ob imbalance:  <val> (<description>)
NO ob imbalance:   <val> (<description>)
Vol timing:        <val> (<description>)

## Positions
UP: 0 shares | DOWN: 0 shares

## Portfolio
Cash: $0.00 | PnL: $0.00 | Trades: 0 | Fees: $0.00 | Drawdown: $0.00

## Cycle #<N>
```

- [ ] **Step 2: Implement the full formatter**

Full code provided — builds each section, handles None/n/a, formats numbers consistently.

- [ ] **Step 3: Run smoke test**

Run: `uv run python -m polybot`
Expected: Full multi-section prompt printed every 30s with live data.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`

- [ ] **Step 5: Commit**

---

### Task 5: Codex review

- [ ] **Step 1:** Run `/codex:rescue --model gpt-5.4` on all changed files
- [ ] **Step 2:** Fix any issues found
- [ ] **Step 3:** `uv run pytest tests/ -v` — ALL PASS
