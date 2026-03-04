# decision_engine

AI-powered trading decision engine using Claude with structured output.

## Architecture

```
┌─────────────────────────────────────────────┐
│              DecisionEngine                  │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │ screen()│→ │ decide() │→ │  Result   │  │
│  │ (Haiku) │  │ (Sonnet) │  │(Decision) │  │
│  └────┬────┘  └────┬─────┘  └───────────┘  │
│       │            │                         │
│  ┌────▼────────────▼─────┐                  │
│  │   AsyncAnthropic      │  ← injectable    │
│  │   (Claude API)        │                  │
│  └───────────────────────┘                  │
└─────────────────────────────────────────────┘
```

## Two-Stage Decision Flow

1. **Screening (Pass-1)**: Fast Haiku model checks if a trade setup exists.
   Returns `(should_trade, reason, cost)`. Filters out weak setups cheaply.

2. **Full Decision (Pass-2)**: Sonnet model makes the actual trading decision
   with structured output via tool use. Returns `(TradingDecision, latency, cost)`.

Both stages use Claude's **tool_choice** to force structured JSON responses.

## Files

| File | Role |
|------|------|
| `engine.py` | `DecisionEngine` class — orchestrates API calls, parses responses |
| `prompts.py` | System prompts and feature vector formatting functions |
| `schemas.py` | JSON schemas for Claude structured output (trading + screening) |
| `constants.py` | `HOLD_FALLBACK`, `SCREEN_MAX_TOKENS`, `SCREEN_TEMPERATURE` |
| `__init__.py` | Re-exports all public names |

## Key Design Decisions

- **Injectable AI client**: `DecisionEngine` accepts an optional `client` param (DIP).
  Tests inject a mock `AsyncAnthropic` instead of hitting the real API.
- **Injectable logger**: Accepts optional `logger` param, defaults to module logger.
- **Pure helpers**: `extract_tool_data()` and `compute_cost()` are stateless functions
  that can be tested independently.
- **Fallback on failure**: Any API error returns `HOLD_FALLBACK` (zero-confidence HOLD)
  rather than crashing the bot.

## Usage

```python
from polybot.config import AiConfig
from polybot.decision_engine import DecisionEngine

engine = DecisionEngine(config=AiConfig(api_key="sk-..."))

# Pass-1: screen
should_trade, reason, cost = await engine.screen(features)

# Pass-2: full decision
if should_trade:
    decision, latency_ms, cost = await engine.decide(features)
```

## Testing

```bash
uv run pytest tests/test_decision_engine.py -v
uv run pytest tests/test_decision_engine.py --cov=polybot.decision_engine --cov-report=term-missing
```
