# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **`config`** — Converted from single `config.py` module to a package (`config/`) with each config class in its own file; extracted all hardcoded defaults into `constants.py`; added `ConfigLoader` class; added field validators for `min_confidence` and risk percentage fields

### Added
- **`tests/test_config.py`** — 17 unit tests covering constants, model validation, YAML loading, env overrides, and backward compatibility
- **`src/polybot/config/README.md`** — Module README documenting package architecture, env variables, validation rules, and usage
- **`CLAUDE.md`** — Project-level configuration for Claude Code with Notion IDs, active skills, and repo conventions
- **`.github/PULL_REQUEST_TEMPLATE.md`** — PR template with delivery checklist enforcing SOLID principles, >80% test coverage, CI checks, documentation, and CHANGELOG updates
- **Keep a Changelog** format header and `[Unreleased]` section in CHANGELOG.md

## [v0.16.0] — 2026-03-03

### Added — GitHub App integration for automated PRs

- **`scripts/gh_app_token.py`** — Generates short-lived GitHub App installation tokens for `tars-bot-01`, enabling Claude Code to push branches and create PRs under its own identity
- **`PULL_REQUEST_PROCESS.md`** — Documents the full PR creation workflow using the GitHub App (token generation, push via `x-access-token`, PR creation via `gh`)
- **`.env.example`** — Added `GH_APP_ID`, `GH_INSTALLATION_ID`, `GH_APP_PRIVATE_KEY_PATH` variables
- **`.gitignore`** — Added `*.pem` to prevent accidental commit of private keys

### Fixed — Reviewdog CI warnings

- **Ruff**: Removed `UP038` from the ruff `ignore` list in `pyproject.toml` — the rule was removed from ruff and ignoring it emitted a warning on every CI run
- **Prettier**: Pinned `EPMatt/reviewdog-action-prettier` to `v1.3.0` (was `@v1`) to resolve the `fail_on_error` deprecation warning — v1.3.0 added proper `-fail-level` support

### Added — Release workflow

Added a `release.yml` on-demand workflow (`workflow_dispatch`) that automates the full release cycle:

- **Validates** that `pyproject.toml` and `CHANGELOG.md` versions match, and the tag doesn't already exist
- **Extracts** release notes from the current CHANGELOG section
- **Lists** merged PRs since the previous tag (via `gh pr list`)
- **Creates** a GitHub tag + release with combined changelog notes and PR list
- **Bumps** the version for the next development cycle (minor or patch, user's choice) and opens a PR with the updated `pyproject.toml` and `CHANGELOG.md`

Trigger from Actions → "Release - Tag & Bump" → Run workflow → choose `minor` (default) or `patch`.

### Added — Reviewdog PR reviews

Added a `reviewdog.yml` workflow that runs on every pull request and posts inline review comments on new/changed lines only (`filter_mode: added`):

- **Reviewdog - ESLint** — `reviewdog/action-eslint@v1` with `eslint-config-next/core-web-vitals` on `dashboard-next/src/`
- **Reviewdog - Prettier** — `EPMatt/reviewdog-action-prettier@v1` with Tailwind plugin, posts one-click code suggestions
- **Reviewdog - Ruff** — DIY via `ruff check --output-format=rdjson` piped to `reviewdog`, covers `src/` + `tests/`

All three jobs use `fail_level: error` and `reporter: github-pr-review` so they block merges and comment directly on the PR diff. Configure as required status checks in repo Settings → Branches → Branch protection rules.

### Added — ESLint + Prettier for dashboard-next

Integrated ESLint (via `eslint-config-next/core-web-vitals`) and Prettier (with `prettier-plugin-tailwindcss`) for the Next.js dashboard:

- **`eslint.config.mjs`** — Flat ESLint config extending `next/core-web-vitals` (native ESLint 9 flat config from eslint-config-next v16)
- **`prettier.config.mjs`** — Prettier config with Tailwind CSS class sorting plugin
- **`package.json`** — Added `lint` and `format:check` scripts, plus `eslint`, `eslint-config-next`, `prettier`, `prettier-plugin-tailwindcss` devDeps
- **`.pre-commit-config.yaml`** — Added ESLint + Prettier hooks (run on staged `dashboard-next/src/` files only)
- Fixed all existing violations: anonymous default export, custom font `<link>` (migrated to `next/font/google`), React hooks circular dependency in `useWebSocket`
- Auto-formatted all 37 source files to Prettier style

### Changed — CI workflow naming + path filtering

Renamed all GitHub Actions workflow checks for consistency, split the Python workflow into parallel jobs, and added `paths` filters so workflows only run when relevant code changes. All workflows now trigger on both `push` and `pull_request` to `main`, so every check can be configured as a required status check:

- **`frontend-lint.yml`** (new) — "Next Dashboard - Lint": ESLint + Prettier check (runs on `dashboard-next/**` changes only)
- **`frontend.yml`** — Renamed to "Next Dashboard - Tests" (runs on `dashboard-next/**` changes only)
- **`python.yml`** — Renamed to "Bot Python" with two parallel jobs: "Bot Python - Lint" (ruff) and "Bot Python - Tests" (pytest) (runs on `src/**`, `tests/**`, `pyproject.toml` changes only)

Four CI check names: `Next Dashboard - Lint`, `Next Dashboard - Tests`, `Bot Python - Lint`, `Bot Python - Tests`

### Added — Ruff linter + pre-commit hooks

Integrated [ruff](https://docs.astral.sh/ruff/) for linting and formatting across the Python codebase:

- **`pyproject.toml`** — Added `[tool.ruff]` config (Python 3.11, 120-char line length, rules: E/F/I/UP/B/SIM) and `ruff`/`pre-commit` as dev dependencies
- **`.pre-commit-config.yaml`** — Ruff lint (with `--fix`) and ruff format hooks run on every commit
- **CI** — `ruff check` and `ruff format --check` steps added to `python.yml` before pytest
- Fixed all existing violations: unused imports, unused variables, import sorting, `raise` chaining, `zip()` strictness, ambiguous variable names
- Auto-formatted all 69 Python files to ruff's style

### Added — GitHub Actions CI (two parallel workflows)

Two independent workflows run simultaneously on every push to `main`:

- **Python Tests** (`python.yml`) — Python 3.11 + uv, pytest with JUnit XML report and check annotations (via `mikepenz/action-junit-report`)
- **Frontend Tests** (`frontend.yml`) — Node 22, TypeScript type checking (`tsc --noEmit`), and Jest test suite

### Added — Jest test suite for dashboard-next

Bootstrapped Jest + Testing Library in `dashboard-next/` with 25 tests across 3 suites:

- `format.test.ts` — unit tests for all formatting utilities (currency, percent, countdown, PnL colors)
- `MetricCard.test.tsx` — render tests for the MetricCard component
- `StatusBadge.test.tsx` — render tests for the StatusBadge component

### Added — Filter bar on iteration history page

The History page now has a filter bar below the header with two filter groups:

- **Mode toggle chips** — PAPER (green), LIVE (blue), DRY RUN (amber) — click to toggle modes in/out; at least one must remain active
- **PnL radio chips** — All / Profitable / Unprofitable — filters iterations by `total_pnl > 0` or `<= 0`
- Summary stats (iteration count, candles, PnL totals, W/L) update dynamically to reflect filtered results
- "Showing X of Y" indicator appears when filters are active
- Empty state message when no iterations match current filters

### Added — Paper vs Live trading mode differentiation in iteration history

Every iteration now carries an explicit `trading_mode` field (`paper`, `live`, or `dry_run`) throughout the data pipeline — from live dashboard data through archive summaries to the frontend. The History page shows colored mode badges (green PAPER, blue LIVE, amber DRY RUN) on each iteration card, and the summary bar breaks down iteration counts and PnL totals by mode.

- `_assemble_dashboard_data()` always writes `trading_mode` (paper/live/dry_run)
- `_compute_summary()` persists `trading_mode` into `summary.json`
- `_enrich_iteration_summary()` extracts `live_trading` metrics (wallet balance, shadow paper PnL, execution cost) with backcompat inference for old archives
- Expanded live iterations show a "Live vs Paper" comparison: real PnL, shadow paper PnL, execution cost, and wallet balance
- Backfill: `_rebuild_iterations_json()` populates all 29 archived iterations (21 paper, 3 dry-run, 5 live)

### Added — Real-time WebSocket dashboard with Next.js frontend

Embedded WebSocket server inside the bot process pushes live state directly to a modern Next.js frontend at `dashboard-next/`. The frontend updates in real-time with animated numbers and cleanly separates Trading data from Tech/Status data.

**Python WS server (`src/polybot/ws/`):**
- `protocol.py` — Message type constants: `snapshot`, `trade`, `resolution`, `market`, `position`, `status`
- `broadcaster.py` — Client set management + message builders (build_snapshot, build_market_update, etc.)
- `server.py` — WebSocket server lifecycle (start/stop/handler with auto-reconnect cleanup)
- Broadcasts snapshot + status every 2s, market + position every 1s
- Immediate push of trade and resolution events as they happen
- `_assemble_dashboard_data()` refactored from `_write_dashboard_json()` (JSON file still written as fallback)

**Next.js app (`dashboard-next/`):**
- `/` — Trading dashboard: PnL summary, market info with countdown, positions with dynamic SL/TP, BTC panel, trade timeline, resolution table, risk bar
- `/status` — Live Status with Infrastructure (API latencies, gate pipeline, system health) and Execution (AI engine, risk state) tabs
- `/history` — Iteration history with expandable cards, PnL, win rate
- `/forensics` — Connects to existing `polybot-server` on port 8888
- `useWebSocket` hook with exponential backoff reconnect (1s → 30s max)
- `AnimatedNumber` component with requestAnimationFrame interpolation + easeOutCubic
- Offline fallback: fetches `dashboard_data.json` via API route when WS disconnects
- Dark theme ported from existing dashboard CSS vars

**Config:** `ws_enabled: bool = True`, `ws_port: int = 8765` in `LoggingConfig`

**New SharedState fields:** `api_latencies`, `ws_client_count`, `sqlite_queue_depth`

**New entry point:** `polybot-check` — runs Python tests + TypeScript type check + frontend tests

**Tests:** 17 Python tests in `tests/test_ws.py` covering protocol, broadcaster, and server

```bash
cd dashboard-next && npm run dev    # Start frontend at http://localhost:3000
uv run polybot-check                # Run all quality checks
```

### Added — `polybot-forensics` execution forensics system

New CLI + API + dashboard for deep post-session analysis of order execution. Six feature modules extract and cross-reference data from `polybot.db` to answer *why* orders fill or miss, *what they cost*, and *how to improve*.

```bash
polybot-forensics --db logs/polybot.db              # Full Rich report (all 6 features)
polybot-forensics --db logs/polybot.db --json        # JSON output
polybot-forensics --db logs/polybot.db --feature B   # Single feature (TTL counterfactuals)
polybot-forensics --feature A,C,E                    # Multiple features
```

**Feature modules:**
- **A: Execution Metrics** — per-order latency (decision→submit, submit→fill), ask drift in bps, fill source histogram, p50/p95/max aggregates
- **B: TTL Counterfactuals** — for each timed-out order, tests which TTL values (1s–60s grid) would have rescued it; produces a rescue curve
- **C: Cost Breakdown** — fees, slippage, and decision-drift cost per filled order; grouped by outcome (win/loss) and side (BUY/SELL)
- **D: Blocked Orders** — classifies risk-blocked orders into categories (kill_switch, timeout, no_book, etc.); assesses TTL and reprice recoverability
- **E: Round-Trips** — FIFO pairs BUY entries with SELL exits; computes realized PnL, MFE/MAE (max favorable/adverse excursion), exit efficiency
- **F: Decision Context** — correlates AI confidence, R/R ratio, indicators, and ML score with win/loss outcomes

**Metric glossary:** `docs/forensics.md` — full definitions, units, and formulas for every metric.

### Added — `polybot-server` FastAPI forensics API

Real-time API server for the forensics system, consumed by the web dashboard.

```bash
uv pip install -e ".[server]"                           # Install FastAPI + uvicorn
polybot-server --db logs/polybot.db --port 8888          # Start server
curl http://localhost:8888/api/forensics/execution       # Query feature A
curl -N http://localhost:8888/api/sse                     # SSE stream (auto-refresh)
```

**Endpoints:** `/api/forensics` (full report), `/api/forensics/{execution,ttl,costs,blocked,roundtrips,context}` (per-feature), `/api/sse` (server-sent events stream, polls DB every 2s).

### Added — Dashboard forensics tab

New "Forensics" tab in the web dashboard (`dashboard/index.html`). Connects to `polybot-server` and renders:
- Execution overview with fill rate gauge, latency metrics, fill source breakdown
- TTL rescue curve bar chart
- Cost waterfall with stacked bar (fees vs slippage vs drift)
- Blocked orders category bar with rescuability badges
- Round-trips table with PnL, MFE/MAE, exit efficiency
- Decision context heatmap (confidence vs outcome grid)

Auto-refreshes via SSE when server is running; falls back to static fetch.

### Added — `polybot-replay` candle replay runner

New CLI tool that deterministically replays any candle's per-second orderbook timeline offline, turning raw SQLite snapshot data into actionable fill-strategy insights.

```bash
polybot-replay --slug btc-updown-5m           # Latest candle matching slug
polybot-replay --slug btc-updown-5m --all     # All candles for slug
polybot-replay --slug btc-updown-5m --candle-id 15
polybot-replay --slug btc-updown-5m --ttl 5   # Counterfactual: 5s TTL
polybot-replay --slug btc-updown-5m --limit-price 0.45  # Fixed limit price scan
```

**Report sections:**
1. **Header** — Candle ID, market slug, traded side, duration, winner outcome
2. **Orderbook Summary** — Min/max/mean/stdev for best_bid, best_ask, mid, spread, BTC price
3. **Decision Timeline** — Each AI decision with confidence, fill price, book state at decision time
4. **Fillability Scan** — For each second, simulates placing a limit order at best_ask and checks if the book moves favorably within the TTL window. Reports: fillable seconds, fill rate, best/worst entry, fill delay distribution
5. **Post-Cancel Recovery** — For missed/cancelled orders, analyzes the 30s price trajectory after cancel to determine if price returned to fillable range
6. **Live Order Telemetry** — Overlays v0.15.0 `live_order_json` data: order lifecycle, polls, decision-to-submit ask drift, OB at submit/end/post-cancel
7. **Key Insights** — Auto-generated summary: best entry point, actual vs optimal fill comparison, TTL counterfactuals, post-cancel recovery, winner correctness

**Integrated into existing CLIs:**
- `polybot-analyze` — appends an aggregate Candle Replay Summary table after the performance report (reads `logs/polybot.db`)
- `polybot-archive` — runs replay on the archived DB, prints the summary, and saves aggregate stats to `summary.json` under the `replay` key

## [v0.15.0] — 2026-03-02

### Added — Full limit order execution telemetry

Every live CLOB limit order attempt now records rich execution telemetry via a new `LiveOrderResult` model, enabling post-session analysis of WHY orders fill or miss.

**Recorded per order attempt**:
- `order_id`, `limit_price`, `submit_ts`, `fill_ts`, `cancel_ts` — order lifecycle
- `fill_source` — how the fill was detected: `status_poll`, `size_matched`, `post_cancel`, `stealth_balance`, or `dry_run`
- `polls` — full status progression `[{ts, status, size_matched}, ...]` during TTL window
- `ob_at_submit`, `ob_at_end`, `ob_post_cancel` — orderbook snapshots (best bid/ask, depth, spread) at submit, resolution, and 1s after cancel
- `pre_balance`, `post_balance` — conditional token balances for stealth fill detection
- `decision_ob_ask`, `decision_ob_bid` — stale AI-snapshot orderbook (measures decision-to-submit drift)

**Storage**: telemetry is persisted in `TradeRecord.extra["live_order"]` (JSONL logs), `decisions.live_order_json` (SQLite), and `dashboard_data.json`.

**Dashboard**: trade detail panel now shows:
- Execution row: fill source + latency (filled) or timeout details + ask movement + post-cancel recovery (missed)
- Input Data grid: limit price, decision ask, ask drift %, ask at submit/end, fill latency, fill source

Paper-mode trades are unaffected (no `live_order` field).

## [v0.14.2] — 2026-03-01

### Fixed — Stealth fills: limit order fills missed due to CLOB API status propagation delay

The CLOB REST API has an async status propagation delay — an order can be matched by the matching engine while `get_order()` still reports status "LIVE" for 1-3 seconds. With a 3-second TTL, the bot would poll 3 times, see "LIVE" each time, cancel the order, and report "Live SKIPPED" — even though the order had already filled on-chain. The user would then have untracked positions in their proxy wallet.

**Root cause**: The polling loop only checked the `status` field for "MATCHED"/"FILLED". The CLOB API sometimes updates `size_matched` before the `status` transitions, and in extreme cases neither field updates within the TTL window.

**Fix**: Three-layer fill detection:
1. **`size_matched` check** — During polling, also checks `size_matched > 0` as a secondary fill indicator (may propagate before `status`)
2. **Post-cancel delay** — Waits 1s after cancelling before the verification poll, giving the API time to propagate
3. **Balance-based stealth fill detection** — Snapshots conditional token balance before order submission, then compares after timeout. If the delta matches the expected fill size (within 10% rounding tolerance), the order filled and a SimulatedFill is returned

### Fixed — SELL orders rejected: "not enough balance"

The AI's paper portfolio tracked 40 shares but the exchange contract's fill math delivered slightly fewer tokens on-chain (e.g. 39.383). The SELL order tried to sell the paper amount (40) but the proxy wallet only held 39.383 → "not enough balance".

**Root cause**: The exchange contract's rounding during BUY fills results in fewer conditional tokens than the requested size. The paper portfolio doesn't reflect this on-chain rounding.

**Fix**: Before a live SELL, queries the actual conditional token balance from the CLOB server (`get_balance_allowance(CONDITIONAL, token_id)`) and caps the sell size to the available on-chain balance. Also refreshes the server's cached allowance after each fill.

### Fixed — Orders rejected with "not enough balance / allowance"

The `ClobClient` had `signature_type=2` (POLY_GNOSIS_SAFE) but was missing the `funder` parameter. Without it, the `maker` field in signed orders defaults to the EOA address, but funds live in the Polymarket proxy wallet. The exchange checked the EOA for balance (zero) and rejected with "not enough balance / allowance".

**Root cause**: Polymarket browser wallets use a 1-of-1 Gnosis Safe proxy. The EOA signs orders, but the proxy wallet is the `maker` (funder) that holds USDC. Both `signature_type=2` AND `funder=<proxy_address>` are required.

**Fix**: Added `proxy_wallet_address` config field (`POLYBOT_TRADING_PROXY_WALLET_ADDRESS` env var). This is passed as the `funder` parameter to `ClobClient`, setting the correct `maker` address in signed orders. The proxy wallet address is found on the Polymarket Profile Settings page.

## [v0.14.1] — 2026-03-01

### Fixed — Wallet balance always reads $0.00

The CLOB balance API requires `signature_type=2` for Polymarket proxy wallets — the default (`0`) returns zero. Also the raw balance is in USDC's 6-decimal units and needs dividing by 1e6. This caused the bot to abort on startup with "wallet balance is $0.00".

## [v0.14.0] — 2026-03-01

### Changed — Replace drift-check FOK with 3-second GTC limit orders

The live execution engine previously used FOK market orders with a stale-price drift check (3% threshold). In fast-moving 5-minute BTC candle markets, token prices routinely swing 20-100% between the AI decision and execution, causing the drift check to reject most trades — creating a large divergence between shadow PnL and live PnL.

**New approach**: Place a GTC limit order at the AI's evaluated price (best_ask for BUY, best_bid for SELL), wait up to `limit_order_ttl_seconds` (default 3) for a fill, then cancel if unfilled. This is safer (you never pay more than the AI evaluated) and fills more often (order sits on the book waiting for the market to come back).

- **Real mode**: `_submit_limit_order()` posts a GTC order via `OrderArgs`, polls `get_order()` every 1s, cancels on timeout
- **Dry run mode**: `_simulate_limit_order()` re-fetches the live orderbook up to TTL times, fills if the market crosses the limit price
- **Dashboard visibility**: Unfilled live trades now show as `BLOCKED` in the candle timeline with the skip reason (e.g. "limit order timeout (3s)")
- **Config**: New `limit_order_ttl_seconds: 3` in TradingConfig; `max_price_drift_pct` retained for backward compat but no longer used
- **Post-cancel verification**: After cancelling a timed-out order, re-checks `get_order()` once to catch fills that raced the cancel — prevents missed fills and phantom positions

### Added — Shadow PnL & Exec Cost metrics on dashboard

In live mode, the session stats panel now shows two new metrics from `live_trading` data: **Shadow PnL** (what the paper simulator would have made) and **Exec Cost** (live vs paper difference — slippage + real fees vs simulated). Both are color-coded green/red by sign and only appear when live trading data exists.

## [v0.13.0] — 2026-03-01

### Fixed — Bot version captured at startup, not archive time

Previously, the bot version was read from `importlib.metadata` at archive time. If `pyproject.toml` was bumped between a session and its archive, the wrong version was recorded. Now `__version__` is captured once at `TradingAgent` startup, persisted to `dashboard_data.json` and `agent_state.json`, and the archiver reads it from there (with `importlib.metadata` fallback for old data).

### Fixed — Adaptive threshold cap for wild markets

The hard `$50` cap on `btc_threshold` prevented the adaptive system from protecting against genuinely wild markets. In iter_020, 36% of fakeouts exceeded $50 (up to $320), but the threshold was clamped at $50 — so the bot entered on $50 moves that were still noise.

**Adaptive cap**: `max($50, min($100, P75 * 1.2))` — rises with fakeout P75 in volatile markets, bounded [$50, $100]. In calm markets (P75=$30), cap stays at $50 and threshold is unchanged. In wild markets (P75=$78), cap rises to $94, letting threshold reach $57 instead of being clamped at $50.

**Wild market advisory**: When recent fakeout max exceeds 1.5x the threshold, the AI prompt includes a HIGH-VOLATILITY MARKET warning advising sustained confirmation (15-20s above threshold) and the 150-200s entry window.

### Fixed — Cumulative session records anchor AI on stale stats

The AI saw inflated cumulative stats like "11W/1L (92%) on DOWN" and anchored on them even as recent performance degraded. Now shows trailing-first format: `Recent 5 trades: 3W/2L (60%) | Session: 16W/8L (67%)` with per-side trailing windows. Entry timing stats also show trailing-10 buckets before full-session buckets. When fewer than 5 resolved trades exist, falls back to cumulative-only format.

### Fixed — Knowledge observations lack freshness decay

Observations displayed without age context let stale hints like "expensive DOWN entries won 5/5" persist at full weight. Now computes `freshness = 1.0 - age/expires_after` and prefixes observations below 50% freshness with `[AGING]`. Both the decision prompt and reflection prompt show freshness percentages, nudging the AI to verify aging observations against recent trades and the reflection AI to expire stale ones.

## [v0.12.0] — 2026-03-01

### Fixed — Auto-close flip SELL not logged

`_auto_close_for_flip` updated the portfolio but never wrote a TradeRecord to JSONL — zero SELL records in the audit trail for reversal flips. Added `cycle` parameter and `_log_cycle()` call after successful fill so every flip close is captured in the trade log.

### Fixed — Reversal retracement fires too early

PositionMonitor could fire reversal_retracement after just ~10s (10 snapshots). On noisy candles, early BTC noise crossing zero triggered a premature flip that guaranteed a loss on the first leg. Added a 30-second minimum hold time guard before checking retracement. Also raised the minimum peak from $15 to $25 (matching `MIN_PEAK_COMMIT` in adaptive_entry.py) so only meaningful peaks trigger retracement analysis.

### Added — Patience advisory for UNCERTAIN regime

In UNCERTAIN signal regimes (40-60% reversal rate), early entries (>200s remaining) historically underperformed — iter_020 saw the >200s bucket collapse from 71-78% WR to 20-33%. Both UNCERTAIN prompt blocks in `get_ai_context()` now include soft timing guidance nudging the AI to wait for the 150-200s window or stronger confirmation on marginal setups. This is prompt-level advice, not a hard gate — the AI can still enter early on genuinely strong signals.

## [v0.11.0] — 2026-03-01

### Added — Live entry timing performance indicator

iter_019 analysis: 69% of trades at >200s remaining won only 43.8%, while entries at 150-200s won 85.7%. The AI had no visibility into its own entry timing track record during the session.

New `_compute_entry_timing_stats()` computes win rate by time-remaining bucket (>200s, 150-200s, 100-150s, <100s) from resolved session trades and injects the results into the AI prompt. Requires 3+ resolved BUY trades to activate (avoids noise). Identifies the best-performing bucket (2+ trades) and advises patience on marginal setups. Computed on-the-fly each cycle from existing `session_trades` + `recent_resolutions` — no new state tracking needed.

### Improved — Enriched reversal retracement prompt

iter_019 analysis: reversal retracement fired on 10 of 16 traded candles but HOLD/FLIP accuracy was only 60% (6/10), costing $20.88 net. Root cause: the 8-line generic reversal prompt gave the AI no quantitative retracement data, so it evaluated the post-retracement BTC move as a standalone entry signal (e.g. candle 3: "$9 move is too small = noise" — missing that $44→$9 is an 80% retracement).

New `_compute_retracement_context()` helper computes from per-second prefilter history: peak BTC move + age, retracement %, zero crossing (BTC switched sides), retreat velocity + acceleration, time since peak, and opposite-side R/R. The reversal prompt now includes this structured data plus a decision guide that teaches the AI to read the retracement pattern instead of the absolute BTC level. System prompt also adds a baseline section on reversal retracement interpretation.

## [v0.10.1] — 2026-03-01

### Added — Bot version tracking per iteration

Each archived iteration now records which bot version ran it. `summary.json` includes a `version` field set from `importlib.metadata` at archive time. `__init__.__version__` now syncs from `pyproject.toml` instead of a stale hardcoded value. All 18 past iterations were backfilled using git tag dates vs iteration date ranges. Dashboard shows version badges in the iteration detail header, sidebar list, and overview cards.

## [v0.10.0] — 2026-03-01

### Fixed — Over-filtering: 38% entry rate despite good WR

iter_018 showed 107 candles but only 41 trades (38% entry rate) with 73.7% WR. Three causes addressed:

1. **AI anti-timing-rationalization prompt** — 76% of Sonnet HOLDs cited "too late" with 2-4 minutes remaining, despite the prompt already saying > 120s is "good time." Added explicit guidance: "Time alone is NEVER a reason to HOLD if you have an edge." Screening prompt time threshold also tightened (120s → 60s) so weak-signal rejections require < 60s instead of < 120s.

2. **Adaptive threshold P75 → P50, cap $100 → $50** — After volatile candles, P75 climbed too high (e.g. $91) blocking real $30-$60 moves. Now uses median (P50) with a $50 cap, so the threshold stays responsive without over-reacting to outliers.

3. **Reversal retracement bypasses ALL guards** — Reversal exits now bypass the winning-position guard (already bypassed cooldown in v0.9.1). Previously a profitable position with matching BTC direction and < 120s remaining would block the reversal exit.

### Fixed — Self-poisoning per-side accuracy warnings

The AI developed a self-reinforcing avoidance loop: early DOWN losses → "0% DOWN accuracy" stat → "be extra cautious" warning → AI refuses all DOWN trades → stat can never improve. 80% of iter_018 HOLDs cited this stat, even with strong $50-130 BTC moves and 3-4 minutes remaining.

Reframed per-side accuracy and losing streak warnings from avoidance ("be extra cautious") to learning ("review WHY these lost, fix entry criteria, do NOT avoid the side entirely"). The trade table already shows entry price, signal type, and outcomes — the AI should analyze patterns, not develop phobias.

### Added — Candle timelines in iteration detail view

Dashboard iteration view now lazy-loads candle timelines from `archive/{label}/logs/dashboard_data.json`. Shows the same per-candle trade timeline used in the live view, cached per iteration for fast re-renders.

## [v0.9.2] — 2026-03-01

### Fixed — Haiku screening returns empty reasoning

Haiku sometimes returned `reason: ""` in its screening tool call, causing the dashboard to show "No reasoning". Strengthened the schema description to demand specific reasoning (e.g. "BTC move only $8, below $15 threshold"). Logs a warning if Haiku still returns empty.

## [v0.9.1] — 2026-02-28

### Fixed — Reversal retracement blocked by AI cooldown

Reversal retracement triggers were being blocked by the 60s AI cooldown — by the time cooldown expired, the flip opportunity was gone. Now `reversal_retracement` bypasses the cooldown entirely (stop-loss emergency bypass at -30% still applies to other triggers).

### Changed — Single-call reversal flip

Reversal retracement now uses a single AI call instead of two. When BTC retraces 80%+ from peak, AI sees HOLD vs BUY opposite. If AI says BUY, the anti-hedge guard auto-closes the held position via `_auto_close_for_flip` — no second AI call needed.

## [v0.9.0] — 2026-02-28

### Added — Reversal retracement detection + contrarian flip

**Reversal retracement** — a new PositionMonitor trigger that fires when BTC retraces 80%+ from its peak move back toward the candle open while a position is open. Instead of waiting for the stop-loss to fire (when the opposite side is already $0.80+), the bot detects the reversal early and asks AI to decide: HOLD (keep position, SL stays active) or flip to the opposite side.

**Post-SL contrarian flip** — after a **stop-loss** exit, if the position was closed and BTC confirms the reversal, a second AI decision is triggered for the opposite side. The anti-flip guard is bypassed for this entry only.

**Post-SL flip conditions:**
1. Exit was a **stop-loss** (not take-profit)
2. Position was actually closed (AI chose SELL, not HOLD)
3. **Time remaining >= 60s**
4. **BTC confirms reversal** — BTC move from candle open is against the exited position

No price gate — the AI sees the full context and decides BUY or HOLD.

### Changed — Shorter fakeout window for BTC threshold (10 → 5 candles)

The fakeout P75 threshold was computed from the last 10 candles, but a few volatile candles with $85-$102 fakeouts pushed the threshold to $91 — blocking entries on normal $30-$60 BTC moves for many candles. Now the fakeout threshold uses the **last 5 candles** so volatile outliers age out in ~25 min instead of ~50 min. The reversal rate and signal type still use the full window (10 candles) for smoothness.

## [v0.8.1] — 2026-02-28

### Reverted — Cheap entry pipeline (v0.7.0) causing 21% WR / -$267 over 4 iterations

iter_011 through iter_014 analysis: 62 trades, 30% combined WR, -$267 net. Root cause traced to v0.7.0's cheap entry pipeline — 4 coordinated changes that removed every gate blocking cheap entries. Before v0.7.0 (iter_010): 75% WR, +$155. After: consistent losses.

The "breaks even at 35% accuracy" EV math was correct but the assumption was wrong — bypassing all gates doesn't give 35%+ accuracy, it gives 21%. Cheap entries that happen *naturally* (after BTC moves past threshold) had ~56% WR; force-fed cheap entries without BTC signal had 21%.

**Reverted 4 changes:**

1. **Adaptive entry bypass removed** (`adaptive_entry.py`) — `min_ask <= 0.35 → return True` bypass removed. Cheap entries now require BTC to cross the fakeout threshold like any other entry. The threshold already adapts to market conditions ($20-$100).

2. **Prefilter spread exemption removed** (`prefilter.py`) — Check 2 (both spreads wide) now applies to all entries regardless of price. Wide spreads on cheap entries were being dismissed as "noise vs R/R" but actually signal thin markets where fills are unreliable.

3. **Haiku screening thresholds restored** (`prompts.py`) — "Attractive entry" reverted from `< $0.40` to `< $0.30`. "Unattractive entries" reverted from `> $0.50` to `> $0.40`. Tighter screening prevents low-quality entries from reaching Sonnet.

4. **Drawdown/streak cheap exceptions removed** (`knowledge.py`) — Removed "Exception: very cheap entries remain +EV — do not skip these" from drawdown alert and losing streak warning. During drawdowns, ALL entries should be more selective.

**Kept from v0.7.0:** Fakeout-based threshold formula (sound improvement), UNCERTAIN cheapest-side suggestion (fires after BTC crosses threshold).

**Kept from v0.8.0:** Wider SL for cheap entries (≤$0.30: 15%, ≤$0.40: 10%) — helps the rare natural cheap entries that pass threshold.

### Fixed — Remove +$5 margin from fakeout threshold

The fakeout threshold was computed as P75 + $5, but the $5 margin created blind spots — a $57 peak on a $60 threshold was missed as a reversal. P75 alone already represents "75% of fakeouts are smaller than this," which is sufficient. Now `btc_threshold = P75` (clamped $20-$100).

### Changed — Retracement-based reversal detection

The old reversal detection ("which side crossed the fakeout threshold first?") measured noise, not commitment. A $25 bounce on the way to an $80 drop was counted as "reversed." And a genuine $60 wrong-direction commitment that crossed the threshold first got missed.

**New algorithm** — reversal = commitment + retracement + acceleration:

1. **Identify initial BTC direction** — first snapshot with |move| > $5
2. **Threshold crossing** — if BTC crosses the fakeout threshold in the initial direction, momentum is confirmed. Winner determines reversal
3. **80% retracement** — if BTC never crosses the threshold but retraces 80%+ of its peak commitment AND the retreat is accelerating (or has crossed zero), that's a reversal
4. **Inconclusive** — neither threshold crossed nor 80% retraced → `reversed = False` (not enough commitment to judge)

Three states replace the old binary threshold-crossing check:
- **Momentum confirmed**: BTC crossed fakeout threshold → `reversed = (initial_direction != winner)`
- **Retracement reversal**: 80%+ retracement with acceleration or zero-cross → `reversed = (initial_direction != winner)`
- **Inconclusive**: Peak < $25 or retracement < 80% → `reversed = False`

**Acceleration check**: Compares average directional position in the first half vs second half of sampled retreat readings (every 5 snapshots after peak). If second half is lower → retreat is accelerating. If price has crossed zero (opposite side of open), reversal is flagged regardless of acceleration.

**Constants**: `RETRACEMENT_THRESHOLD = 0.80`, `MIN_PEAK_COMMIT = $25`, `VELOCITY_SAMPLE_SEC = 5`

**Validation on 470 historical candles**:
- 85% agreement with old algorithm
- 37+ false positives eliminated (old=reversed, new=not): noise peaks below $25 excluded, plus cases where old $20 first-cross was fooled
- 33 real reversals caught (old=missed, new=caught): mostly zero-cross reversals where BTC peaked $25+ then collapsed past zero

**Files changed**:
- `adaptive_entry.py`: new constants, `record_outcome()` and `bootstrap_from_binance()` use retracement logic, `get_ai_context()` prose updated, `CandleOutcome` docstrings updated
- `prompts.py`: screening prompt wording updated

**Not changed**: `direction_at_20`/`winner_ask_at_20` fields (still captured for entry price calibration), fakeout threshold computation, signal type thresholds, dynamic SL/TP, position sizing, JSONL field names

## [v0.8.0] — 2026-02-28

### Fixed — Bootstrap uses hardcoded $20 threshold, inflating reversal rate

The Binance bootstrap (warm start on fresh sessions) still used the hardcoded `$20` for initial direction detection — the same bug fixed in `record_outcome()`. This caused bootstrapped reversal rates of 58-60% (UNCERTAIN) when the dynamic threshold ($72) would compute 8% (MOMENTUM). iter_014's 3 losses were all contrarian UP buys triggered by this inflated rate.

- `bootstrap_from_binance()`: replaced `>= 20.0` with `>= self.btc_threshold`
- Added near-zero guard (`abs(final_move) < 5.0`) to exclude flat candles from reversal counting
- Same fix as `record_outcome()` — the logic was duplicated but only one copy was updated

### Fixed — UNCERTAIN contrarian overtrading + cheap entry SL

iter_013 analysis: 19 trades, 31% win rate, -$21.41 PnL. UNCERTAIN trades destroyed PnL (12 trades, 25% WR, -$34.53) while MOMENTUM trades were fine (7 trades, 67% WR, +$13.12). Three interconnected fixes:

**1. Reversal detection threshold: $20 → dynamic fakeout threshold** (`adaptive_entry.py`)

The reversal rate was inflated by a hardcoded $20 detection threshold. At $20, small moves (noise) were counted as "reversals" — BTC bouncing up $22 on its way to closing -$80 was flagged as "reversed." Data: small moves (<$57 fakeout threshold) had a 59% "reversal" rate (coin flips); large moves (>=$57) had only 26%. The 40% blended rate put the signal into UNCERTAIN territory when the market was actually momentum-driven for real moves.

- `record_outcome()`: replaced hardcoded `>= 20.0` with `>= self.btc_threshold` (the dynamically-computed fakeout threshold from P75 of peak wrong-direction moves)
- Added guard: near-zero BTC moves (`abs(btc_close - btc_open) < 5.0`) are now excluded from reversal counting — these are Chainlink timing artifacts, not real reversals

No circular dependency: `btc_threshold` is computed from fakeout magnitudes (`peak_up_move`/`peak_down_move`), NOT from the `reversed` flag.

**2. BTC-move-aware UNCERTAIN suggestion** (`adaptive_entry.py`, `ai_decision.py`)

The cheapest-side suggestion fired in UNCERTAIN markets regardless of how far BTC had moved. At $80 BTC move, telling Claude to go contrarian is fighting strong momentum.

- `get_ai_context()` now accepts `abs_btc_move` parameter
- When BTC has cleared the fakeout threshold: message says "momentum entries are favored over contrarian"
- When BTC is below the threshold: original cheapest-side guidance applies (could still be noise)
- Adapts automatically to volatility — in noisy markets with $60+ fakeouts, the threshold is higher

**3. Wider dynamic SL for cheap entries** (`position_monitor.py`)

Current SL widened only 5% for cheap entries. At $0.34 entry with -35% base SL, exit triggered at $0.255 — an absolute swing of just $0.085. In iter_013, 3 of 11 losses (27%) were correct-side trades killed by SL before resolution.

- Very cheap (≤$0.30): widen 15% (was 5%)
- Cheap (≤$0.40): widen 10% (was 5%)
- Example: $0.34 entry → SL at $0.187 (was $0.204), giving cheap tokens room for their naturally large percentage swings

**4. Haiku screening: scope UNCERTAIN cheap-side to moderate moves** (`prompts.py`)

Updated the UNCERTAIN screening rule to note that cheap-side entries apply to moderate BTC moves ($15-$50), and larger moves (>$50) should favor momentum.

### Fixed — Haiku screening rejects negative BTC moves as "below threshold"

Haiku compared the signed BTC move value (e.g., `$-80`) against the `>$15` threshold using naive comparison: `-80 < 15` = true, so an $80 DOWN move was rejected as "no signal." Added explicit instruction that BTC moves are signed values and all threshold comparisons must use the absolute magnitude. Changed all threshold language from "BTC move" to "BTC move magnitude."

### Added — Reflection feedback: teach Claude to learn from "wrong side" mistakes

The bot bought UP at $0.68 in a 50% reversal market when DOWN was $0.31 — the pipeline delivered the entry correctly, but Claude followed momentum instead of buying the cheap side. The feedback loop was blind to this class of mistake because reflection couldn't see opposite-side prices, signal type, or reversal rate.

**Three changes close the feedback gap:**

1. **Data capture** (`ai_decision.py`) — For every BUY trade, `record.extra` now stores `opposite_ask` (the other side's best ask), `signal_type` (MOMENTUM/UNCERTAIN/CONTRARIAN), and `reversal_rate`. All three were already in scope at trade time but weren't persisted.

2. **Reflection visibility** (`knowledge.py`) — The trades table in reflection now shows `Opp Ask` and `Signal` columns (replacing `Size`, which wasn't diagnostic for learning). A new **Side Selection Analysis** section flags trades that bought the expensive side (>$0.55) when the opposite was cheap (<$0.40) in UNCERTAIN/CONTRARIAN markets, with win/loss outcome. The reflection prompt instructs Claude to pay attention to these patterns.

3. **Real-time feedback** (`knowledge.py`) — The recent trades table in `build_feedback_context()` now includes `Opp Ask` and `Signal` columns. When 2+ trades show the expensive-side-in-uncertain-market pattern, a warning is appended so Claude can self-correct within a session.

**Backward compatible**: Old trades without the new `extra` fields show "—" in enriched columns and are excluded from pattern analysis.

## [v0.7.0] — 2026-02-28

### Changed — Cheap entry pipeline: stop blocking profitable opportunities

iter_011 analysis: 17 of 22 candles (77%) had the winner side at < $0.50, 14 at < $0.40. The bot captured zero cheap entries — all 4 wins were at expensive fills ($0.75–$0.81). Every pipeline layer was blocking cheap entries before they reached Claude.

**Problem**: The EV math is clear — a $0.35 entry breaks even at 35% accuracy. At 50%: +$0.15/trade. At 40%: +$0.05/trade. Cheap entries are +EV by construction, but the adaptive entry gate (requires BTC move $30+), prefilter spread check, Haiku screening threshold ($0.30), and drawdown warnings all conspired to block them.

**Changes across 4 files:**

1. **Adaptive entry bypass** (`adaptive_entry.py`) — When `min_ask <= 0.35`, `should_trigger()` returns True regardless of BTC move threshold. Cheap entries reach AI before BTC crosses the fakeout threshold. Cooldown + prefilter still gate.

2. **Prefilter spread exemption** (`prefilter.py`) — Check 2 (both spreads wide) is skipped when `best_entry < 0.35`. Wide spreads on a $0.30 entry are noise vs the R/R.

3. **Haiku attractive entry raised** (`prompts.py`) — Screening prompt "attractive entry" threshold: `< $0.30` → `< $0.40`. The false rule for unattractive entries also raised from $0.40 → $0.50. Entries at $0.30–$0.40 now qualify as standalone pass-through signals.

4. **Softer drawdown/streak for cheap entries** (`knowledge.py`) — Drawdown alert now includes: "Exception: very cheap entries (ask < $0.35) have favorable R/R even at lower accuracy — do not skip these." Losing streak warning changed to: "Increase selectivity on expensive entries. Cheap entries (ask < $0.35) remain +EV even at low win rates."

**Not changed**: Claude's decision freedom (changes get entries TO Claude, don't force buys), position sizing, SL/TP, risk checks, fakeout threshold formula (still gates normal entries), cooldown (60s), prefilter time/depth/choppy checks.

### Changed — Fakeout-based dynamic BTC threshold

Replaced the V-shaped reversal-rate formula ($20–$50) with a **fakeout magnitude-based threshold** ($20–$100) learned from the last 10 candles' actual BTC trajectories.

**Problem**: 3 of 4 recent losses were reversals — BTC moved one way at entry, then flipped. The V-shaped formula peaked at $50, but fakeouts of +$45 and +$56 both reversed and caused losses. The formula used a fixed $20 detection point and an abstract `abs(rate - 0.5)` deviation — disconnected from actual market noise.

**Solution**: For each candle, measure how far BTC moved in the *wrong direction* (peak move opposite to eventual winner) from the 300 per-second prefilter snapshots. Set the threshold above typical fakeouts:

- `peak_up_move` = max positive `btc_move_from_open` during candle
- `peak_down_move` = max abs(negative `btc_move_from_open`) during candle
- Fakeout = peak in wrong direction (if winner=UP, fakeout = peak_down_move)
- Threshold = **P75(last 10 fakeouts) + $5 margin**, clamped to [$20, $100]

**Examples**:
- Small fakeouts `[0, 2, 5, 8, 10, 12, 15, 18, 22, 25]` → P75=$20 → threshold=$25
- Large fakeouts `[10, 15, 25, 30, 35, 40, 45, 50, 55, 80]` → P75=$52 → threshold=$57

**Backward compatible**: Falls back to V-shaped formula when peak data is unavailable (old JSONL records without `peak_up_move`/`peak_down_move` fields). Binance bootstrap now approximates peak moves from 1-min high/low.

**Dashboard**: Fakeout badge shows P75/Max/Median when fakeout data is active. BTC Threshold tooltip updated. Color breakpoints widened for $100 range (red at $60+).

**Cheapest-side suggestion for UNCERTAIN markets** — When reversal rate is 40–60% (coin-flip territory), the AI receives a suggestion to lean toward the cheaper side when both asks are in the balanced range ($0.35–$0.65). At ~50% accuracy, only cheap entries are profitable after fees. However, this is a soft suggestion — when one side is clearly confirmed by price (e.g., $0.90 vs $0.10), the AI should trust the market signal. The guidance applies mainly to early-candle balanced prices, not late confirmations. Signal type boundaries widened to match: MOMENTUM (<40%), UNCERTAIN (40–60%), CONTRARIAN (>60%).

**Unchanged**: `reversal_rate`, `signal_type`, `regime`, `direction_at_20`, `reversed`, `max_entry_price`, dynamic SL/TP — only the BTC threshold formula and UNCERTAIN market guidance are changed.

### Fixed — Archive missing ask prices, R/R, streak in snapshot timelines

The archive enrichment query was missing 6 columns that the live dashboard query includes: `up_best_ask`, `down_best_ask`, `rr_up`, `rr_down`, `streak`, `streak_direction`. This meant archived iterations lacked the data needed for price heatmaps (cheap entry windows), prefilter tick popovers (entry prices, R/R), and streak context. Now matches the live dashboard query exactly.

### Fixed — Haiku screening blocks UNCERTAIN market entries

The Haiku screening prompt used the old signal boundaries (CONTRARIAN >55%, false-when < 55%) and had no awareness of the UNCERTAIN regime. In 40–60% reversal markets with balanced prices, Haiku would reject valid cheap-side entries because "both asks > $0.40 and reversal rate < 55%" matched its false rule. Updated:
- CONTRARIAN trigger: >55% → >60%
- False rules: reversal rate < 55% → < 40% (don't block UNCERTAIN zone)
- New true rule: uncertain (40–60%) + balanced prices ($0.35–$0.65) + BTC moved >$15 = valid cheap-side setup

### Fixed — AI cooldown race condition

The 60s cooldown between AI calls was bypassed when MarketMonitor re-triggered during an async Haiku/Sonnet call. The race: (1) MarketMonitor checks cooldown → OK → sets trigger event, (2) AIDecision clears event, starts async Haiku call, (3) MarketMonitor's next 1s tick sees event cleared and cooldown still based on the *previous* call time → sets event again, (4) Haiku finishes, calls `_record_ai_call_time()` → but event is already re-set. Result: two Haiku calls 19s apart instead of 60s. Fix: record `ai_last_call_time` immediately when the entry trigger fires (before async work), not after completion. The final call time is still updated when the decision completes.

### Added — Interactive prefilter ticks on candle timeline

Prefilter tick marks on the candle timeline are now hoverable with a rich popover showing the full prefilter context at each snapshot:
- **Hover popover**: Shows PASS/FAIL status with reason, entry prices (best ask), R/R ratios, BTC price & move, spread, depth, and streak
- **Cheap rejection highlighting**: Failed ticks where min(UP ask, DOWN ask) < $0.35 render in amber instead of gray — makes it easy to spot contrarian entries the prefilter blocked
- **New data columns**: `up_best_ask`, `down_best_ask`, `rr_up`, `rr_down`, `streak`, `streak_direction` now flow from SQLite snapshots into the dashboard JSON

### Added — Real-time Bot Status dashboard panel

The bot is no longer a black box. A new "Bot Status" panel on the dashboard shows the full gate pipeline on every tick (1s updates):
- **Gate pipeline visualization**: Prefilter → Adaptive Entry → Cooldown → AI Trigger, each step colored green (pass) / red (blocked)
- **Gate status message**: Exactly why the AI isn't being called (e.g., "PREFILTER: No clear setup: streak=1, best entry=0.520 > 0.500", or "ADAPTIVE: BTC move $8 < $30 threshold", or "COOLDOWN: 42s remaining")
- **Live market data**: BTC move from candle open, UP/DOWN ask prices, R/R ratios, streak, position status
- Data flows from `MarketMonitor` → `SharedState.monitor_status` → dashboard JSON → UI

## [v0.6.0] — 2026-02-28

### Fixed — 3 improvements from iter_010 deep analysis (75% WR, +$155 net)

**Bug fix: SL sell size rounding** — Position sizing creates fractional share counts (e.g., 30.6) via R/R scaling, but the AI prompt displayed shares as integers (`:.0f` rounds 30.6 → "31"). When the AI tried to sell "31 shares" with only 30.6 held, the `short_sell_prevention` risk check blocked the exit. This occurred 4 times in iter_010. Fixed by:
- Clamping sell size to actual held shares before risk checks (`ai_decision.py`)
- Showing share counts with 1 decimal (`:.1f`) in the AI prompt (`prompts.py`)

**Entry price hard cap ($0.85)** — Data shows entries at $0.85+ (R/R < 0.18) have negative average PnL. Even at 85% accuracy, fees and execution costs push these trades underwater. Added a hard block on BUY entries where the best ask >= $0.85 (`ai_decision.py`).

**Dashboard: Haiku screening visibility** — When Haiku screens and rejects a trade, the dashboard now shows:
- Haiku's reasoning (was blank before — `_log_cycle` was called without a decision)
- The actual formatted context Haiku received (BTC vs candle open, orderbook depth, R/R, indicators) via "Show Haiku Input" toggle

**Haiku screening context enriched** — `format_screening_context` now includes the primary BTC signal (move from candle open), orderbook depth, and R/R ratios for both tokens. Previously it only showed raw BTC price with no candle-open comparison.

### Added — Live Polymarket CLOB Trading

The bot can now place real money trades on Polymarket via the CLOB API, while running a shadow paper simulator in parallel for comparison.

**Two modes** (configurable, defaults to paper):
- `mode: "paper"` (default) — paper simulator only, exactly how it works today. No changes to existing behavior.
- `mode: "live"` — real FOK market orders via py-clob-client Level 2 + shadow paper simulator running side-by-side.

**New files:**
- `src/polybot/execution/__init__.py` + `live.py` — `LiveExecutionEngine` wrapping py-clob-client for real CLOB orders
- `scripts/generate_api_key.py` — Standalone script to derive CLOB API credentials from a wallet private key

**LiveExecutionEngine** (`execution/live.py`):
- Creates Level 2 `ClobClient` with wallet + API credentials
- Submits FOK (fill-or-kill) market orders — fills entirely or rejects, no partial fills or stuck orders
- Stale price mitigation: re-fetches orderbook before every order, skips if price drifted >3% since AI decision
- Returns the same `SimulatedFill` type as `ExecutionSimulator` — Portfolio, risk, indicators, AI, dashboard all unchanged
- `dry_run` mode: signs orders but doesn't post (for testing auth flow)

**Safety layers (defense in depth):**

| Layer | What | Where |
|-------|------|-------|
| 1 | Config default `mode: paper` | `config.py` |
| 2 | Dry run mode (sign, don't post) | `LiveExecutionEngine` |
| 3 | Max order size ($50 hard cap) | `LiveExecutionEngine.execute()` |
| 4 | Min wallet balance check ($5) | `LiveExecutionEngine.execute()` |
| 5 | Session kill switch ($40 loss → shutdown) | `_balance_sync_loop()` |
| 6 | Stale price drift check (3% max) | `LiveExecutionEngine.execute()` |
| 7 | Existing risk manager (unchanged) | `RiskManager` |
| 8 | FOK orders (no partial fills) | CLOB API |
| 9 | Startup credential + balance validation | `agent.py` |

**Shadow paper tracking (live mode):**
- Both `LiveExecutionEngine` AND `ExecutionSimulator` run on every trade
- Real fill → applied to real `Portfolio`. Paper fill → applied to `_shadow_portfolio`
- Trade logs include `paper_fill_price` and `paper_total_cost` for comparison
- Dashboard shows `live_trading` section: wallet balance, kill switch status, shadow PnL, execution cost diff
- At candle resolution, logs both: `Shadow paper PnL: $X | Live PnL: $Y | Diff: $Z`

**Config additions** (`TradingConfig`):
- `mode`, `private_key`, `api_key/secret/passphrase`, `chain_id`
- `max_order_size_usd` (50), `max_session_loss_usd` (40), `min_wallet_balance_usd` (5)
- `max_price_drift_pct` (0.03), `dry_run` (false)
- All overridable via `POLYBOT_TRADING_*` env vars

**New async task**: `_balance_sync_loop()` — checks USDC wallet balance every 60s, runs kill switch check

### iter_009 Analysis (first test of v0.5.0 AI engineering + soft safeguards)
- **1.2 hours, 53 candles, 12 traded** — short session. 41.7% win rate (5W/7L), -$37.15 PnL, -$39.17 net after fees ($0.97) and AI cost ($1.04)
- **Losses on UP candles dominate**: 5/7 losses were on UP-winning candles where the bot bet UP but got stopped out before resolution. Only 2/7 losses on DOWN candles
- **Stop-loss triggering too aggressively on winners**: candles 1772204700 and 1772203200 were ultimately won by the side the bot bet on, but dynamic SL exited at -36%/-44% mid-candle. Both would have been profitable if held
- **Largest loss (-$43.42)** on candle 1772205300: bet DOWN at $0.773 with 0.78 confidence on a -$124 BTC move, but candle resolved UP ($-20 close). Classic reversal — strong signal reversed in final minutes
- **High entry prices**: avg fill $0.69 across all BUYs. 5 entries at >$0.70 (up to $0.911) — expensive entries with low R/R. The "cheap entries are traps" lesson overcorrected to accepting expensive entries
- **Avg loss ($14.50) is 1.13x avg win ($12.87)** — improved from iter_008's 2.1x ratio. The dynamic SL/TP is cutting losses closer to wins, but winning too infrequently
- **Low trade frequency**: only 12/53 candles traded (22.6%). The adaptive entry threshold + prefilter + cooldown is being very selective, but the selections aren't winning
- **Key problems to address**: (1) dynamic SL ejecting positions that ultimately win — need wider SL or BTC-direction check before SL fires, (2) expensive entries reducing R/R, (3) reversal detection on strong signals needs improvement

### Bug Fixes
- **Fix rotation loop crash** — `ResolutionRecord.pnl` → `ResolutionRecord.total_pnl` in adaptive reflection threshold calculation (`agent.py:763`). Was crashing the rotation loop every ~10s.
- **Suppress stop-loss when BTC favors position** — SL now checks if BTC direction still supports the bet before triggering. Prevents cutting winning positions on orderbook noise (e.g., UP token dips but BTC is still above open).
- **Demote Chainlink WS to cross-reference only** — Chainlink WS was too unreliable as primary price source (80 disconnects, 179 connection errors, HTTP 429 rate limits in one session). Caused 3/13 winner mismatches from mixed Chainlink/Binance prices. Now: Binance is always the primary price source (consistent open-to-close), Chainlink WS is kept only for divergence display and resolution verification where it already works well. Candle history (200 candles for indicators) now uses Binance exclusively.
- **Fix adaptive entry duplicate recordings** — Added dedup check in `record_outcome()`. The rotation loop crash was causing the same candle to be recorded 38x, flooding the rolling window. Cleaned existing JSONL data.

## [v0.5.0] — 2026-02-27

### Dashboard Overhaul

#### Backend — Data Pipeline Enrichment
- **Screen tracking per trade** (`ai_decision.py`) — Each trade record now includes `screen_passed` field: `null` (no screen/prefilter), `false` (Haiku rejected), `true` (Haiku passed → Sonnet). Enables frontend to show which AI model handled each decision
- **Candle snapshot timelines** (`agent.py`) — Dashboard JSON now includes `candle_snapshots` dict with downsampled per-candle data (every ~10s): winner token prices, BTC move, prefilter pass/fail, indicator values, orderbook state. Powers the heatmap, prefilter ticks, and input data views
- **Archive snapshot enrichment** (`archive.py`) — `_enrich_iteration_summary()` reads candle snapshots from archived `polybot.db` so iteration detail views have full timeline data

#### Frontend — Interactive PnL Chart
- **Hover tooltips with crosshair** — `buildLargePnlChart()` now renders gridlines (horizontal at auto-scaled PnL levels, vertical every N candles), gradient area fill, and interactive hover with vertical/horizontal crosshair lines and a positioned DOM tooltip showing candle number and PnL value
- **Win/loss dot coloring** — Each point on the PnL curve is colored green (win), red (loss), or gray (flat) based on the corresponding resolution
- **Larger chart area** — SVG viewport 900x220 with 70px right margin for value labels, 280px container height

#### Frontend — Consolidated Layout
- **Dense Performance Statistics panel** — Merged Trade Quality, Resolution Stats, Calibration & Intelligence, and Account State into a single full-width panel with a compact multi-column grid layout (4+ columns). Eliminates wasted space from separate 2-column panel boxes
- **Tighter spacing throughout** — Reduced all margins (0.75rem → 0.5rem), gaps (0.75rem → 0.5rem), padding (0.85rem → 0.6rem), and font sizes for a denser, more information-rich layout
- **Active Indicators panel** — Compact tag list showing all enabled pre-filter indicators as color-coded badges

#### Frontend — Enhanced Timeline
- **Prefilter tick marks** — Small colored tick marks along the timeline track showing prefilter activity from snapshot data: green = passed (AI could be called), gray = failed (skipped)
- **AI model badges** — Each trade dot gets a badge above it: "H" (cyan) = Haiku screen only, "S" (purple) = Sonnet decision, "P" (gray) = prefilter skip
- **Winner price heatmap** — For resolved candles, a gradient bar below the timeline shows the winner token's price over time using dynamic per-candle scaling: green (cheapest observed) → yellow (midpoint) → red (most expensive), with price labels

#### Frontend — Trade Detail Enhancements
- **Model info row** — Each expanded trade shows which model handled it: "Haiku screen (rejected)", "Haiku + Sonnet", or "Sonnet (no screen)"
- **Collapsible Input Data section** — "Show Input Data" toggle reveals a grid of the market state at decision time: BTC price, UP midpoint, spread, cash, portfolio value, fee, AI cost
- **SL/TP display in positions panel** — Live session's Open Positions panel now shows dynamic stop-loss and take-profit thresholds with color-coded badges (red for SL, green for TP)

#### Frontend — Layout Fix
- **Replaced grid with flex layout** — `.content-grid`, `.live-row`, `.iv-grid` switched from CSS grid to flexbox so all panels use the full available width instead of being constrained to half-width columns
- **Simplified media queries** — Removed redundant breakpoints since flex layout handles responsiveness natively

### iter_008 Analysis (pre-v0.5.0 code — baseline for AI engineering changes)
- **10.4 hours, 128 candles, 95 traded** — longest session by far. 71.6% win rate, +$97 net after fees
- **Recovered from -$96 max drawdown** in the first 2 hours to finish profitable — system resilience proven
- **Loss magnitude remains #1 problem**: avg loss $22.36 is 2.1x avg win $10.51. 27 losses totaled -$604 vs 68 wins at +$715
- **16/27 losses were mid-candle reversals** where BTC moved $30-80+ at entry but reversed before resolution
- **5 double-entry violations** where the AI bought the same side twice on one candle despite prompt rules — caused -$123 including the session's largest loss (-$52.73)
- **6 losses had Chainlink divergence >$100** — this is a reliable reversal warning that was treated as advisory, not blocking
- **AI acknowledged its own 0W/10L failure pattern** on UP trades and continued buying UP — 3 instances totaling -$57
- **5 late re-entries** after stop-loss at prices >0.85 with <80s remaining — all had R/R <0.15x (pure gambling)
- **Confidence 0.72-0.74 band overconfident**: claimed 73% but actual win rate was 67% — this band contained 47% of all trades
- **v0.5.0 AI engineering changes were NOT active** during iter_008 (committed after bot started). iter_009 will be the first test of all 10 improvements
- **Key improvements identified**: hard Chainlink divergence block, code-enforced single-entry-per-side, post-stop-loss re-entry block, drawdown circuit breaker, corrected $50 threshold accuracy claim

### Added — AI Engineering Improvements (see `docs/AIEngineering.md` for full analysis)
- **BTC trajectory signals (velocity + peak-drawback)** — The AI now sees intra-candle BTC velocity ($/s, accelerating or decelerating) and peak drawback (how far BTC has pulled back from its candle peak). Computed from prefilter snapshots recorded every second. This directly addresses iter_007's #1 failure mode: all 4 losses were on decelerating BTC moves that reversed, but the AI only saw the static position (+$64) without knowing it was exhausting.
- **Haiku screening reason passed to Sonnet** — When the fast screener (Haiku) approves a trade, its reasoning is now injected into Sonnet's context as a "Pre-Screening Note." This gives the decision model a free second opinion and primes it to evaluate the key signal Haiku identified. Previously the screening reason was logged but discarded.
- **ML scorer feature contributions in prompt** — The ML baseline line now shows the top 3 features driving the prediction (e.g., "drivers: btc_vs_open: +0.25, streak_signed: +0.18, reversal_rate: -0.12"). This lets the AI understand WHY the ML predicts a direction, not just the probability, enabling it to agree or disagree with the ML's logic.
- **Adaptive reflection frequency** — Reflection now triggers every 5 resolutions (~25 min) when the bot is losing (recent 5-candle PnL < -$10), instead of the fixed 10-resolution interval (~50 min). This doubles feedback speed during drawdowns while keeping normal pace during profitable periods.

- **Cross-candle microstructure memory** — At each candle rotation, a microstructure summary (avg spreads, BTC intra-candle range) is saved before clearing prefilter history. The AI now sees spread trends (widening/narrowing/stable) and volatility trends (increasing/decreasing) across the last 5 candles. Previously each candle was treated independently with no market microstructure context.
- **Time-weighted stop-loss** — Stop-loss now tightens as the candle nears expiry. With 240s+ left: -60% (configured default). With 120s: ~-40%. With 60s: ~-30%. With 30s: ~-20%. A -40% position with 30 seconds left is almost certainly not recovering — cut it early. Linear interpolation from configured stop at 240s to -20% at 0s.
- **Ensemble disagreement tracking** — Tracks Haiku pass-through rate (what % of screenings reach Sonnet), Sonnet trade rate (what % of Haiku passes result in actual trades), and ML-Sonnet directional agreement rate. Disagreements are logged with both model predictions. All stats exposed to dashboard JSON for monitoring.
- **Prompt token reduction** — Moved static explanations (what Chainlink is, why 24h change isn't predictive, spread advice) from per-cycle feature vector into system prompt. Compacted orderbook, positions, portfolio, and risk sections from verbose multi-line to data-dense single-line formats. ~20-25% token reduction per Sonnet call.

### Added — 8 Soft Safeguards for Better AI Decisions

Based on iter_008 loss analysis (27 losses totaling -$583), implemented 8 safeguards — 7 soft (inject context/warnings into the AI prompt so it makes better decisions) and 1 hard (single-entry-per-side is position discipline, not market-dependent).

1. **Chainlink divergence warning** — When Chainlink diverges >$100 from Binance, a warning block is injected into the AI's indicators text: "resolution source may differ significantly." The AI decides whether to reduce confidence or skip. Previously, 6/27 losses had divergence >$100 with no warning surfaced.

2. **Single-entry-per-side enforcement** (code-level) — Prevents buying the same side twice on the same candle. Tracks `_bought_sides` per slug, overrides duplicate BUY to HOLD. The system prompt already said "do NOT buy more of the same token" but iter_008 showed 5 violations causing -$123 including the largest single loss (-$52.73). This is the ONE code-level enforcement.

3. **Post-stop-loss cooldown signal** — After a stop-loss exit fires, a warning is injected into the next AI call on the same candle: "Re-entering immediately is high-risk — the price moved against you and may continue." Stored in `SharedState.last_stop_loss`, cleared on candle rotation. iter_008 had 5 post-stop-loss re-entries that all lost.

4. **Corrected $50 threshold accuracy** — Fixed `trading_patterns.md`: the $50-$100 BTC move accuracy was listed as ~90% (from a smaller sample) but iter_008's 128 candles showed ~65-70%. Updated the table and added a caveat about accuracy varying by market conditions.

5. **Drawdown awareness in prompt** — When the last 10 resolutions have net PnL < -$5, a "SESSION DRAWDOWN ALERT" is injected into the feedback context. The AI can adjust sizing and selectivity during losing streaks rather than trading blind to cumulative losses.

6. **Counter-trend accuracy context** — When a strong market trend is detected (score >= 0.3), a "Counter-Trend Advisory" is injected before the AI call: "Historical counter-trend accuracy: ~55-60% (vs ~75% trend-aligned)." Previously the counter-trend sizing reduction existed but the AI didn't know *why* or the accuracy differential.

7. **Calibration overconfidence warnings** — Enhanced `get_calibration_summary()` to flag bins where actual win rate is below the stated confidence range: "OVERCONFIDENT — actual 67% win rate but you state 70%-80% confidence (23W/11L from 34 trades)." iter_008 showed the 0.72-0.74 band claimed 73% but actually won 67%.

8. **Per-side failure pattern surfacing** — Enhanced `build_feedback_context()` with: (a) side-specific accuracy warnings when UP or DOWN win rate < 50% over 3+ trades, (b) losing streak detection (3+ consecutive losses trigger "Increase selectivity" warning). iter_008 showed the AI acknowledged its own 0W/10L UP failure pattern and continued buying UP.

### Added — Adaptive Dynamic Stop-Loss & Take-Profit

The fixed -60% SL was too wide (let losing positions bleed) while the previous -15% SL was too tight (stopped winners prematurely). iter_008 showed avg loss $22.36 — 2.1x avg win $10.51, with 16/27 losses being mid-candle reversals. The right threshold depends on market conditions.

**Dynamic Stop-Loss** — Computed every second from 5 additive factors on top of the existing time-weighted base:

1. **Time weighting** (existing, preserved as base) — Tightens from -60% at 240s to -20% at 0s
2. **Regime** (from reversal rate) — Momentum (rr<0.35): tighten up to +12% (drawdowns are real signals). Choppy (rr>0.55): widen up to -8% (whipsaws may recover)
3. **BTC velocity** (real-time from prefilter history) — BTC accelerating against position: tighten up to +8%. In favor: widen up to -6%
4. **ML alignment at entry** — ML agreed with position: widen -4% (give room). ML disagreed: tighten +5% (less room for error)
5. **Entry price quality** — Expensive entries (>=$0.75): tighten +6%. Cheap entries (<=$0.40): widen -5%

Combined with configurable floor/ceiling: never wider than -75%, never tighter than -15%.

**Dynamic Take-Profit** — Time-weighted base with 3 adjustments:

1. **Regime** — Momentum: +10% (let winners run). Choppy: -15% (take profits early)
2. **BTC velocity** — Accelerating in favor: raise TP up to +10%. Turning against: lower TP up to -10%
3. **Entry price** — Expensive (>$0.70): lower TP -15%. Cheap (<$0.40): raise TP +10%

Floor/ceiling: never below +20%, never above +120%.

**New config parameters** (`config/default.yaml`):
- `dynamic_sl_enabled` / `dynamic_tp_enabled` — feature flags (default: true)
- `sl_floor` / `sl_ceiling` — SL bounds (-0.75 / -0.15)
- `tp_floor` / `tp_ceiling` — TP bounds (0.20 / 1.20)

**Data flow**:
- `EntryContext` dataclass stores ML prediction, entry price, BTC move, reversal rate at fill time
- Stored on BUY fill, cleared on SELL fill and candle rotation
- Reversal rate, signal type, regime synced from AdaptiveEntryTracker every 2s
- Dynamic SL/TP values written to SharedState for dashboard display

**Fallback**: When `dynamic_sl_enabled: false`, falls back to existing time-weighted-only logic. When signals are unavailable (no reversal data, no prefilter history, no entry context), the corresponding adjustment is 0.

### Changed
- `SharedState` now includes `last_stop_loss` field for post-stop-loss cooldown tracking, plus `EntryContext` dataclass and fields: `entry_context`, `reversal_rate`, `signal_type`, `regime`, `dynamic_sl`, `dynamic_tp`
- `_handle_market_transition()` clears `last_stop_loss`, `entry_context`, `dynamic_sl`, `dynamic_tp` on candle rotation
- `MonitorConfig` gains 6 new fields for dynamic SL/TP configuration
- `PositionMonitor._dynamic_stop_loss()` now takes `token_side` parameter and uses 5-factor adaptive formula
- `PositionMonitor._check_thresholds()` uses both dynamic SL and dynamic TP
- Dashboard JSON includes `dynamic_sl` and `dynamic_tp` sections
- SL/TP trigger log messages include component breakdown (time, regime, velocity, entry price, ML)
- **Calibration bins widened from 5% to 10%** — With 5%-wide bins, the calibrator needed ~75+ trades to populate any single bin (MIN_SAMPLES=15). Most bins had 1-5 samples after 7 iterations and zero reliable calibration. Changed to 10%-wide bins with MIN_SAMPLES=10 — reaches reliability ~3x faster. Trade-off: lower resolution (can't distinguish 0.62 from 0.67), but the AI doesn't have that precision anyway.
- **Temperature raised from 0.0 to 0.1** — Mild exploration for the decision model (Sonnet). Introduces slight variety in reasoning paths without compromising coherence. Screening (Haiku) stays at 0.0 for deterministic filtering. Avoids systematic biases from always picking the same highest-probability output.

## [v0.4.1] — 2026-02-26

### Added
- **Contrarian trading via reversal rate context** — When the rolling reversal rate exceeds 55%, the AI now receives a "Reversal Rate Context" section showing the actual rate (e.g., "80% — 8 of last 10 candles reversed"), signal type (CONTRARIAN/MOMENTUM/UNCERTAIN), and the average winner ask price during reversals. This lets the AI decide to bet against the initial BTC direction when reversals are predictable, instead of blindly following momentum. Both the Haiku screener and Sonnet decision maker see this context.
- **V-shaped BTC threshold** — The adaptive entry threshold now peaks at 50% reversal rate ($50, maximum uncertainty) and drops at both extremes: low reversal ($20, reliable momentum) and high reversal ($20-32, predictable reversals = contrarian edge). Formula: `50 - abs(rate - 0.5) × 60`, clamped to [$20, $50]. Previously it was monotonically increasing, blocking all trades during high-reversal markets instead of exploiting the pattern.
- **Signal type indicator** — Dashboard shows MOMENTUM (<35% reversal), UNCERTAIN (35-55%), or CONTRARIAN (>55%) badge alongside the existing regime label. Logged in adaptive entry updates for tracking.
- **ML scorer: reversal rate feature** — Added `reversal_rate` as the 10th feature to the online logistic regression model. This lets the ML baseline learn the interaction between BTC direction and reversal rate (e.g., high reversal + positive BTC = DOWN wins). Model auto-resets on feature count change and retrains within ~10 candles.
- **Binance bootstrap for adaptive entry** — On startup, if the adaptive entry has fewer than `window` (10) candles of history, it fetches recent 1-min klines from Binance and reconstructs the reversal pattern for the last 10 five-minute periods. This gives the bot a warm reversal rate from the first candle instead of running blind for ~50 minutes. Real Polymarket observations naturally replace the bootstrapped data as the session progresses.

### Fixed
- **YAML config override: `adaptive_entry_window` was stuck at 5** — `config/default.yaml` had `adaptive_entry_window: 5` which overrode the Python default of 10. With window=5, only 6 discrete reversal rates are possible (0/20/40/60/80/100%), causing wild jumps. Fixed to 10 in YAML.
- **PreFilter: raised `no_streak_max_entry` from $0.40 → $0.50** — The $0.40 threshold blocked nearly all streak=1 entries (47% of candles), since ask prices typically sit at $0.44-0.55. Entries at $0.40-0.50 have ~56% win rate — profitable territory the AI should evaluate. The $0.50 threshold aligns with the R/R break-even boundary.
- **Screening prompt updated for contrarian setups** — Haiku screener no longer rejects trades purely because BTC has moved in one direction. High reversal rate is now a valid trade signal (contrarian opportunity), not just a momentum signal.
- **Dashboard: negative value formatting** — All PnL/loss values now display as `-$72.53` instead of `$-72.53`. Fixed `fmt$` helper and `pnlSign` to consistently show the minus before the dollar sign across sidebar, candle timeline, resolution table, and portfolio deltas.

## [v0.4.0] — 2026-02-26

### Added
- **Market data analysis → AI knowledge base** — Deep statistical analysis across 159 candles and 16K snapshots (4 iterations) loaded into `data/knowledge/trading_patterns.md` as soft guidance for the AI. Key findings: $50+ BTC moves have ~90% directional accuracy vs ~54% for <$20; two EV peaks at 30-45s and 120-165s with dead zone at 60-105s; cheap entries (R/R 1.5-3.0) are contrarian traps winning only ~29%; streaks of 3+ continue ~62%; orderbook imbalance >70% predicts at ~80%. All framed as observations and tendencies, not absolute rules.
- **Updated self_assessment.md** — Replaced rigid absolute rules with data-backed considerations. Removed hard entry price caps and strategy mandates, replaced with calibration awareness and bias warnings.

### Changed
- **R/R position sizing flattened** — Old curve: 0.20x-1.0x scale (cheap entries got full size, expensive entries got 20%). New curve: 0.75x-1.0x (gentle nudge only). Data showed expensive entries (R/R <0.5) win ~85% while cheap entries (R/R 1.5-3.0) win only ~29% — the old system was sizing up on losers and sizing down on winners. BTC move magnitude and trend remain the primary sizing drivers.

### Added
- **Polymarket outage detection and recovery** — The bot now detects when the Gamma API becomes unavailable (3+ consecutive discovery failures). During an outage: logs structured warnings with duration/failure count, pauses trading (no stale market data used), and reports outage status to the dashboard. On recovery: skips resolution of missed candles (stale token IDs would be wrong), cancels any pre-outage orders, and cleanly resumes with the next live market. In iter_006, the Polymarket API went down for ~13 minutes (129 failures) — the bot kept running but couldn't trade. This feature ensures it handles that gracefully.
- **Dashboard outage banner** — A prominent banner appears at the top of the dashboard during outages (red, blinking) showing "Polymarket markets unavailable" with elapsed time. When markets recover, a green banner briefly shows "Markets recovered after Xm Ys". Auto-hides after 60 seconds.

### Fixed
- **Chainlink WS staleness watchdog** — The WebSocket connection would silently die without triggering the reconnect loop. In iter_006, this caused a 2-hour gap (16:49→18:49) where the WS hung on `async for raw_msg` with no data flowing, producing only 2 candles in 2.5 hours. Fix: a watchdog task checks every 10s if no message has arrived in 30s, and force-closes the connection so the reconnect loop fires immediately. Expected result: continuous Chainlink data instead of 2-hour dead zones.
- **Dashboard iteration detail view crash** — The `buildDeepAnalysisSection` function crashed on iterations with different deep_analysis field names (e.g., `avg_win` vs `avg_winning_trade`), causing the entire iteration view to show "No trades yet". Fix: wrapped in try-catch with field name fallbacks, added support for iter_006+ analysis format (what_went_well/wrong, fixes_verified sections).

## [v0.3.0] — 2026-02-26

### Fixed
- **Chainlink WS message parsing** — The RTDS sends batches in `payload.data[]` format with per-second `{timestamp, value}` ticks. The original parser looked for `data.value` / `data.price` (wrong nesting), so zero ticks were ever extracted. Fixed to parse the actual format and process all ticks in each batch for accurate candle OHLC. Also handles empty keepalive frames and logs first messages per connection for debugging.
- **Force token_side on exit SELL decisions** — The AI could return the wrong `token_side` in its SELL response for exit triggers (e.g., exit signal says "sell DOWN" but AI responds with `token_side: "up"`). This caused `sold_sides` to track the wrong side, letting the anti-flip guard miss the side-flip on candle 1772124000 (-$49.03). Fix: force `token_side` from the exit signal, never trust the AI output for exits.
- **Counter-trend min size floor** — The 40-share minimum position floor was completely negating counter-trend sizing reductions. In iter_005, counter-trend scaling reduced sizes to 5-24 shares but the floor put them all back to 40. Fix: use 20-share floor for counter-trend trades so the size reduction actually takes effect (50% of normal floor).

## [v0.2.0] — 2026-02-26

### Added
- **Chainlink WS candle builder** — 5-min OHLCV candles are now aggregated directly from Chainlink WebSocket ticks (`_record_tick()` / `_finalize_bucket()` in `chainlink_ws.py`). Each completed 5-min bucket produces a `BtcCandle(source="chainlink_ws")` with open/high/low/close from real ticks and tick count as proxy volume. Up to 200 completed candles are retained.
- **Merged candle history** — `BtcPriceFeed.candles` now merges Chainlink WS candles on top of Binance backfill. When both sources have a candle for the same 5-min bucket, the Chainlink version wins (matches resolution source). Binance klines remain for startup backfill (~200 historical candles). After ~4 hours of running, all 200 candles are Chainlink-sourced.
- **`BtcCandle.source` field** — New field (`"binance"` default, `"chainlink_ws"` for WS-built candles) tracks candle provenance. All 8+ candle-based indicators (streak, momentum, EMA, volume trend, etc.) transparently consume merged candles with no code changes.
- **Dashboard: Candle source count** — BTC Price panel now shows "Candles: X chainlink / Y binance" so operators can see the Chainlink candle count grow over time toward full alignment.
- **Hybrid Chainlink RTDS WebSocket + Binance BTC price feed** — The bot now connects to Polymarket's RTDS WebSocket (`wss://ws-live-data.polymarket.com`, topic `crypto_prices_chainlink`, symbol `btc/usd`) to receive the exact Chainlink BTC/USD price used for candle resolution. When the WebSocket is active, this becomes the primary price source — eliminating the Binance-vs-Chainlink divergence that caused ~$82/iteration in losses from correct predictions resolving against the bot. Binance remains the fallback (auto-switches within seconds if the WebSocket disconnects or goes stale >30s). Binance klines still used for 5-min candle history (EMA indicators — only relative movement matters). No authentication required.
- **`ChainlinkWSFeed`** class (`src/polybot/market_data/chainlink_ws.py`) — Async WebSocket client with auto-reconnect (5s retry), keepalive pings (5s), 30s staleness check, and clean start/stop lifecycle. Properties: `price` (None if stale), `is_active` (connected + fresh data), `last_update` timestamp.
- **`BtcPrice.price_source`** field — Tracks which source provided the current price: `"chainlink_ws"`, `"binance"`, or `"coingecko"`. Flows through to indicators and dashboard.
- **`ApiConfig.polymarket_rtds_url`** — Configurable RTDS WebSocket URL (default `wss://ws-live-data.polymarket.com`).
- **Dashboard: Price source badge** — Green "CHAINLINK WS" or amber "BINANCE" badge next to BTC Price panel header showing the active price source.
- **Anti-flip guard** — Blocks buying the opposite side after a SELL on the same candle. Prevents the whipsaw pattern where the bot sells a correct position mid-candle, flips to the opposite side, and loses on both. Same-side re-entry (adding back) is still allowed. In iter_004, two whipsaw candles cost -$104.45 combined; both would have been profitable (+$36.80) if the bot held the first trade. Estimated impact: +$80/iteration.
- **Archive: auto-rebuild iterations.json** — The archive CLI now regenerates `logs/iterations.json` after archiving, ensuring the dashboard immediately shows the new iteration without needing to restart the bot. Previously, iterations.json was only written by the running agent, so newly archived iterations wouldn't appear until next bot startup.

### Changed
- **All indicators now use resolution-source data** — Streak counts, candle momentum, EMA crossovers, and the AI prompt all reflect Chainlink candle direction when available, eliminating the $20-30 divergence that could flip candle direction between Binance and Chainlink.
- **`BtcPriceFeed.get_price()` hybrid priority** — Chainlink WS (if active) → Binance → CoinGecko → stale cache. When on Chainlink WS, the expensive Ethereum RPC call to read the on-chain Chainlink aggregator is skipped entirely. Cross-reference divergence is still computed but is informational only (Binance vs Chainlink WS).
- **Chainlink divergence indicator** — When `price_source == "chainlink_ws"`, the indicator shows "ALIGNED — using Chainlink WS" with no resolution risk warning. Divergence value still computed (Binance vs Chainlink) for monitoring. When on Binance, existing behavior preserved (resolution risk warnings).
- **Agent lifecycle** — `ChainlinkWSFeed` is started before the main task loop and stopped during shutdown. WebSocket runs as a background asyncio task alongside the existing 6 tasks.

### Fixed
- **Adaptive entry: window 5→10** — Window of 5 only had 6 discrete reversal rates (0/20/40/60/80/100%), making CALM trigger with just 1 non-reversal candle. In iter_005's 43% reversal market, window=5 showed CALM 29% of the time (wrong). Window=10 gives 11 discrete levels (0%/10%/20%/…/100%) — smooth enough to avoid wild regime jumps while still adapting to recent conditions.
- **Adaptive entry: continuous threshold** — Replaced discrete $20/$30/$40 jumps with continuous formula: `threshold = 20 + reversal_rate × 50`, clamped to [$20, $50]. Eliminates unstable regime flipping at sharp cutoff boundaries. At 40% reversals → $40 threshold (same as before), but now smoothly adapts between values.
- **Adaptive entry: archive + clean on iteration reset** — `adaptive_entry.jsonl` is now included in the archive file list and cleaned after archiving, ensuring each new iteration starts fresh without stale market regime data.
- **Dashboard: regime labels from continuous rate** — CALM (<20%), MODERATE (20–40%), CHOPPY (≥40%) now derived from reversal rate directly. Dashboard shows server-computed regime label with matching color thresholds.
- **Block mid-position AI calls via prefilter** — Previously, the prefilter bypassed all checks when the bot had an open position (`has_open_position → always pass`), allowing MarketMonitor to trigger Claude every 60s while positioned. Claude would then invent its own exit rules (e.g., "down >15% with <90s = EXIT NOW") and sell at much tighter thresholds than the system's -60% stop-loss. This caused premature exits on positions that ultimately won — the iter_004 weird loss on candle 1772049300 (-$11.69) was a DOWN buy where DOWN won, but Claude panic-sold at $0.46 mid-candle. Fix: prefilter now **skips** AI when positioned, letting PositionMonitor handle all exits at the configured -60%/-80% thresholds. Estimated impact: +$20-30/iteration from avoided premature exits.

## [v0.1.0] — 2026-02-26

### Added
- **Dashboard: Deep Analysis Section** — Each iteration detail view now includes a full deep analysis panel when data is available. Shows: profit factor + summary stats banner, loss classifications with horizontal bars (Multi-Trade Candle, Chainlink Divergence, Counter-Trend, Reversal), entry price ROI buckets (cheap entries vs expensive with ROI%), confidence calibration with actual win rates and UNDERCONFIDENT/OVERCONFIDENT/CALIBRATED labels, UP vs DOWN side performance comparison, entry timing buckets, investigated "weird losses" (correct predictions that lost money with root cause analysis), and ranked actionable improvements with impact estimates and LOSS FIX/WIN BOOST badges.
- **Standardized Analysis Process** — `docs/ANALYSIS_PROCESS.md` documenting the 6-phase post-iteration analysis methodology: summary overview, deep loss analysis (classification taxonomy), deep winner analysis (7 sub-analyses), actionable recommendations with priority matrix, dashboard update, and cross-iteration trend tracking. Includes checklist for consistency across iterations.
- **Deep analysis data in iterations.json** — iter_004 now includes `deep_analysis` object with: summary stats (profit factor 2.33x), loss classifications (4 categories totaling -$226.84), entry price buckets (101% ROI on <$0.55 entries vs 8.9% on >$0.70), confidence calibration (0.68 conf wins at 82% — 14pt underestimation), side analysis, timing analysis, exit quality assessment, weird loss investigations, and 5 ranked actionable fixes totaling ~$298/iter potential improvement.
- **Market Trend Indicator** (`market_trend` in `indicators.py`) — EMA20/EMA50-based regime detection on 5-min BTC candle closes. Produces a composite trend score (-1 to +1) from three components: EMA crossover signal (40%), price vs EMA50 (35%), and recent candle direction ratio (25%). Labels: STRONG BULLISH / BULLISH / NEUTRAL / BEARISH / STRONG BEARISH.
- **Counter-Trend Position Size Reduction** — When the bot buys against the prevailing trend (e.g., DOWN in a bullish regime), position size is automatically reduced: 30% reduction for moderate counter-trend (score 0.3-0.7), 50% reduction for strong counter-trend (score >= 0.7). This addresses the #1 PnL drag across all iterations (-$12.66 iter_001, -$7.57 iter_002, -$52.56 iter_003).
- **Market Trend in Claude's Prompt** — New "Market Trend" section in the AI decision prompt showing EMA20 vs EMA50, price position relative to EMA50, composite trend score, and counter-trend size reduction warnings.
- **Dashboard: Market Trend Badge** — Adaptive Entry panel now shows a color-coded trend badge (green=bullish, amber=neutral, red=bearish) with the trend score when sufficient candle history (50+) is available.
- **EMA Helper** (`_ema()` in `indicators.py`) — Reusable exponential moving average function for any period, seeded from the first value in the window.
- **Dashboard: Dedicated Iteration Analysis View** — Each archived iteration now has its own full-page analysis view accessible from the sidebar. Clicking an iteration opens a comprehensive breakdown with: header bar (label, date range, net result badge, prev/next navigation), 6 key metric cards (win rate, total PnL, net result, trades, AI cost, candles — all with deltas from previous iteration), full-width cumulative PnL curve, trade quality panel (entry price distribution bar, avg fill/confidence/hold rate, buy/sell/hold counts), resolution stats panel (avg BTC move, avg win/loss PnL, biggest win/loss, risk/reward ratio), calibration & intelligence panel (shadow accuracy, good exit rate, exit value saved/missed, confidence calibration bar chart), AI observations cards (category-badged: edge/pattern/bias with timestamps), session history table (parsed from markdown), and scrollable resolutions detail table (per-candle slug, resolution, BTC move, PnL — color-coded win/loss rows).
- **Sidebar: Iterations section** — New "Iterations" section at the bottom of the sidebar listing all archived iterations (newest first) with net result and win rate. Click to navigate to the iteration's dedicated analysis page.
- **Backend: Enriched iteration data** — `_enrich_iteration_summary()` now includes `observations` (AI learnings from observations.jsonl), `session_history` (markdown session summaries), and `resolutions_detail` (per-candle resolution outcomes with slug, PnL, BTC move, and resolution direction).
- **Dashboard: Changes from Previous Iteration panel** — Each iteration detail view now shows a "Changes from [prev_label]" section comparing 18 metrics side-by-side: win rate, net result, total PnL, avg win/loss, biggest win/loss, risk/reward ratio, avg fill price, hold rate, AI cost, fees, candles, trades, avg BTC move, shadow accuracy, good exit rate, and exit value saved. Each metric shows previous→current values with color-coded delta badges (green=improved, red=regressed, purple=neutral).

### Fixed
- **PENDING candle bug** — Early candle resolutions were missing from dashboard data because `_session_resolutions` was previously capped at 20. The fix (uncapped list) was already in place but the stale `dashboard_data.json` on disk still had the gap. Added slug-based deduplication when merging historical + session resolutions as a safety net against future data gaps.

### Removed
- **Iteration Analysis panel from Overview** — The horizontal scrolling iteration cards at the bottom of the Overview are replaced by the dedicated iteration analysis view in the sidebar.

- **Dashboard: Iteration History panel** — Full-width comparison table showing all archived iterations side-by-side. Displays label, date range, candles, win rate, PnL, fees, AI cost, and net result with color-coded deltas from the previous iteration (green = improvement, red = regression). Only appears when `archive/*/summary.json` files exist.
- **Dashboard: Adaptive Entry panel** — Half-width panel showing live adaptive threshold state: BTC move threshold ($20/$30/$40), max entry price, reversal rate, and rolling window size. Color-coded regime badge (CALM/MODERATE/CHOPPY) based on current reversal rate. Shows "using defaults" when insufficient history. Entire panel dims with DISABLED overlay when adaptive entry is turned off.
- **Dashboard: Enhanced candle timelines** — Four visual additions to each candle timeline row: (1) Regime color bar — thin 3px bar below the timeline showing current BTC threshold regime (green/amber/red). (2) BTC move label — shows `+$47` or `-$23` at the endpoint dot, colored by direction. (3) Entry price labels — BUY dots show fill price (`$0.42`) below the dot stem. (4) Win/loss row tinting — subtle green/red left border on resolved candle rows for scannable results.
- **Backend: `adaptive_entry` section in dashboard JSON** — Exposes `btc_threshold`, `max_entry_price`, `reversal_rate`, `has_enough_history`, `window_size`, and `history_count` from `AdaptiveEntryTracker`.
- **Backend: `iterations` section in dashboard JSON** — Loads all `archive/*/summary.json` files on startup and includes them in the dashboard data for the iteration comparison table.

### Fixed
- **Dashboard resolutions evicted after 20** — `_recent_resolutions` was capped at 20 items (intended for reflection context window) but was also used to build the dashboard `resolutions` array. After 20 resolutions in a session: early candles lost their WIN/LOSS badge (showed FLAT), their PnL disappeared from all-time totals, and archived dashboard data was corrupted. Fixed by adding a separate uncapped `_session_resolutions` list for the dashboard writer, keeping the 20-item cap only for the reflection system. This was the root cause of iter_002 showing $0 PnL despite having profitable trades.
- **Archive summary used wrong PnL/win-rate source** — `_compute_summary()` in `archive.py` used `_compute_stats()` which derived `total_pnl` from the last trade record's `realized_pnl + unrealized_pnl` (stale/wrong) and `win_rate` from SELL trade counts (not resolution outcomes). Fixed to use the resolutions JSONL as the source of truth for PnL, wins, losses, and win rate. Fees and AI cost still come from trade records. Regenerated iter_001 and iter_002 summaries: iter_002 was actually +$51.67 net (82.6% WR), not -$6.67 (50% WR).

### Added
- **Adaptive entry threshold tracker** (`adaptive_entry.py`) — Learns the optimal BTC move threshold ($20/$30/$40) and max entry price from rolling candle history. Uses reversal rate from the last N candles (configurable, default 5) to calibrate when to trigger AI: calm markets (reversal rate < 25%) trust early $20 BTC signals, moderate markets (< 45%) wait for $30, choppy markets (>= 45%) require $40 confirmation. Max entry price caps at the rolling average winner ask + $0.10 (capped at $0.65) to avoid overpaying vs recent winners. Falls back to conservative defaults ($30 threshold, $0.60 max entry) until enough history accumulates. Persisted to `logs/adaptive_entry.jsonl` for cross-session continuity. Feature-flagged via `monitor.adaptive_entry_enabled` (default true); when disabled, falls back to static R/R threshold.

### Changed
- **Adaptive AI trigger replaces static R/R gate** — MarketMonitor now uses `AdaptiveEntryTracker.should_trigger(abs_btc_move, min_ask)` instead of the static `best_rr >= rr_trigger_threshold` check. The prefilter still runs first (time, spread, depth, choppy, setup checks unchanged). AI cooldown is unchanged. Trigger logs now show adaptive thresholds: `AI triggered: adaptive btc_thresh=$20, max_entry=$0.58`.
- **Wider SL/TP thresholds** — Stop-loss widened from -35% to -60%, take-profit from +50% to +80%. Analysis showed $60.92 lost to premature exits where 9/10 sells were on winning positions.
- **Guard winning exits near expiry** — If position is profitable AND BTC direction matches position side AND < 120s remaining, skip the exit trigger and let it ride to resolution. Prevents selling winners right before they pay out.
- **Minimum position size = 40 shares** — Enforced after R/R × move scaling, before risk manager caps. Previous avg was 9 shares — too small to capture meaningful edge.
- **Removed overconfidence size cap** — Deleted the 30% size reduction when confidence >= 0.70 AND fill > $0.65. Data showed this was cutting winning trades.
- **Raised move-magnitude scaling floors** — Small moves (<$10) now 80% (was 60%), medium (<$30) now 90% (was 80%), large (<$60) now 100% (was 90%). Reduces missed profit from undersized positions.
- **Tighter Haiku screening** — Entry attractiveness threshold lowered to ask < $0.30 (was $0.35). Added explicit "$0 BTC move is NEVER a trade setup" rule. Added: BTC move < $15 AND no streak AND time < 120s = always false. Targets 50%+ screening rate (was 26%).
- **Stop force-triggering AI when positioned** — Removed `force_trigger = has_position and prefilter_passed` from MarketMonitor. Exit triggers from PositionMonitor's queue still work. Saves 5-10 wasted HOLD calls per positioned candle.
- **Lower BTC move description thresholds** — FLAT < $5, SMALL $5-15, MODERATE $15-30, STRONG $30+ (was $5/$20/$50). Matches the actual signal quality observed in data.

### Added
- **Persistent market history database** (`data/market_history.db`) — A separate SQLite database that accumulates pure market data (candle outcomes + per-second orderbook snapshots) across all iterations. Never deleted by `polybot-archive`. Each candle is tagged with an iteration label. Two tables: `market_candles` (condition_id, slug, iteration, BTC open/close, winner) and `market_snapshots` (full UP+DOWN orderbook, R/R, BTC price, BTC move, streak). Enables statistical validation of trading assumptions with hundreds of candles instead of guessing.
- **`MarketHistoryStore`** class in `datastore.py` — Same async queue + batched writer pattern as `DataStore`, but stores only market observables (no decisions, portfolio, or session-specific data). Runs as its own async task alongside the session DataStore.
- **`polybot-validate` CLI** — Queries `data/market_history.db` to validate trading assumptions with Rich tables. Five reports: momentum continuation (% where mid-candle BTC direction = final winner, by move × time bucket), reversal rates (inverse), optimal entry timing (avg winner ask price by time bucket), BTC move distribution (percentiles), and summary header. Supports `--report`, `--min-candles`, and `--db` flags. Low-sample cells are dimmed.
- **`logging.market_history_db_path`** config field — Path to persistent market history database (default `data/market_history.db`).

### Changed
- **Softened reversal prompt** — Removed hardcoded percentages ("~97% continuation", "NEVER reversed") from the system prompt's Mid-Candle Signal Reliability section. Replaced with directional guidance ("tend to continue", "larger moves are more reliable") and a pointer to `polybot-validate` for current data-backed rates. Prevents wrong assumptions from being baked into the prompt.
- **Archive cleanup excludes market history** — `polybot-archive` cleanup only touches `logs/` and AI-written knowledge files. `data/market_history.db` is explicitly excluded with a code comment confirming it's intentional.

### Changed
- **Anti-hedging guard** — Blocks BUY on one side when holding shares on the opposite side. Prevents both-side bets that averaged -$2.85 per hedge in prior run. Overrides to HOLD with logged reason.
- **Position sizing ~3x increase** — Flattened R/R scaling curve (R/R 1.0 now 80% vs old 50%, R/R 0.5 now 55% vs old 25%, minimum 20% vs old 10%). Move-magnitude floors raised (small moves 60% vs 40%, medium 80% vs 60%). `max_position_pct` increased from 25% to 40%. Average position should rise from ~$7.82 to ~$20-25.
- **Wider SL/TP thresholds** — Stop-loss widened from -15% to -35%, take-profit from +30% to +50%. Prevents premature exits on positions that ultimately win.
- **Reversal awareness in AI prompt** — New "CRITICAL: Mid-Candle Reversal Risk" section warns AI that ~35-40% of mid-candle moves reverse. Caps confidence at 0.55-0.62 for $30-80 moves. Reserves 0.70+ for large sustained moves with <120s remaining.
- **AI cooldown increased 45s → 60s** — Reduces AI calls per candle. Combined with exit trigger cooldown and aggressive screening, targets ~50% reduction in AI spend.
- **Exit trigger cooldown** — SL/TP exit triggers now respect AI cooldown. Non-emergency exits (PnL > -30%) skip AI call when on cooldown. True emergencies (PnL ≤ -30%) bypass cooldown.
- **Haiku screening recalibrated from data** — BTC move threshold lowered from $40 to $20 based on SQLite analysis: moves >$20 have 96.8% momentum continuation rate, >$50 is 100%. The $40 threshold was blocking the $20-50 range where entries are cheaper and signals are already 97%+ reliable. Entry price threshold relaxed to $0.40. "When in doubt, say false" preserved.
- **Reversal risk prompt corrected from data** — Replaced speculative "35-40% reversal rate" with actual observed data: 3.2% reversal rate, only in $20-30 range. Moves >$50 have never reversed. Prompt now encourages acting on $20+ moves instead of waiting for $100+.
- **Overconfidence size cap** — When confidence ≥ 0.70 AND estimated fill > $0.65, position size reduced by 30%. The 0.70+ confidence bin had the worst win rate (57.7%) in prior run.

### Added
- **Iteration archive & comparison tools** — Two new CLI commands for managing iteration snapshots:
  - `polybot-archive` — Copies all generated artifacts (trade logs, resolutions, SQLite DB, AI-written knowledge, feature config) into `archive/<label>/`, computes a `summary.json` with key metrics (date range, candles, trades, win rate, PnL, fees, AI cost, net result, enabled indicators), and cleans working directories for a fresh start. Supports `--name` for custom labels and `--no-clean` to skip cleanup.
  - `polybot-compare` — Scans all `archive/*/summary.json` files and prints a Rich table comparing iterations side-by-side with color-coded deltas from previous iteration (win rate, PnL, net result).
- **SQLite analytics layer** — Per-second market replay and decision analysis. Three tables (`candles`, `snapshots`, `decisions`) persist every tick of orderbook state, computed indicators, AI decisions, and resolution outcomes. Queryable via standard SQL with `json_extract()` for indicator values.
  - `candles` — 1 row per 5-min candle (slug, BTC open/close, winner, PnL)
  - `snapshots` — ~300 rows per candle (1/sec: full UP+DOWN orderbook, R/R ratios, BTC price, prefilter result, streak, all computed indicators as JSON)
  - `decisions` — 1-5 rows per candle (AI action, confidence, reasoning, fill price/size, risk state, portfolio state, indicators as JSON)
- **`src/polybot/datastore.py`** — `DataStore` class with non-blocking `asyncio.Queue` and batched background writer (6th async task). Flushes every 5s or 50 rows via `executemany()` in WAL mode (~10ms for 60 rows). Zero impact on trading latency (<1ms queue overhead).
- **`logging.sqlite_db_path`** config field — Path to SQLite database (default `logs/polybot.db`)
- **`SharedState.session_wins/session_losses`** — Session resolution stats synced from agent, enabling indicator computation in MarketMonitor snapshots
- **Per-second indicator computation in MarketMonitor** — All enabled indicators are computed every tick and stored in `snapshots.indicators_json`, not just at AI decision time. Previously indicators were computed and discarded; now every second of indicator history is queryable.

### Changed
- **Multi-task concurrent architecture** — Replaced the monolithic single-loop `_run_cycle()` with 5 concurrent `asyncio.Task`s running in the same event loop:
  - **MarketMonitor** (1s loop) — fetches market data, runs prefilter checks 1-5, records `PreFilterSnapshot` every second, triggers AI when R/R >= 1.0 and prefilter passes
  - **AIDecision** (event-driven) — waits for entry triggers from MarketMonitor or exit triggers from PositionMonitor, runs the full AI decision pipeline (feature vector, indicators, ML, two-pass screening, confidence/calibration gates, position sizing, execution)
  - **PositionMonitor** (1s loop) — marks positions to market, computes real-time P&L %, triggers exit evaluation at stop-loss (-15%) or take-profit (+30%)
  - **RotationLoop** (5s loop) — discovers markets, handles candle transitions and resolution
  - **DashboardLoop** (2s loop) — writes dashboard JSON from shared state
- **R/R hard block removed** — The R/R gate in both the prefilter (Check 6) and risk manager `post_trade_checks` has been removed. All entries are now allowed; position size scales with R/R quality instead of blocking:
  - R/R >= 2.0 (entry <= $0.33): 100% size
  - R/R 1.0 (entry $0.50): 50% size
  - R/R 0.5 (entry $0.67): 25% size
  - R/R < 0.3 (entry > $0.77): 10% size (tiny position)
- **AI cooldown** — Minimum 45 seconds between AI calls (configurable via `monitor.ai_cooldown_seconds`), preventing over-trading while still allowing rapid response to market changes
- **BTC price cache TTL reduced from 30s to 2s** — Configurable via `monitor.btc_price_cache_ttl`. Enables the 1-second market monitor loop to see near-real-time BTC prices
- **System prompt updated** — R/R discipline section now describes the sliding scale instead of the hard block

### Added
- **`src/polybot/shared_state.py`** — Central coordination hub (`SharedState` class) for concurrent tasks. Contains `PreFilterSnapshot` dataclass for per-second market state recording, `asyncio.Event` for AI triggering, `asyncio.Queue` for exit signals, and real-time P&L tracking
- **`src/polybot/tasks/` package** — Three new task modules:
  - `market_monitor.py` — 1-second market data polling with prefilter and AI trigger logic
  - `ai_decision.py` — Event-driven AI decision pipeline with entry and exit handling
  - `position_monitor.py` — Real-time position P&L tracking with stop-loss/take-profit triggers
- **Stop-loss/take-profit monitoring** — Positions are marked to market every second. When P&L hits -15% (stop-loss) or +30% (take-profit), an exit evaluation is triggered through the AI with full context about why the exit was triggered
- **`MonitorConfig`** — New config section with 7 parameters: `market_monitor_interval`, `position_monitor_interval`, `ai_cooldown_seconds`, `rr_trigger_threshold`, `stop_loss_pct`, `take_profit_pct`, `btc_price_cache_ttl`
- **Monitor section in `config/default.yaml`** — All monitor parameters exposed for tuning
- **Dashboard: monitor stats** — New `monitor` section in dashboard JSON showing prefilter snapshot count, AI cooldown remaining, and last trigger reason
- **Dashboard: position P&L** — New `position_pnl` section showing real-time P&L % for open positions

### Removed
- **Prefilter Check 6 (R/R ratio block)** — No longer blocks AI calls based on R/R ratio; R/R is handled by position sizing only
- **Risk manager R/R gate** — `reward_risk_ratio` check removed from `post_trade_checks`; entries at any price are allowed with size scaling
- **`_run_cycle()`, `_run_plain()`, `_run_with_dashboard()`, `_next_sleep_interval()`** — Replaced by concurrent task architecture
- **Adaptive polling** — No longer needed; market monitor runs every 1 second continuously

### Changed
- **Confidence gate lowered from 0.6 to 0.55** — AI confidence clustered at 0.55/0.58, just below the old 0.6 gate. Now configurable via `agent.min_confidence` in config.
- **Calibration gate `MIN_SAMPLES` raised from 5 to 15** — The calibration gate was blocking trades based on tiny sample sizes (5 trades). Now requires 15+ samples per confidence bin before activating.
- **Confidence gate now configurable** — New `agent.min_confidence` config field (default 0.55) allows tuning the confidence threshold without code changes.
- **System prompt: removed self-defeating confidence instruction** — Removed "If confidence below 0.6, HOLD" from the prompt (the hard gate in code already enforces this).
- **System prompt: removed harmful UP structural edge** — The "prefer UP" bias caused 0/8 UP trade losses in testing. The AI was treating every early-candle flat reading as "flat = UP wins" and buying UP regardless of actual conditions. Removed entirely — let the AI decide direction based on market data.
- **System prompt: added "wait for price action" guardrail** — At candle open, BTC is always "flat" by definition. The AI now knows to wait for a meaningful move before choosing direction, preventing the false "flat = UP wins" signal.
- **System prompt: calibrated confidence range** — Instead of anchoring at a single number (every trade was 0.62), the prompt now defines what each confidence band means: 0.55-0.60 marginal, 0.60-0.70 good, 0.70-0.80 strong, 0.80+ exceptional. Forces the AI to vary confidence based on actual signal strength.
- **System prompt: one entry per candle per side** — Prevents double-entry on the same candle (previously lost -$41 on 140 shares from two BUY UPs on the same candle).
- **BTC move elevated to PRIMARY SIGNAL** — The current BTC move vs candle open is now the first thing the AI sees, displayed prominently at the top of the context with signal strength classification (FLAT/SMALL/MODERATE/LARGE). Previously this critical signal was buried mid-prompt.
- **Pre-mortem requirement for BUY trades** — The `confidence_drivers` field now requires the AI to state what would make the trade LOSE before entering. Forces consideration of the downside scenario and counteracts overconfidence.
- **Recent trade outcomes in feedback context** — The AI now sees its own trade decisions and results (e.g., "UP buys: 0W/8L | DOWN buys: 3W/4L") plus a table of recent trades with outcomes. This enables real-time self-correction — the AI can see which token side is working and which isn't.
- **Move-magnitude position sizing** — Position size now scales with how much BTC has moved from candle open. Small moves (<$10) are noise and get 40% size, moderate moves ($30-60) get 80%, large moves ($60+) get full size. Combines multiplicatively with R/R scaling. Previously, the bot sized the same on $5 moves as $150 moves, causing big losses on noise.
- **Disabled `flat_market_edge` indicator** — This indicator told the AI "UP is underpriced" whenever UP < $0.50, generating false buy signals. The AI treated this as a buy trigger even when BTC was actively moving down. Market pricing reflects real information — cheap ≠ underpriced.
- **BTC candle momentum window: 4 → 6** — 4-candle momentum was too noisy for 5-min markets. 6-candle window (30 minutes) provides cleaner trend signals.
- **Slippage model: proportional_factor 0.5 → 1.0** — Previous slippage was optimistic, underestimating real execution costs especially in thin markets. Doubled the size-proportional slippage component for more realistic paper trading.
- **Cheap entry trap warning in prompt** — Added explicit warning that high R/R ≠ good trade. A $0.15 token has 5.7x R/R but is cheap because the market gives it ~15% odds. Direction must be confirmed before chasing cheap entries.

### Added
- **R/R pre-filter gate (Check 6)** — The pre-filter now checks if the best entry price has R/R < 1.3 *before* calling the AI, saving ~$0.005 per skipped cycle. Previously, the AI was called and then the post-trade risk manager blocked the trade — wasting the API call. Entry prices are known pre-AI, so this is a free optimization.
- **Shadow predictions on HOLD** — AI now returns a `hypothetical_direction` ("up" or "down") on every decision, including HOLDs. Shadow predictions are tracked by the calibration system and scored against actual candle outcomes, building calibration data without risking capital. Shadow accuracy is shown in the calibration summary and dashboard.
- **Confidence drivers** — AI now returns a `confidence_drivers` field explaining what specific data, signals, or conditions would increase its confidence. Makes HOLD decisions informative — shows what would need to change for the AI to trade. Stored in `TradeRecord.extra["confidence_drivers"]`.

### Fixed
- **SELL orders no longer blocked by wide spread** — The post-trade spread check now only applies to BUY orders. Previously, SELL/exit orders on DOWN tokens were blocked by the DOWN token's wide spread (e.g., 18% > 10% limit), trapping the bot in losing positions it couldn't exit. Exits should never be blocked by spread — you need to get out of losers.
- **Confidence and calibration gates no longer block exits** — Both the hard confidence gate (<0.6 override) and the calibration gate (win rate < break-even override) now only apply to BUY orders. Previously, a SELL/exit on a losing position could be overridden to HOLD if the AI's stated confidence fell in a poorly-calibrated bin, trapping the bot in an increasing loss.
- **Dashboard: resolutions now assigned to correct session** — Resolution-to-session assignment now uses candle slug matching (trade's `candle_slug` → resolution's `slug`) as primary method, with a generous timestamp fallback. Previously used a 5-minute post-session buffer which orphaned resolutions from candles that resolved after a run was stopped — showing 0W/0L for sessions that actually had wins/losses.
- **Dashboard: all session trades now included** — The dashboard data writer now uses an uncapped `_session_trades` list instead of `_recent_trades` (capped at 50). Previously, when a session ran more than 50 cycles, early trades (including BUY/SELLs with fills) were evicted from the dashboard view. This caused sessions to show 0W/0L and missing candle timeline data despite having real trades in the JSONL log.

### Changed
- **Structured reflection system** — Complete rewrite of the reflection/knowledge architecture to prevent the death spiral where reflection wrote escalating rules into persistent files:
  - **Structured observations** — Reflection now produces descriptive observations ("momentum plays at 0.30-0.40 won 3/4 times"), not imperatives ("NEVER trade above 0.40"). Stored in `observations.jsonl` with category (pattern/bias/edge/regime).
  - **Append-only with decay** — Observations are appended to a JSONL file and automatically expire after a configurable number of resolutions (default 30). Reflection can also explicitly expire old observations by ID when contradicted by new data.
  - **Quantitative scorecard** — Each reflection sees a scorecard comparing the current batch to the previous batch (win rate, avg PnL, avg win/loss size, hold rate with deltas). Creates a real feedback loop so reflection can see if its changes helped.
  - **Base knowledge is read-only** — `trading_patterns.md` and `self_assessment.md` are human-curated reference files, never overwritten by reflection. Decision prompt shows them as "Strategy & Bias Notes (reference)".
  - **Session history append-only** — One row appended per reflection batch, capped at 20 entries.
  - **New models** — `ObservationCategory`, `Observation`, `Scorecard`, `ScorecardDelta` in `models.py`.
  - **Knowledge state persistence** — Resolution counter and previous scorecard saved in `agent_state.json` so scorecard deltas work across restarts.
  - **Reflection max_tokens reduced** from 16384 to 4096 (structured output is much smaller than rewriting entire files).

### Added
- **Minimum risk/reward ratio gate** — New `risk.min_reward_risk_ratio` config (default 1.3) blocks BUY entries where `(1 - entry_price) / entry_price` falls below the threshold (~$0.435 entry cutoff). This prevents the bot from entering positions where the potential loss exceeds the potential gain, fixing the win/loss asymmetry where losses were significantly larger than wins.
- **Risk/reward-based position sizing** — BUY size is now scaled linearly based on R/R quality: 100% at R/R >= 2.0 (entry <= $0.33), ramping down to 50% at the minimum gate (R/R 1.3). Better entries get more capital, marginal entries get less.
- **R/R discipline in AI prompt** — The system prompt now explains the risk/reward math and gate to Claude, so the AI can factor entry price quality into its recommendations before the risk manager intervenes.

### Fixed
- **Reflection death spiral** — The reflection system was writing session-specific state (e.g., "-$21.63 LOSING SESSION", "require confidence >0.72") into persistent knowledge files. New sessions inherited stale losing-session rules, creating a permanent HOLD loop where the AI could never reach the self-imposed confidence threshold. Fixed by: (1) cleaning knowledge files to remove session-specific state and overly restrictive self-imposed rules, (2) adding guardrails to the reflection prompt explicitly forbidding session-specific state, escalating confidence thresholds, and absolute volatility filters in persistent knowledge files.

### Changed
- **Direct Chainlink data feed integration** — The Chainlink on-chain BTC/USD price (the actual resolution source) is now exposed to the AI in the prompt alongside the Binance price, including the $ divergence between them. New `chainlink_divergence` indicator flags high divergence (>$50) as resolution risk. The `BtcPrice` model now carries `chainlink_price` and `price_divergence` fields.
- **Hybrid ML + LLM scoring** (`ml_scorer.py`) — Online logistic regression model trained on 9 computed features (streak, magnitude, BTC vs open, volatility, volume, midpoints, imbalance, flat ratio). Trains incrementally after each candle resolution via gradient descent. ML prediction (UP probability + confidence) is passed to Claude as additional context. No external ML libraries — pure Python implementation. Model weights persisted to `ml_model.json`.
- **Enhanced order book indicators** — Three new indicators: `down_orderbook_imbalance` (bid/ask depth ratio for DOWN token), `cross_book_flow` (UP vs DOWN depth comparison for informed flow detection), `best_entry_analysis` (compares UP/DOWN ask prices and risk/reward ratios). Previously only UP token orderbook was analyzed.
- **Flat=UP edge detection** — New `flat_market_edge` indicator detects when BTC is in a flat/near-flat pattern (candle body < $5). Since Polymarket rule is "close >= open → UP wins", flat markets give UP a structural edge. Flags when UP token is underpriced (<0.50) in flat conditions. Enabled by default with configurable flat threshold.
- **Quantitative exit strategy tracker** (`exit_tracker.py`) — For every SELL decision, records entry/exit price and time remaining. After resolution, computes what-if: what would the position be worth if held to expiry ($1 or $0). Tracks good-exit rate (exits that were better than holding), total saved, and total missed upside. Feeds summary into AI prompt. Data persisted to `exit_analysis.jsonl`.
- **Intra-candle BTC price context** — The AI now sees BTC price NOW vs the candle open price, with the current move and who's winning (UP/DOWN). Uses the actual recorded candle open from the resolution tracker (not an approximation). The `btc_vs_candle_open` indicator also uses the recorded open. Exposed via `ResolutionTracker.get_candle_open()`.
- **Two-pass AI architecture** — Pass 1 uses Haiku (fast, cheap) to screen "is there a trade setup?" before calling Sonnet for the full decision. Skips the expensive model on ~70% of cycles. Configurable via `ai.two_pass_enabled` and `ai.screen_model`. Bypassed when positions are open (exit decisions always get full AI). Screen cost is ~$0.0003 vs ~$0.005 for full decision.
- **5 new computed indicators** — Pre-computed signals so Claude doesn't have to count/calculate from raw data: `consecutive_streak` (same-direction candle count with mean reversion signal), `streak_magnitude` (total $ move during streak with exhaustion detection), `btc_vs_candle_open` (where BTC is NOW vs candle open — the key binary outcome signal), `volatility_30m` (avg candle range + stdev for regime detection), `volume_trend` (recent vs prior volume ratio for momentum confirmation). All enabled by default in `feature_config.json`.
- **Confidence calibration tracker** (`calibration.py`) — Tracks every trade's stated confidence vs actual outcome. Builds a calibration curve from historical data, persisted to `calibration_data.jsonl`. Gates trades when calibrated win rate falls below break-even threshold (55%). Feeds calibration summary back to AI in the prompt so Claude can see how its confidence maps to reality.
- **Rules-based pre-filter** (`prefilter.py`) — Cheap, fast checks run before calling Claude to skip obvious HOLD cycles. Checks time remaining (<90s), spread width, book depth, choppy market detection (BTC range <$50/30min), and entry pricing. Bypasses AI for open positions (exit decisions still need Claude). Tracks skip rate and displays stats on both Rich terminal and web dashboards. Expected to save 60-70% of AI API costs.
- **Pending bet resolution on startup** — When the bot restarts after a crash or stop mid-candle, it now automatically detects unresolved trades (fills with no matching resolution record), fetches historical BTC prices from Binance, verifies the winner via Polymarket token prices, computes PnL from logged fills, and writes the missing resolution records. This ensures all-time stats and dashboard history remain accurate across restarts.
- `MarketDiscovery.fetch_market_by_slug()` — Public method to fetch a specific candle market by its exact slug, used by the pending bet resolver to look up past markets on the Gamma API.
- `_compute_pnl_from_trades()` helper — Reconstructs position PnL from logged BUY/SELL fills for settlement (winning token = $1, losing = $0).

- **Dashboard: Intelligence panel** — New panel showing ML model training status (sample count, trained/training state), confidence calibration curve as a visual bar chart (stated confidence bins vs actual win rates, color-coded above/below break-even, dimmed bars for insufficient data), and exit analysis stats (good-exit rate, money saved by early exits, missed upside from exits). All three intelligence subsystems are now surfaced for live monitoring.
- **Dashboard: Chainlink price in BTC panel** — The BTC panel now shows the Chainlink on-chain price alongside the Binance price, with the dollar divergence between them. Divergences above $50 display an amber warning icon since Polymarket resolves via Chainlink, not Binance.
- **Adaptive polling intervals** — The bot now uses two-speed polling: fast 10s checks until the pre-filter first passes and the AI is called, then 60s intervals for the rest of the candle. This detects opportunities quickly without multiplying AI costs — the fast phase is free (pre-filter only), and once the AI has evaluated, the bot drops to the same 60s cadence as before. Resets on each candle rotation. Configurable via `fast_poll_interval` (default 10s) and `decision_interval` (default 60s).

### Fixed
- **Dashboard Cash/Portfolio metrics now scoped per session** — When viewing a specific session or day, the Cash and Portfolio cards now show that session's start→current values instead of always referencing the global `initial_cash`. Overview still shows the all-time view.
- **Added AI Cost and Fees metric cards to dashboard** — Two new cards show the total Claude API cost and trading fees for the selected view, making it clear why a session with positive PnL can still lose portfolio value. AI cost is now logged per-trade in `TradeRecord.ai_cost` so historical sessions can compute it too.
- **Added Open Trade PnL metric to dashboard** — Shows realized P&L from buy/sell round-trips on the current (unresolved) candle. This value is already reflected in cash but not yet in resolution PnL, explaining the accounting gap between `initial_cash + resolution_pnl - fees - ai_cost` and actual cash.
- **Fixed stale BTC candle in history** — `load_candle_history()` now drops the last candle from Binance's response (always an incomplete in-progress candle with wrong close/high/low). `append_latest_candle()` now replaces the last candle when the `open_time` matches instead of skipping it. This fixes the AI seeing phantom wrong-direction candles that persisted from startup.
- **Added candle completeness safeguards** — Three layers of defense against stale candle data: (1) `candles` property now filters out any candle with `close_time` in the future, so incomplete candles can never reach the AI. (2) Periodic full candle history refresh every 10 minutes corrects any accumulated drift. (3) Initial load strips the in-progress candle.
- **Reset knowledge files** — Cleared session-specific analysis from `trading_patterns.md`, `self_assessment.md`, and `session_history.md` since previous sessions' pattern analysis was built on incorrect candle direction data. Retained proven strategy framework (entry/exit discipline, regime detection, confidence calibration).
