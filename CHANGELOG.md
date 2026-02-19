# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Confidence calibration tracker** (`calibration.py`) — Tracks every trade's stated confidence vs actual outcome. Builds a calibration curve from historical data, persisted to `calibration_data.jsonl`. Gates trades when calibrated win rate falls below break-even threshold (55%). Feeds calibration summary back to AI in the prompt so Claude can see how its confidence maps to reality.
- **Rules-based pre-filter** (`prefilter.py`) — Cheap, fast checks run before calling Claude to skip obvious HOLD cycles. Checks time remaining (<90s), spread width, book depth, choppy market detection (BTC range <$50/30min), and entry pricing. Bypasses AI for open positions (exit decisions still need Claude). Tracks skip rate and displays stats on both Rich terminal and web dashboards. Expected to save 60-70% of AI API costs.
- **Pending bet resolution on startup** — When the bot restarts after a crash or stop mid-candle, it now automatically detects unresolved trades (fills with no matching resolution record), fetches historical BTC prices from Binance, verifies the winner via Polymarket token prices, computes PnL from logged fills, and writes the missing resolution records. This ensures all-time stats and dashboard history remain accurate across restarts.
- `MarketDiscovery.fetch_market_by_slug()` — Public method to fetch a specific candle market by its exact slug, used by the pending bet resolver to look up past markets on the Gamma API.
- `_compute_pnl_from_trades()` helper — Reconstructs position PnL from logged BUY/SELL fills for settlement (winning token = $1, losing = $0).

### Fixed
- **Dashboard Cash/Portfolio metrics now scoped per session** — When viewing a specific session or day, the Cash and Portfolio cards now show that session's start→current values instead of always referencing the global `initial_cash`. Overview still shows the all-time view.
- **Added AI Cost and Fees metric cards to dashboard** — Two new cards show the total Claude API cost and trading fees for the selected view, making it clear why a session with positive PnL can still lose portfolio value. AI cost is now logged per-trade in `TradeRecord.ai_cost` so historical sessions can compute it too.
- **Added Open Trade PnL metric to dashboard** — Shows realized P&L from buy/sell round-trips on the current (unresolved) candle. This value is already reflected in cash but not yet in resolution PnL, explaining the accounting gap between `initial_cash + resolution_pnl - fees - ai_cost` and actual cash.
- **Fixed stale BTC candle in history** — `load_candle_history()` now drops the last candle from Binance's response (always an incomplete in-progress candle with wrong close/high/low). `append_latest_candle()` now replaces the last candle when the `open_time` matches instead of skipping it. This fixes the AI seeing phantom wrong-direction candles that persisted from startup.
- **Added candle completeness safeguards** — Three layers of defense against stale candle data: (1) `candles` property now filters out any candle with `close_time` in the future, so incomplete candles can never reach the AI. (2) Periodic full candle history refresh every 10 minutes corrects any accumulated drift. (3) Initial load strips the in-progress candle.
- **Reset knowledge files** — Cleared session-specific analysis from `trading_patterns.md`, `self_assessment.md`, and `session_history.md` since previous sessions' pattern analysis was built on incorrect candle direction data. Retained proven strategy framework (entry/exit discipline, regime detection, confidence calibration).
