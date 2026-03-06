# logging — Trade and Resolution JSONL Logging

Append-only JSONL logging for trade decisions and market resolutions.

## Modules

| File | Class/Contents | Responsibility |
|------|---------------|----------------|
| `constants.py` | `DATE_FORMAT`, `TRADE_LOG_PREFIX`, etc. | Named constants for file naming |
| `trade_log.py` | `TradeLog` | Date-rotated JSONL writer for trades and resolutions |

## How It Works

1. `TradeLog` is initialized with a `LoggingConfig` specifying the log directory
2. On each `write()` call, it checks the current UTC date and rotates the file if needed
3. Trade records go to `trades_YYYYMMDD.jsonl`, resolution records to `resolutions_YYYYMMDD.jsonl`
4. Each line is a complete JSON object (one record per line)
5. Files are flushed after every write for crash safety

## File Layout

```
logs/
  trades_20260306.jsonl      # One TradeRecord JSON per line
  trades_20260307.jsonl
  resolutions_20260306.jsonl # One ResolutionRecord JSON per line
```

## Configuration

Controlled by `LoggingConfig`:
- `log_dir` — directory for all log files (created automatically)
- `jsonl_enabled` — master switch; when `False`, all writes are no-ops
