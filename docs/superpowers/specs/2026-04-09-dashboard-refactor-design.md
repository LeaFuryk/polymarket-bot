# Dashboard Refactor — Multi-Model Trading View

## Context

The polybot now runs 3 models (LogisticRegression, RandomForest, XGBoost) in parallel, each with independent portfolios and strategies. The bot broadcasts two new event types: `model_entry` and `model_settlement`. The dashboard needs a complete refactor to display this multi-model data.

The existing `dashboard-next` is a Next.js 16 / React 19 app with Tailwind and custom SVG charts. It currently connects to the collector WS (port 8765) and renders a legacy single-model view built for an older bot architecture. Most of the existing components are for the legacy system and will be replaced.

## Design

### Layout: 3 sections, top to bottom

```
┌─────────────────────────────────────────────────────────┐
│  Section 1: Candle Chart                                │
│  BTC OHLC candles + UP/DOWN token prices                │
│  Similar to Polymarket UI — last N candles              │
│  Current candle highlighted with countdown timer         │
└─────────────────────────────────────────────────────────┘
┌───────────────────────────────────────┬─────────────────┐
│  Section 2: Current Bet               │  PnL Panel      │
│  Timeline (0%→100% elapsed)           │  Per-model PnL   │
│  UP price line (green)                │  for this candle │
│  DOWN price line (red)                │                  │
│  Model entry markers on timeline      │                  │
│  Each marker: model, direction,       │                  │
│  price, confidence, inference_ms      │                  │
└───────────────────────────────────────┴─────────────────┘
┌─────────────────────────────────────────────────────────┐
│  Section 3: Portfolio Comparison                        │
│  3 equity curves (LR blue, RF red, XGB orange)          │
│  Stats cards: cash, W/L, win rate, return % per model   │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│  Section 4: Previous Bets (list)                        │
│  Candle ID | Outcome | Model entries | PnL per model    │
│  Click to expand → shows Section 2 chart for that bet   │
└─────────────────────────────────────────────────────────┘
```

### Data Source

Single WebSocket connection to **Polybot** (`ws://localhost:8766`). The polybot forwards all collector events and adds its own model events — the dashboard never connects to the collector directly.

**Events received on port 8766:**
- `snapshot`: BTC price, UP/DOWN orderbooks, elapsed %, market volume (forwarded from collector)
- `candle_close`: OHLC, outcome, final_ret (forwarded from collector)
- `candle_correction`: updated outcome/prices (forwarded from collector)
- `model_entry`: model name, direction, price, confidence, inference_ms, checkpoint, elapsed
- `model_settlement`: model name, outcome, won, pnl, cash, W/L counts
- `initial_state`: candle history, snapshots, 3 portfolio summaries (sent on connect)

### Section 1: Candle Chart

Displays the last ~20 candles as a standard OHLC-style chart, but for UP/DOWN token prices rather than BTC.

**Data:** Built from `candle_close` events (historical) + `snapshot` events (current candle).

**Components:**
- `CandleChart` — main chart area. Each candle shows:
  - UP token price range (green bar)
  - DOWN token price range (red bar)
  - BTC open price as horizontal reference line
  - Outcome indicator (UP/DOWN badge) for resolved candles
- Current candle is highlighted with a pulsing border + countdown timer showing time remaining
- X-axis: time labels (HH:MM). Y-axis: token price (0–1.0)

**On candle_close:** Current candle freezes, shifts left, new empty candle appears on the right.

### Section 2: Current Bet

A horizontal timeline chart for the active 5-minute candle, showing price evolution and model entries.

**Left side — Timeline chart:**
- X-axis: elapsed % (0% → 100%) or time (0:00 → 5:00)
- Two lines: UP price (green) and DOWN price (red), updated in real-time from `snapshot` events
- Model entry markers overlaid on the timeline. Each marker is a dot/triangle at the elapsed % where the model entered, color-coded by model:
  - LogisticRegression: blue
  - RandomForest: red
  - XGBoost: orange
- Hover/tooltip on marker shows: model name, direction (UP/DOWN), entry price, confidence %, inference time (ms)
- If a model has 2 entries (scaling-in), both are shown

**Right side — PnL panel:**
- For each model that entered this candle: direction, entry price(s), current unrealized PnL
- Updated in real-time as prices change
- Color: green if currently winning, red if losing

**On candle_close:** This entire section resolves — shows final outcome (UP/DOWN) with animation, updates PnL to final realized values, then moves the bet to the Previous Bets section below.

### Section 3: Portfolio Comparison

Three equity curves and stats cards, one per model.

**Equity chart:**
- 3 overlaid line charts showing cumulative balance over time
- LogisticRegression: blue, RandomForest: red, XGBoost: orange
- X-axis: candle # or time. Y-axis: balance ($)
- Horizontal $1000 reference line
- Updated on each `model_settlement` event

**Stats cards** (one per model, side by side):
- Cash balance
- W / L count
- Win rate %
- Return %
- Max drawdown %

**Data:** Built from `model_settlement` events (append balance to history) + `initial_state` on connect.

### Section 4: Previous Bets

A scrollable list of past candle bets, most recent first.

**Collapsed view (one row per candle):**
- Candle ID / time
- Outcome (UP/DOWN badge)
- Per-model results: direction + won/lost + PnL (3 columns, one per model)
- Color-coded: green row if all models won, red if all lost, mixed otherwise

**Expanded view (on click):**
- Shows the same chart as Section 2 (timeline with price lines + model markers) but for a historical candle
- All data comes from stored `model_entry` and `model_settlement` events
- Resolution outcome displayed prominently

**Data:** Accumulated from `model_settlement` events. Each candle's entries stored in a buffer. On `candle_correction`, update the affected row.

### State Management

**React Context** (`DashboardContext`):

```typescript
interface DashboardState {
  // Collector data
  candles: CandleRecord[];
  currentSnapshots: Snapshot[];   // current candle's snapshots for Section 2 chart
  
  // Model data
  portfolios: Record<string, PortfolioSummary>;  // "LogisticRegression" → summary
  equityHistory: Record<string, number[]>;        // model → balance history
  
  // Current candle
  currentEntries: ModelEntry[];   // model_entry events for current candle
  
  // History
  pastBets: PastBet[];            // resolved candles with entries + settlements
}
```

**Buffer management:**
- Keep last 100 resolved candles in `pastBets`
- Keep full equity history (grows unbounded during session, reset on refresh)
- Current candle snapshots reset on `candle_close`

### New TypeScript Types

```typescript
interface ModelEntry {
  type: "model_entry";
  model: string;          // "LogisticRegression" | "RandomForest" | "XGBoost"
  candle_id: string;
  direction: "UP" | "DOWN";
  price: number;
  amount_usd: number;
  confidence: number;
  inference_ms: number;
  checkpoint: number;
  elapsed_pct: number;
  timestamp: number;
}

interface ModelSettlement {
  type: "model_settlement";
  model: string;
  candle_id: string;
  outcome: "UP" | "DOWN";
  direction: "UP" | "DOWN";
  won: boolean;
  entries: BetEntry[];
  pnl: number;
  cash: number;
  wins: number;
  losses: number;
  timestamp: number;
}

interface PortfolioSummary {
  initial_cash: number;
  final_balance: number;
  wins: number;
  losses: number;
  win_rate: number;
  realized_pnl: number;
  net_pnl: number;
  total_fees: number;
  total_return_pct: number;
}

interface PastBet {
  candle_id: string;
  outcome: "UP" | "DOWN";
  timestamp: number;
  entries: ModelEntry[];                     // all model entries for this candle
  settlements: Record<string, ModelSettlement>;  // model → settlement
  snapshots: Snapshot[];                     // price history for expanded chart
}
```

### WebSocket Hook Changes

Current `useWebSocket` connects to port 8765 (collector). Change to connect to **port 8766 (polybot)** — single connection receives all events (collector forwarded + model events + initial_state). The existing reconnection logic (exponential backoff) stays the same.

### Component Structure

```
src/
├── app/
│   └── page.tsx                    # Main dashboard (REWRITE)
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx            # MODIFY: new context provider
│   │   ├── Header.tsx              # KEEP: connection status for both WS
│   │   └── Sidebar.tsx             # SIMPLIFY: fewer pages for now
│   ├── candles/
│   │   └── CandleChart.tsx         # NEW: Section 1
│   ├── current-bet/
│   │   ├── BetTimeline.tsx         # NEW: Section 2 left (price lines + markers)
│   │   └── BetPnlPanel.tsx         # NEW: Section 2 right (per-model PnL)
│   ├── portfolios/
│   │   ├── EquityChart.tsx         # NEW: Section 3 chart
│   │   └── PortfolioCards.tsx      # NEW: Section 3 stats
│   ├── history/
│   │   ├── BetList.tsx             # NEW: Section 4 list
│   │   └── BetDetail.tsx           # NEW: Section 4 expanded view
│   └── shared/
│       ├── MetricCard.tsx          # KEEP
│       ├── StatusBadge.tsx         # KEEP
│       ├── AnimatedNumber.tsx      # KEEP
│       ├── Countdown.tsx           # KEEP
│       └── ConnectionStatus.tsx    # KEEP
├── hooks/
│   ├── useWebSocket.ts            # REWRITE: dual WS connections
│   └── useDashboardData.ts        # NEW: derives dashboard state
├── lib/
│   ├── types.ts                   # REWRITE: new message types
│   ├── constants.ts               # MODIFY: add polybot WS URL
│   └── format.ts                  # KEEP + extend
└── context/
    └── DashboardContext.tsx        # NEW: central state management
```

### Pages

For this iteration, the dashboard is a **single page** with all 4 sections stacked vertically. The existing status, history, and forensics pages are removed (they were built for the legacy bot architecture).

Future iterations can add pages back as needed.

### Model Colors

Consistent across all sections:
- **LogisticRegression**: `#3498db` (blue)
- **RandomForest**: `#e74c3c` (red)
- **XGBoost**: `#e67e22` (orange)

Defined once in `constants.ts`, used everywhere.

### Chart Implementation

Continue the existing approach: **custom SVG charts** (no external charting library). The current codebase already has `CandlePriceChart` with dual-series lines, hover tooltips, and trade markers. The new charts follow the same patterns.

### Responsive Design

Desktop-first (this is a monitoring dashboard). Min-width: 1024px. Sections stack vertically. Section 2 has a left/right split (timeline | PnL panel) that collapses to stacked on narrow screens.

## Out of Scope

- Mobile layout optimization
- User authentication
- Persistent storage (dashboard is stateless — refreshing resets history)
- Status, history, forensics pages (legacy, may return in future iterations)
- Dark/light theme toggle (dark only, matching Polymarket UI)
