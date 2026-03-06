# execution/

Live and simulated order execution on the Polymarket CLOB.

## Execution Pipeline

```
TradingDecision + OrderbookSnapshot
        │
        ▼
   Safety Checks
   ├─ Kill switch (cumulative session loss)
   ├─ Token ID present
   ├─ Orderbook has bid/ask
   ├─ Max order size cap
   └─ Min wallet balance (BUY only, live mode)
        │
        ▼
  ┌─────┴──────┐
  │  dry_run?  │
  └─────┬──────┘
   yes  │  no
   ▼    ▼
Simulate   Submit GTC Limit Order
(poll OB)  (sign → post → poll status)
   │            │
   ▼            ▼
Fill or     3-Layer Fill Detection
Timeout     ├─ API status poll (MATCHED/FILLED)
            ├─ size_matched > 0
            └─ Stealth balance check (on-chain delta)
```

## 3-Layer Fill Detection

The CLOB REST API has an async status propagation delay — an order can be
matched by the matching engine while `get_order` still reports status
"LIVE" for 1-3 seconds. To avoid missing real fills:

1. **Status poll** — check `status` field for MATCHED/FILLED during TTL window
2. **size_matched** — check `size_matched > 0` even when status is still LIVE
3. **Stealth balance** — after timeout + cancel, compare pre/post on-chain
   conditional token balance to detect fills the API never reported

## Dry Run Mode

When `TradingConfig.dry_run` is enabled, orders are simulated by polling the
live orderbook. If the market crosses the limit price within the TTL window,
a fill is synthesised at the limit price with standard taker fees.

## Kill Switch

Activated when cumulative session PnL drops below `-max_session_loss_usd`.
Once active, all execution is blocked until the session restarts.

## Module Files

| File | Description |
|------|-------------|
| `live.py` | `LiveExecutionEngine` — async orchestrator, CLOB client interaction |
| `helpers.py` | Pure functions: `snapshot_ob`, `extract_order_fill_info`, `make_fill_from_balance`, `parse_order_response` |
| `constants.py` | All magic numbers: signature type, fees, polling intervals, tolerances |
| `__init__.py` | Re-exports for `from polybot.execution import ...` |
