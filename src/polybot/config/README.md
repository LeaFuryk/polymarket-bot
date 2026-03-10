# config — Application Configuration

## Overview

The `config` package provides Pydantic-based configuration for the Polymarket bot.
Configuration is loaded in layers with clear precedence:

1. **Model defaults** — named constants in `constants.py`
2. **YAML file** — `config/default.yaml` (or custom path)
3. **Environment variables** — `POLYBOT_*` prefix (highest precedence)

## Architecture

```
config/
├── __init__.py        — Public API re-exports
├── constants.py       — All default values as named constants
├── market.py          — MarketConfig
├── api.py             — ApiConfig (external service URLs)
├── agent.py           — AgentConfig (polling, confidence thresholds)
├── ai.py              — AiConfig (model selection, cost tracking)
├── simulator.py       — SimulatorConfig (paper trading parameters)
├── risk.py            — RiskConfig (position sizing, safety limits)
├── monitor.py         — MonitorConfig (intervals, adaptive toggles)
├── logging_config.py  — LoggingConfig (log output, storage)
├── trading.py         — TradingConfig (live trading credentials)
├── app.py             — AppConfig (root, composes all sections)
└── loader.py          — ConfigLoader + load_config()
```

## Usage

```python
from polybot.config import load_config

config = load_config()                        # default: config/default.yaml
config = load_config("config/production.yaml") # custom YAML path
```

For testing, use `ConfigLoader` directly with a temporary YAML file
or construct config models directly:

```python
from polybot.config import AppConfig, AgentConfig

test_config = AppConfig(agent=AgentConfig(min_confidence=0.8))
```

## Environment Variables

All overrides use the `POLYBOT_` prefix:

| Variable | Section | Field | Type |
|---|---|---|---|
| `POLYBOT_MARKET_SERIES_SLUG` | market | series_slug | str |
| `POLYBOT_AI_API_KEY` | ai | api_key | str |
| `POLYBOT_AI_MODEL` | ai | model | str |
| `POLYBOT_AGENT_DECISION_INTERVAL` | agent | decision_interval | int |
| `POLYBOT_AGENT_INITIAL_CASH` | agent | initial_cash | float |
| `POLYBOT_AGENT_MAX_CYCLES` | agent | max_cycles | int |
| `POLYBOT_AGENT_MIN_CONFIDENCE` | agent | min_confidence | float |
| `POLYBOT_RISK_DAILY_LOSS_LIMIT_PCT` | risk | daily_loss_limit_pct | float |
| `POLYBOT_KNOWLEDGE_DIR` | logging | knowledge_dir | str |
| `POLYBOT_ETHEREUM_RPC_URL` | api | ethereum_rpc_url | str |
| `POLYBOT_TRADING_MODE` | trading | mode | str |
| `POLYBOT_TRADING_PRIVATE_KEY` | trading | private_key | str |
| `POLYBOT_TRADING_API_KEY` | trading | api_key | str |
| `POLYBOT_TRADING_API_SECRET` | trading | api_secret | str |
| `POLYBOT_TRADING_API_PASSPHRASE` | trading | api_passphrase | str |
| `POLYBOT_TRADING_DRY_RUN` | trading | dry_run | bool |
| `POLYBOT_TRADING_PROXY_WALLET_ADDRESS` | trading | proxy_wallet_address | str |
| `POLYBOT_TRADING_MAX_ORDER_SIZE_USD` | trading | max_order_size_usd | float |
| `POLYBOT_TRADING_MAX_SESSION_LOSS_USD` | trading | max_session_loss_usd | float |

## Validation

Pydantic validates types automatically. Additional business rules:

- `AgentConfig.min_confidence` — must be in `[0.0, 1.0]`
- `RiskConfig.max_position_pct` — must be in `[0.0, 1.0]`
- `RiskConfig.max_concentration_pct` — must be in `[0.0, 1.0]`
- `RiskConfig.daily_loss_limit_pct` — must be in `[0.0, 1.0]`

Invalid values raise `pydantic.ValidationError` with a clear message.
