# Plan: Chainlink Data Streams Integration (HMAC-Authenticated)

## Context

The current Chainlink WS connects to Polymarket's unauthenticated RTDS relay (`wss://ws-live-data.polymarket.com`) which is extremely unreliable — 80+ disconnects, HTTP 429 rate limits per session. It was demoted to cross-reference only, meaning BTC prices come from Binance while Polymarket resolves candles via Chainlink. This mismatch caused 23% winner prediction errors.

With official HMAC credentials for the Chainlink Data Streams API, we get the exact resolution price feed directly — reliable, authenticated, sub-second updates. This eliminates the price source mismatch entirely.

## Security Decision: No SDK

The `py-chainlink-streams` SDK was audited and rejected:
- AI-generated (Cursor), 1 maintainer, 2 GitHub stars, 422 downloads/month
- No CI/CD, no security policy, no human code review
- Too risky for production trading bot

Instead: implement HMAC auth ourselves (~20 lines of stdlib) and use the SDK only as reference for the report decoding format.

## Technical Details

- **WebSocket endpoint:** `wss://ws.dataengine.chain.link/api/v1/ws?feedIDs={feed_id}`
- **BTC/USD Feed ID:** `0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8`
- **Auth headers:**
  - `Authorization: {hmac_user_id}`
  - `X-Authorization-Timestamp: {timestamp_ms}`
  - `X-Authorization-Signature-SHA256: {hmac_signature}`
- **String-to-sign:** `"GET {path} {sha256('').hexdigest()} {user_id} {timestamp_ms}"`
- **Signature:** HMAC-SHA256 of string-to-sign using HMAC Secret, hex-encoded
- **Report schema v3:** `benchmarkPrice`, `bid`, `ask` (int192, 18-decimal fixed-point)

## Changes (7 files)

### 1. `src/polybot/config.py` — Add credential fields
- Add to `ApiConfig`: `chainlink_ds_ws_url`, `chainlink_ds_user`, `chainlink_ds_secret`, `chainlink_ds_feed_id`
- Credentials default empty (graceful degradation — no creds = Binance primary as today)
- Add `POLYBOT_CHAINLINK_DS_USER` and `POLYBOT_CHAINLINK_DS_SECRET` env var overrides in `_apply_env_overrides()`
- Feed ID defaults to BTC/USD: `0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8`

### 2. `src/polybot/market_data/chainlink_ws.py` — Rewrite (core work)
- **HMAC auth function** (`_generate_hmac_headers`): ~20 lines using `hmac`, `hashlib` from stdlib
  - String-to-sign: `"GET {path} {sha256_empty_body} {user_id} {timestamp_ms}"`
  - Headers: `Authorization`, `X-Authorization-Timestamp`, `X-Authorization-Signature-SHA256`
- **Report v3 decoder** (`_decode_report_v3`): ~30 lines, manual ABI hex parsing with `int.from_bytes()`
  - Reads offset to report body, parses 9 x 32-byte fields
  - Extracts `benchmarkPrice`, `bid`, `ask` (int192, 18-decimal fixed-point -> float)
  - No `eth-abi` dependency needed
- **Dual-mode constructor**: accepts `ds_user`, `ds_secret`, `ds_feed_id` kwargs
  - If credentials provided -> authenticated mode (official `wss://ws.dataengine.chain.link`)
  - If empty -> legacy RTDS relay (existing behavior, for backward compat)
- **`_connect_authenticated()`**: connects with HMAC headers via `websockets.connect(additional_headers=...)`
- **`_connect_rtds_legacy()`**: existing RTDS code moved here
- **Same interface**: `price`, `is_active`, `completed_candles`, `start()`, `stop()` unchanged
- Increase `_STALE_THRESHOLD` to 60s for authenticated mode (more reliable feed)
- `websockets` handles keepalive pings via `ping_interval` param (remove manual ping loop for auth mode)
- Sanity check decoded prices: reject if not in range 10,000-200,000

### 3. `src/polybot/agent.py` — Pass credentials to constructor
- Update `ChainlinkWSFeed(...)` call to pass `ds_ws_url`, `ds_user`, `ds_secret`, `ds_feed_id` from config
- Add startup log indicating authenticated vs legacy mode

### 4. `src/polybot/market_data/btc_price.py` — Re-promote Chainlink as primary
- In `get_price()`: if `chainlink_ws.is_active` AND `chainlink_ws._authenticated` -> use Chainlink price as primary, Binance as cross-reference
- If Chainlink not available -> Binance primary (current behavior)
- New source string: `"chainlink_ds"` (distinct from old `"chainlink_ws"`)

### 5. `src/polybot/indicators.py` — Update divergence indicator
- When `price_source == "chainlink_ds"`: label as informational ("Chainlink DS primary, gap is Binance noise")
- When `price_source == "binance"`: label as resolution risk (current behavior)

### 6. `src/polybot/models.py` — Update docstrings
- `BtcPrice.price_source`: add `"chainlink_ds"` to allowed values comment
- `BtcCandle.source`: add `"chainlink_ds"`

### 7. `.env.example` — Add credential placeholders
```
# Chainlink Data Streams (official HMAC credentials)
# POLYBOT_CHAINLINK_DS_USER=your-hmac-user-id
# POLYBOT_CHAINLINK_DS_SECRET=your-hmac-secret
```

### 8. `CHANGELOG.md` + `README.md` — Document changes

## Graceful Degradation

- **No credentials** -> bot works exactly as today (Binance primary, no Chainlink WS)
- **Credentials set but feed disconnects** -> `is_active` returns false, falls back to Binance automatically
- **Credentials wrong (401/403)** -> logged as error, reconnect loop backs off, Binance takes over

## Verification

1. Start bot with empty `POLYBOT_CHAINLINK_DS_USER` -> confirm Binance primary, no errors
2. Set credentials -> confirm log shows "authenticated mode", price ticks arrive
3. Check `price_source` in dashboard JSON shows `"chainlink_ds"`
4. Verify divergence indicator shows "[Chainlink DS primary]"
5. Monitor for 30+ minutes: no disconnects, consistent candle building

## References

- [Chainlink Data Streams Docs](https://docs.chain.link/data-streams)
- [Data Streams Authentication](https://docs.chain.link/data-streams/reference/data-streams-api/authentication)
- [WebSocket API Reference](https://docs.chain.link/data-streams/reference/data-streams-api/interface-ws)
- [BTC/USD Stream Info](https://data.chain.link/streams/btc-usd-cexprice-streams)
- [py-chainlink-streams (reference only, not used)](https://github.com/smolquants/py-chainlink-streams)
