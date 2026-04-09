# Dashboard Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the dashboard to display 3 models (LR, RF, XGBoost) trading in parallel — candle chart, current bet timeline with model entries, portfolio equity curves, and previous bets history.

**Architecture:** Single-page dashboard connected to Polybot WS (port 8766). React Context holds all state. Messages: `snapshot`, `candle_close`, `candle_correction` (forwarded from collector) + `model_entry`, `model_settlement`, `initial_state` (from model runners). Custom SVG charts following existing codebase patterns.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, Tailwind CSS 4, custom SVG charts

**Spec:** `docs/superpowers/specs/2026-04-09-dashboard-refactor-design.md`

---

### File Structure

```
dashboard-next/src/
├── app/
│   ├── layout.tsx                    # KEEP (fonts, metadata)
│   └── page.tsx                      # REWRITE (single-page, 4 sections)
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx              # REWRITE (new DashboardContext)
│   │   └── Header.tsx                # MODIFY (remove sidebar, simpler)
│   ├── candles/
│   │   └── CandleChart.tsx           # NEW: Section 1
│   ├── current-bet/
│   │   ├── BetTimeline.tsx           # NEW: Section 2 left
│   │   └── BetPnlPanel.tsx           # NEW: Section 2 right
│   ├── portfolios/
│   │   ├── EquityChart.tsx           # NEW: Section 3 chart
│   │   └── PortfolioCards.tsx        # NEW: Section 3 stats
│   ├── history/
│   │   ├── BetList.tsx               # NEW: Section 4 list
│   │   └── BetDetail.tsx             # NEW: Section 4 expanded
│   └── shared/
│       ├── MetricCard.tsx            # KEEP
│       ├── AnimatedNumber.tsx        # KEEP
│       └── Countdown.tsx             # KEEP
├── hooks/
│   └── useWebSocket.ts              # REWRITE (port 8766, new message types)
├── context/
│   └── DashboardContext.tsx          # NEW: central state
└── lib/
    ├── types.ts                      # REWRITE (new message types)
    ├── constants.ts                  # MODIFY (WS URL, model colors)
    └── format.ts                     # KEEP
```

**Files to delete:** `src/components/layout/Sidebar.tsx`, `src/components/trading/*`, `src/components/status/*`, `src/components/candles/CandleCard.tsx`, `src/components/candles/CandleDetail.tsx`, `src/components/candles/CandlePriceChart.tsx`, `src/components/candles/BtcMoveChart.tsx`, `src/components/candles/CandleTimeline.tsx`, `src/app/status/`, `src/app/history/`, `src/app/forensics/`, `src/app/api/`, `src/hooks/useTradingData.ts`, `src/hooks/useStatusData.ts`, `src/hooks/useFallbackData.ts`

---

### Task 1: Types and constants

**Files:**
- Rewrite: `dashboard-next/src/lib/types.ts`
- Modify: `dashboard-next/src/lib/constants.ts`

- [ ] **Step 1: Rewrite types.ts**

```typescript
/** TypeScript types for the multi-model trading dashboard. */

// --- Model identification ---

export type ModelName = "LogisticRegression" | "RandomForest" | "XGBoost";

// --- Collector events (forwarded by polybot) ---

export interface Snapshot {
  type: "snapshot";
  candle_id: string;
  timestamp: number;
  elapsed_pct: number;
  btc_price: number;
  btc_bid: number;
  btc_ask: number;
  up_bids: [number, number][];
  up_asks: [number, number][];
  down_bids: [number, number][];
  down_asks: [number, number][];
  market_volume: number;
}

export interface CandleClose {
  type: "candle_close";
  candle_id: string;
  start_time: number;
  end_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  outcome: "UP" | "DOWN";
  final_ret: number;
}

export interface CandleCorrection {
  type: "candle_correction";
  candle_id: string;
  start_time: number;
  end_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  outcome: "UP" | "DOWN";
  final_ret: number;
}

// --- Model events (from polybot runners) ---

export interface BetEntry {
  price: number;
  amount_usd: number;
  elapsed_pct: number;
  confidence: number;
  checkpoint: number;
}

export interface ModelEntry {
  type: "model_entry";
  model: ModelName;
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

export interface ModelSettlement {
  type: "model_settlement";
  model: ModelName;
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

// --- Initial state (sent on WS connect) ---

export interface PortfolioSummary {
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

export interface InitialState {
  type: "initial_state";
  candles: CandleClose[];
  snapshots_so_far: Snapshot[];
  portfolios: Record<ModelName, PortfolioSummary>;
}

// --- Derived types for dashboard state ---

export interface PastBet {
  candle_id: string;
  outcome: "UP" | "DOWN";
  timestamp: number;
  entries: ModelEntry[];
  settlements: Partial<Record<ModelName, ModelSettlement>>;
  snapshots: SnapshotPoint[];
}

export interface SnapshotPoint {
  elapsed_pct: number;
  timestamp: number;
  up_ask: number | null;
  down_ask: number | null;
  btc_price: number;
}

// --- Union type for all incoming messages ---

export type WSMessage =
  | Snapshot
  | CandleClose
  | CandleCorrection
  | ModelEntry
  | ModelSettlement
  | InitialState;
```

- [ ] **Step 2: Update constants.ts**

```typescript
/** Theme constants and shared configuration. */

export const THEME = {
  bg: {
    base: "#080a0e",
    raised: "#0d1017",
    surface: "#131720",
  },
  colors: {
    green: "#22c55e",
    red: "#ef4444",
    amber: "#f59e0b",
    cyan: "#06b6d4",
    blue: "#3b82f6",
    purple: "#a78bfa",
  },
} as const;

export const MODEL_COLORS: Record<string, string> = {
  LogisticRegression: "#3498db",
  RandomForest: "#e74c3c",
  XGBoost: "#e67e22",
} as const;

export const MODEL_SHORT: Record<string, string> = {
  LogisticRegression: "LR",
  RandomForest: "RF",
  XGBoost: "XGB",
} as const;

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8766";

export const RECONNECT_INTERVALS = {
  initial: 1000,
  max: 30000,
  multiplier: 2,
} as const;
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd dashboard-next && npx tsc --noEmit src/lib/types.ts src/lib/constants.ts`

- [ ] **Step 4: Commit**

```bash
git add dashboard-next/src/lib/types.ts dashboard-next/src/lib/constants.ts
git commit -m "feat(dashboard): rewrite types and constants for multi-model"
```

---

### Task 2: WebSocket hook + DashboardContext

**Files:**
- Rewrite: `dashboard-next/src/hooks/useWebSocket.ts`
- Create: `dashboard-next/src/context/DashboardContext.tsx`

- [ ] **Step 1: Rewrite useWebSocket.ts**

```typescript
"use client";

import { useEffect, useRef, useState } from "react";
import type {
  CandleClose,
  ModelEntry,
  ModelSettlement,
  Snapshot,
  SnapshotPoint,
  WSMessage,
  InitialState,
  PastBet,
  PortfolioSummary,
} from "@/lib/types";
import { RECONNECT_INTERVALS, WS_URL } from "@/lib/constants";

export type WSState =
  | "connecting"
  | "connected"
  | "disconnected"
  | "reconnecting";

export interface DashboardData {
  wsState: WSState;
  candles: CandleClose[];
  currentCandleId: string | null;
  currentSnapshots: SnapshotPoint[];
  currentEntries: ModelEntry[];
  portfolios: Record<string, PortfolioSummary>;
  equityHistory: Record<string, number[]>;
  pastBets: PastBet[];
  latestSnapshot: Snapshot | null;
}

const MAX_PAST_BETS = 100;

export function useWebSocket(url: string = WS_URL): DashboardData {
  const [wsState, setWsState] = useState<WSState>("disconnected");
  const [candles, setCandles] = useState<CandleClose[]>([]);
  const [currentCandleId, setCurrentCandleId] = useState<string | null>(null);
  const [currentSnapshots, setCurrentSnapshots] = useState<SnapshotPoint[]>([]);
  const [currentEntries, setCurrentEntries] = useState<ModelEntry[]>([]);
  const [portfolios, setPortfolios] = useState<Record<string, PortfolioSummary>>({});
  const [equityHistory, setEquityHistory] = useState<Record<string, number[]>>({});
  const [pastBets, setPastBets] = useState<PastBet[]>([]);
  const [latestSnapshot, setLatestSnapshot] = useState<Snapshot | null>(null);

  // Refs for accumulating data within a candle (avoid stale closures)
  const currentEntriesRef = useRef<ModelEntry[]>([]);
  const currentSnapshotsRef = useRef<SnapshotPoint[]>([]);
  const currentCandleIdRef = useRef<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retryCount = useRef(0);
  const retryTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let disposed = false;

    function scheduleReconnect() {
      if (disposed) return;
      const delay = Math.min(
        RECONNECT_INTERVALS.initial *
          RECONNECT_INTERVALS.multiplier ** retryCount.current,
        RECONNECT_INTERVALS.max,
      );
      retryCount.current += 1;
      retryTimeout.current = setTimeout(connect, delay);
    }

    function handleMessage(raw: string) {
      if (disposed) return;
      try {
        const msg: WSMessage = JSON.parse(raw);
        switch (msg.type) {
          case "initial_state": {
            const init = msg as InitialState;
            setCandles(init.candles);
            setPortfolios(init.portfolios);
            // Initialize equity history from portfolio balances
            const hist: Record<string, number[]> = {};
            for (const [model, p] of Object.entries(init.portfolios)) {
              hist[model] = [p.final_balance];
            }
            setEquityHistory(hist);
            // Load current snapshots if any
            if (init.snapshots_so_far.length > 0) {
              const points = init.snapshots_so_far.map((s) => ({
                elapsed_pct: s.elapsed_pct,
                timestamp: s.timestamp,
                up_ask: s.up_asks?.[0]?.[0] ?? null,
                down_ask: s.down_asks?.[0]?.[0] ?? null,
                btc_price: s.btc_price,
              }));
              currentSnapshotsRef.current = points;
              setCurrentSnapshots(points);
            }
            break;
          }
          case "snapshot": {
            const snap = msg as Snapshot;
            setLatestSnapshot(snap);
            // Track candle transitions
            if (snap.candle_id !== currentCandleIdRef.current) {
              currentCandleIdRef.current = snap.candle_id;
              currentSnapshotsRef.current = [];
              currentEntriesRef.current = [];
              setCurrentCandleId(snap.candle_id);
              setCurrentEntries([]);
            }
            const point: SnapshotPoint = {
              elapsed_pct: snap.elapsed_pct,
              timestamp: snap.timestamp,
              up_ask: snap.up_asks?.[0]?.[0] ?? null,
              down_ask: snap.down_asks?.[0]?.[0] ?? null,
              btc_price: snap.btc_price,
            };
            currentSnapshotsRef.current = [...currentSnapshotsRef.current, point];
            setCurrentSnapshots([...currentSnapshotsRef.current]);
            break;
          }
          case "model_entry": {
            const entry = msg as ModelEntry;
            currentEntriesRef.current = [...currentEntriesRef.current, entry];
            setCurrentEntries([...currentEntriesRef.current]);
            break;
          }
          case "model_settlement": {
            const settlement = msg as ModelSettlement;
            // Update portfolio for this model
            setPortfolios((prev) => ({
              ...prev,
              [settlement.model]: {
                ...prev[settlement.model],
                final_balance: settlement.cash,
                wins: settlement.wins,
                losses: settlement.losses,
                win_rate:
                  settlement.wins + settlement.losses > 0
                    ? settlement.wins / (settlement.wins + settlement.losses)
                    : 0,
                net_pnl: settlement.cash - 1000,
                total_return_pct: ((settlement.cash - 1000) / 1000) * 100,
              },
            }));
            // Append to equity history
            setEquityHistory((prev) => ({
              ...prev,
              [settlement.model]: [
                ...(prev[settlement.model] ?? []),
                settlement.cash,
              ],
            }));
            // Build past bet entry (accumulate settlements per candle)
            setPastBets((prev) => {
              const existing = prev.find(
                (b) => b.candle_id === settlement.candle_id,
              );
              if (existing) {
                return prev.map((b) =>
                  b.candle_id === settlement.candle_id
                    ? {
                        ...b,
                        outcome: settlement.outcome,
                        settlements: {
                          ...b.settlements,
                          [settlement.model]: settlement,
                        },
                      }
                    : b,
                );
              }
              return [
                {
                  candle_id: settlement.candle_id,
                  outcome: settlement.outcome,
                  timestamp: settlement.timestamp,
                  entries: [...currentEntriesRef.current].filter(
                    (e) => e.candle_id === settlement.candle_id,
                  ),
                  settlements: { [settlement.model]: settlement },
                  snapshots: [...currentSnapshotsRef.current],
                },
                ...prev,
              ].slice(0, MAX_PAST_BETS);
            });
            break;
          }
          case "candle_close": {
            const candle = msg as CandleClose;
            setCandles((prev) => [...prev.slice(-19), candle]);
            // Reset current candle state
            currentSnapshotsRef.current = [];
            currentEntriesRef.current = [];
            setCurrentSnapshots([]);
            setCurrentEntries([]);
            setCurrentCandleId(null);
            break;
          }
          case "candle_correction": {
            // Update the affected candle and past bet
            const correction = msg as unknown as CandleClose;
            setCandles((prev) =>
              prev.map((c) =>
                c.candle_id === correction.candle_id ? { ...c, ...correction } : c,
              ),
            );
            setPastBets((prev) =>
              prev.map((b) =>
                b.candle_id === correction.candle_id
                  ? { ...b, outcome: correction.outcome }
                  : b,
              ),
            );
            break;
          }
        }
      } catch {
        // ignore malformed messages
      }
    }

    function connect() {
      if (disposed) return;
      if (wsRef.current?.readyState === WebSocket.OPEN) return;

      setWsState(retryCount.current > 0 ? "reconnecting" : "connecting");

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) return;
        setWsState("connected");
        retryCount.current = 0;
      };

      ws.onmessage = (event) => handleMessage(event.data);

      ws.onclose = () => {
        if (disposed) return;
        setWsState("disconnected");
        wsRef.current = null;
        scheduleReconnect();
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      disposed = true;
      if (retryTimeout.current) clearTimeout(retryTimeout.current);
      wsRef.current?.close();
    };
  }, [url]);

  return {
    wsState,
    candles,
    currentCandleId,
    currentSnapshots,
    currentEntries,
    portfolios,
    equityHistory,
    pastBets,
    latestSnapshot,
  };
}
```

- [ ] **Step 2: Create DashboardContext.tsx**

```typescript
"use client";

import { createContext, useContext } from "react";
import type { DashboardData } from "@/hooks/useWebSocket";

const DashboardContext = createContext<DashboardData | null>(null);

export function useDashboard(): DashboardData {
  const ctx = useContext(DashboardContext);
  if (!ctx)
    throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}

export { DashboardContext };
```

- [ ] **Step 3: Commit**

```bash
git add dashboard-next/src/hooks/useWebSocket.ts dashboard-next/src/context/DashboardContext.tsx
git commit -m "feat(dashboard): rewrite WS hook for multi-model + DashboardContext"
```

---

### Task 3: AppShell and Header cleanup

**Files:**
- Rewrite: `dashboard-next/src/components/layout/AppShell.tsx`
- Modify: `dashboard-next/src/components/layout/Header.tsx`
- Delete: `dashboard-next/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Rewrite AppShell.tsx**

```typescript
"use client";

import { Header } from "./Header";
import { useWebSocket } from "@/hooks/useWebSocket";
import { DashboardContext } from "@/context/DashboardContext";

export function AppShell({ children }: { children: React.ReactNode }) {
  const data = useWebSocket();

  return (
    <DashboardContext.Provider value={data}>
      <div className="flex h-screen flex-col overflow-hidden bg-[#080a0e]">
        <Header wsState={data.wsState} />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">{children}</main>
      </div>
    </DashboardContext.Provider>
  );
}
```

- [ ] **Step 2: Simplify Header.tsx**

```typescript
"use client";

import type { WSState } from "@/hooks/useWebSocket";

const STATE_COLORS: Record<WSState, string> = {
  connected: "#22c55e",
  connecting: "#f59e0b",
  reconnecting: "#f59e0b",
  disconnected: "#ef4444",
};

export function Header({ wsState }: { wsState: WSState }) {
  return (
    <header className="flex items-center justify-between border-b border-white/5 px-6 py-3">
      <div className="flex items-center gap-3">
        <h1 className="font-mono text-lg font-bold text-white">
          Polymarket Bot
        </h1>
        <span className="text-xs text-white/40">Multi-Model Dashboard</span>
      </div>
      <div className="flex items-center gap-2">
        <div
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: STATE_COLORS[wsState] }}
        />
        <span className="font-mono text-xs text-white/60">{wsState}</span>
      </div>
    </header>
  );
}
```

- [ ] **Step 3: Delete Sidebar.tsx**

```bash
rm dashboard-next/src/components/layout/Sidebar.tsx
```

- [ ] **Step 4: Commit**

```bash
git add dashboard-next/src/components/layout/
git commit -m "feat(dashboard): simplify layout — remove sidebar, new AppShell"
```

---

### Task 4: Section 1 — CandleChart

**Files:**
- Create: `dashboard-next/src/components/candles/CandleChart.tsx`

- [ ] **Step 1: Create CandleChart component**

This is a custom SVG chart showing last ~20 candles as vertical bars (UP price green, DOWN price red), with the current candle highlighted.

```typescript
"use client";

import { useDashboard } from "@/context/DashboardContext";
import { Countdown } from "@/components/shared/Countdown";
import { THEME } from "@/lib/constants";

const CHART_W = 900;
const CHART_H = 200;
const BAR_GAP = 4;
const MAX_CANDLES = 20;

export function CandleChart() {
  const { candles, latestSnapshot, currentCandleId } = useDashboard();
  const displayed = candles.slice(-MAX_CANDLES);

  if (displayed.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg bg-[#0d1017] text-white/30">
        Waiting for candle data...
      </div>
    );
  }

  const barW = (CHART_W - BAR_GAP * (MAX_CANDLES + 1)) / MAX_CANDLES;

  // Y-axis: BTC price range across displayed candles
  const allPrices = displayed.flatMap((c) => [c.open, c.close, c.high, c.low]);
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const range = maxP - minP || 1;
  const pad = range * 0.1;

  function yPos(price: number): number {
    return CHART_H - ((price - minP + pad) / (range + pad * 2)) * CHART_H;
  }

  // Time remaining for current candle
  const lastCandle = displayed[displayed.length - 1];
  const timeRemaining = latestSnapshot
    ? Math.max(0, (1 - latestSnapshot.elapsed_pct) * 300)
    : 0;

  return (
    <div className="rounded-lg bg-[#0d1017] p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-mono text-sm font-semibold text-white/70">
          Candle History
        </h2>
        {currentCandleId && (
          <div className="flex items-center gap-2 font-mono text-xs text-white/50">
            <span>Current: {currentCandleId.split("-").pop()}</span>
            <Countdown seconds={timeRemaining} />
          </div>
        )}
      </div>
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        className="w-full"
        style={{ maxHeight: 200 }}
      >
        {/* Grid lines */}
        {[0.25, 0.5, 0.75].map((pct) => {
          const price = minP - pad + (range + pad * 2) * pct;
          const y = yPos(price);
          return (
            <g key={pct}>
              <line
                x1={0}
                x2={CHART_W}
                y1={y}
                y2={y}
                stroke="white"
                strokeOpacity={0.05}
              />
              <text
                x={CHART_W - 2}
                y={y - 3}
                fill="white"
                fillOpacity={0.3}
                fontSize={9}
                textAnchor="end"
                fontFamily="monospace"
              >
                ${price.toFixed(0)}
              </text>
            </g>
          );
        })}

        {displayed.map((candle, i) => {
          const x = BAR_GAP + i * (barW + BAR_GAP);
          const isUp = candle.outcome === "UP";
          const bodyTop = yPos(Math.max(candle.open, candle.close));
          const bodyBot = yPos(Math.min(candle.open, candle.close));
          const bodyH = Math.max(bodyBot - bodyTop, 1);
          const wickTop = yPos(candle.high);
          const wickBot = yPos(candle.low);
          const color = isUp ? THEME.colors.green : THEME.colors.red;
          const isCurrent =
            currentCandleId && candle.candle_id === currentCandleId;

          return (
            <g key={candle.candle_id}>
              {/* Wick */}
              <line
                x1={x + barW / 2}
                x2={x + barW / 2}
                y1={wickTop}
                y2={wickBot}
                stroke={color}
                strokeWidth={1}
                strokeOpacity={0.5}
              />
              {/* Body */}
              <rect
                x={x}
                y={bodyTop}
                width={barW}
                height={bodyH}
                fill={color}
                fillOpacity={isCurrent ? 1 : 0.7}
                rx={1}
              />
              {/* Current candle highlight */}
              {isCurrent && (
                <rect
                  x={x - 2}
                  y={0}
                  width={barW + 4}
                  height={CHART_H}
                  fill="none"
                  stroke={THEME.colors.cyan}
                  strokeWidth={1}
                  strokeDasharray="4 2"
                  strokeOpacity={0.4}
                />
              )}
              {/* Outcome badge */}
              <text
                x={x + barW / 2}
                y={CHART_H - 4}
                fill={color}
                fontSize={7}
                textAnchor="middle"
                fontFamily="monospace"
              >
                {candle.outcome}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard-next/src/components/candles/CandleChart.tsx
git commit -m "feat(dashboard): Section 1 — CandleChart component"
```

---

### Task 5: Section 2 — BetTimeline + BetPnlPanel

**Files:**
- Create: `dashboard-next/src/components/current-bet/BetTimeline.tsx`
- Create: `dashboard-next/src/components/current-bet/BetPnlPanel.tsx`

- [ ] **Step 1: Create BetTimeline.tsx**

```typescript
"use client";

import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT, THEME } from "@/lib/constants";

const W = 700;
const H = 160;
const PAD = { top: 20, right: 10, bottom: 25, left: 35 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

export function BetTimeline() {
  const { currentSnapshots, currentEntries, currentCandleId } = useDashboard();

  if (!currentCandleId || currentSnapshots.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg bg-[#0d1017] text-white/30 font-mono text-sm">
        Waiting for candle...
      </div>
    );
  }

  // Price range for Y-axis
  const upPrices = currentSnapshots.map((s) => s.up_ask).filter((p): p is number => p !== null);
  const downPrices = currentSnapshots.map((s) => s.down_ask).filter((p): p is number => p !== null);
  const allPrices = [...upPrices, ...downPrices];
  const minP = allPrices.length > 0 ? Math.min(...allPrices) : 0;
  const maxP = allPrices.length > 0 ? Math.max(...allPrices) : 1;
  const range = maxP - minP || 0.1;
  const pad = range * 0.1;

  function x(elapsed: number): number {
    return PAD.left + Math.min(elapsed, 1) * INNER_W;
  }
  function y(price: number): number {
    return PAD.top + INNER_H - ((price - minP + pad) / (range + pad * 2)) * INNER_H;
  }

  // Build path strings
  function buildPath(prices: { elapsed_pct: number; price: number | null }[]): string {
    const valid = prices.filter((p) => p.price !== null);
    if (valid.length === 0) return "";
    return valid
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.elapsed_pct)},${y(p.price!)}`)
      .join(" ");
  }

  const upPath = buildPath(currentSnapshots.map((s) => ({ elapsed_pct: s.elapsed_pct, price: s.up_ask })));
  const downPath = buildPath(currentSnapshots.map((s) => ({ elapsed_pct: s.elapsed_pct, price: s.down_ask })));

  return (
    <div className="rounded-lg bg-[#0d1017] p-4">
      <h2 className="mb-2 font-mono text-sm font-semibold text-white/70">
        Current Bet — {currentCandleId.split("-").pop()}
      </h2>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {/* X-axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((pct) => (
          <text
            key={pct}
            x={x(pct)}
            y={H - 4}
            fill="white"
            fillOpacity={0.3}
            fontSize={9}
            textAnchor="middle"
            fontFamily="monospace"
          >
            {`${Math.round(pct * 5)}:00`}
          </text>
        ))}

        {/* Grid */}
        {[0.25, 0.5, 0.75].map((pct) => (
          <line
            key={pct}
            x1={x(pct)}
            x2={x(pct)}
            y1={PAD.top}
            y2={PAD.top + INNER_H}
            stroke="white"
            strokeOpacity={0.05}
          />
        ))}

        {/* UP price line (green) */}
        {upPath && (
          <path d={upPath} fill="none" stroke={THEME.colors.green} strokeWidth={1.5} strokeOpacity={0.8} />
        )}

        {/* DOWN price line (red) */}
        {downPath && (
          <path d={downPath} fill="none" stroke={THEME.colors.red} strokeWidth={1.5} strokeOpacity={0.8} />
        )}

        {/* Model entry markers */}
        {currentEntries.map((entry, i) => {
          const color = MODEL_COLORS[entry.model] ?? "#888";
          const short = MODEL_SHORT[entry.model] ?? entry.model;
          const entryY = entry.direction === "UP"
            ? y(entry.price)
            : y(entry.price);
          const cx = x(entry.elapsed_pct);

          return (
            <g key={`${entry.model}-${entry.checkpoint}-${i}`}>
              {/* Marker dot */}
              <circle cx={cx} cy={entryY} r={5} fill={color} stroke="white" strokeWidth={1} />
              {/* Label */}
              <text
                x={cx}
                y={entryY - 10}
                fill={color}
                fontSize={8}
                textAnchor="middle"
                fontFamily="monospace"
                fontWeight="bold"
              >
                {short} {entry.direction}
              </text>
              {/* Confidence + inference */}
              <text
                x={cx}
                y={entryY + 14}
                fill="white"
                fillOpacity={0.4}
                fontSize={7}
                textAnchor="middle"
                fontFamily="monospace"
              >
                {(entry.confidence * 100).toFixed(0)}% · {entry.inference_ms.toFixed(1)}ms
              </text>
            </g>
          );
        })}

        {/* Legend */}
        <text x={PAD.left} y={12} fill={THEME.colors.green} fontSize={9} fontFamily="monospace">
          UP
        </text>
        <text x={PAD.left + 30} y={12} fill={THEME.colors.red} fontSize={9} fontFamily="monospace">
          DOWN
        </text>
      </svg>
    </div>
  );
}
```

- [ ] **Step 2: Create BetPnlPanel.tsx**

```typescript
"use client";

import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT } from "@/lib/constants";
import { AnimatedNumber } from "@/components/shared/AnimatedNumber";

export function BetPnlPanel() {
  const { currentEntries, latestSnapshot } = useDashboard();

  // Group entries by model
  const byModel = new Map<string, typeof currentEntries>();
  for (const entry of currentEntries) {
    const list = byModel.get(entry.model) ?? [];
    list.push(entry);
    byModel.set(entry.model, list);
  }

  if (byModel.size === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg bg-[#0d1017] p-4 text-white/30 font-mono text-sm">
        No entries yet
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-[#0d1017] p-4">
      <h2 className="mb-3 font-mono text-sm font-semibold text-white/70">
        Open Positions
      </h2>
      <div className="space-y-3">
        {Array.from(byModel.entries()).map(([model, entries]) => {
          const color = MODEL_COLORS[model] ?? "#888";
          const short = MODEL_SHORT[model] ?? model;
          const direction = entries[0]?.direction ?? "—";
          const totalCost = entries.reduce((sum, e) => sum + e.amount_usd, 0);

          // Estimate unrealized PnL from current ask price
          let unrealized = 0;
          if (latestSnapshot) {
            const currentAsk =
              direction === "UP"
                ? latestSnapshot.up_asks?.[0]?.[0]
                : latestSnapshot.down_asks?.[0]?.[0];
            if (currentAsk && currentAsk > 0) {
              // Simplified: shares * (1 - ask) if winning, -(cost) if losing
              for (const e of entries) {
                const shares = e.amount_usd / e.price;
                unrealized += shares * (1 - currentAsk) - (e.amount_usd - shares * currentAsk);
              }
            }
          }

          const isPositive = unrealized >= 0;

          return (
            <div
              key={model}
              className="rounded border border-white/5 p-2"
              style={{ borderLeftColor: color, borderLeftWidth: 3 }}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-bold" style={{ color }}>
                  {short}
                </span>
                <span
                  className={`font-mono text-xs font-bold ${isPositive ? "text-green-400" : "text-red-400"}`}
                >
                  {isPositive ? "+" : ""}
                  <AnimatedNumber value={unrealized} decimals={2} prefix="$" />
                </span>
              </div>
              <div className="mt-1 flex gap-3 font-mono text-[10px] text-white/40">
                <span>{direction}</span>
                <span>{entries.length} entry{entries.length > 1 ? "s" : ""}</span>
                <span>${totalCost.toFixed(2)} wagered</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
mkdir -p dashboard-next/src/components/current-bet
git add dashboard-next/src/components/current-bet/
git commit -m "feat(dashboard): Section 2 — BetTimeline + BetPnlPanel"
```

---

### Task 6: Section 3 — EquityChart + PortfolioCards

**Files:**
- Create: `dashboard-next/src/components/portfolios/EquityChart.tsx`
- Create: `dashboard-next/src/components/portfolios/PortfolioCards.tsx`

- [ ] **Step 1: Create EquityChart.tsx**

```typescript
"use client";

import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS } from "@/lib/constants";

const W = 900;
const H = 180;
const PAD = { top: 15, right: 10, bottom: 20, left: 50 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

export function EquityChart() {
  const { equityHistory } = useDashboard();

  const models = Object.keys(equityHistory);
  if (models.length === 0) {
    return (
      <div className="flex h-44 items-center justify-center rounded-lg bg-[#0d1017] text-white/30 font-mono text-sm">
        Waiting for settlements...
      </div>
    );
  }

  const allValues = models.flatMap((m) => equityHistory[m]);
  const maxLen = Math.max(...models.map((m) => equityHistory[m].length));
  const minV = Math.min(1000, ...allValues);
  const maxV = Math.max(1000, ...allValues);
  const range = maxV - minV || 1;
  const pad = range * 0.1;

  function x(i: number): number {
    return PAD.left + (maxLen > 1 ? (i / (maxLen - 1)) * INNER_W : INNER_W / 2);
  }
  function y(val: number): number {
    return PAD.top + INNER_H - ((val - minV + pad) / (range + pad * 2)) * INNER_H;
  }

  // $1000 reference line
  const refY = y(1000);

  return (
    <div className="rounded-lg bg-[#0d1017] p-4">
      <h2 className="mb-2 font-mono text-sm font-semibold text-white/70">
        Portfolio Equity
      </h2>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 180 }}>
        {/* $1000 reference */}
        <line
          x1={PAD.left} x2={W - PAD.right}
          y1={refY} y2={refY}
          stroke="white" strokeOpacity={0.1} strokeDasharray="4 2"
        />
        <text x={PAD.left - 4} y={refY + 3} fill="white" fillOpacity={0.3} fontSize={9} textAnchor="end" fontFamily="monospace">
          $1000
        </text>

        {/* Equity lines */}
        {models.map((model) => {
          const data = equityHistory[model];
          if (data.length < 2) return null;
          const path = data
            .map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`)
            .join(" ");
          const color = MODEL_COLORS[model] ?? "#888";
          const last = data[data.length - 1];
          return (
            <g key={model}>
              <path d={path} fill="none" stroke={color} strokeWidth={2} />
              {/* End label */}
              <text
                x={x(data.length - 1) + 4}
                y={y(last)}
                fill={color}
                fontSize={9}
                fontFamily="monospace"
                dominantBaseline="middle"
              >
                ${last.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* X-axis */}
        <text x={PAD.left} y={H - 3} fill="white" fillOpacity={0.3} fontSize={8} fontFamily="monospace">
          Candle #1
        </text>
        <text x={W - PAD.right} y={H - 3} fill="white" fillOpacity={0.3} fontSize={8} textAnchor="end" fontFamily="monospace">
          #{maxLen}
        </text>
      </svg>
    </div>
  );
}
```

- [ ] **Step 2: Create PortfolioCards.tsx**

```typescript
"use client";

import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT } from "@/lib/constants";
import { AnimatedNumber } from "@/components/shared/AnimatedNumber";

export function PortfolioCards() {
  const { portfolios } = useDashboard();

  const models = ["LogisticRegression", "RandomForest", "XGBoost"];

  return (
    <div className="grid grid-cols-3 gap-3">
      {models.map((model) => {
        const p = portfolios[model];
        if (!p) return null;
        const color = MODEL_COLORS[model] ?? "#888";
        const short = MODEL_SHORT[model] ?? model;
        const isPositive = p.total_return_pct >= 0;

        return (
          <div
            key={model}
            className="rounded-lg bg-[#0d1017] p-4"
            style={{ borderTop: `2px solid ${color}` }}
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="font-mono text-sm font-bold" style={{ color }}>
                {short}
              </span>
              <span
                className={`font-mono text-xs ${isPositive ? "text-green-400" : "text-red-400"}`}
              >
                {isPositive ? "+" : ""}
                {p.total_return_pct.toFixed(1)}%
              </span>
            </div>
            <div className="space-y-1 font-mono text-xs text-white/50">
              <div className="flex justify-between">
                <span>Balance</span>
                <span className="text-white">
                  $<AnimatedNumber value={p.final_balance} decimals={2} />
                </span>
              </div>
              <div className="flex justify-between">
                <span>W / L</span>
                <span className="text-white">
                  {p.wins} / {p.losses}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Win Rate</span>
                <span className="text-white">
                  {(p.win_rate * 100).toFixed(1)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span>PnL</span>
                <span className={isPositive ? "text-green-400" : "text-red-400"}>
                  {isPositive ? "+" : ""}$
                  <AnimatedNumber value={p.net_pnl} decimals={2} />
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
mkdir -p dashboard-next/src/components/portfolios
git add dashboard-next/src/components/portfolios/
git commit -m "feat(dashboard): Section 3 — EquityChart + PortfolioCards"
```

---

### Task 7: Section 4 — BetList + BetDetail

**Files:**
- Create: `dashboard-next/src/components/history/BetList.tsx`
- Create: `dashboard-next/src/components/history/BetDetail.tsx`

- [ ] **Step 1: Create BetList.tsx**

```typescript
"use client";

import { useState } from "react";
import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT, THEME } from "@/lib/constants";
import { BetDetail } from "./BetDetail";
import type { PastBet } from "@/lib/types";

export function BetList() {
  const { pastBets } = useDashboard();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (pastBets.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center rounded-lg bg-[#0d1017] text-white/30 font-mono text-sm">
        No resolved bets yet
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-[#0d1017] p-4">
      <h2 className="mb-3 font-mono text-sm font-semibold text-white/70">
        Previous Bets
      </h2>
      <div className="space-y-1">
        {pastBets.map((bet) => (
          <BetRow
            key={bet.candle_id}
            bet={bet}
            expanded={expandedId === bet.candle_id}
            onToggle={() =>
              setExpandedId(
                expandedId === bet.candle_id ? null : bet.candle_id,
              )
            }
          />
        ))}
      </div>
    </div>
  );
}

function BetRow({
  bet,
  expanded,
  onToggle,
}: {
  bet: PastBet;
  expanded: boolean;
  onToggle: () => void;
}) {
  const models = ["LogisticRegression", "RandomForest", "XGBoost"];
  const ts = new Date(bet.timestamp * 1000);
  const time = ts.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  const outcomeColor =
    bet.outcome === "UP" ? THEME.colors.green : THEME.colors.red;

  return (
    <div>
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 rounded px-3 py-2 text-left font-mono text-xs hover:bg-white/5 transition-colors"
      >
        <span className="text-white/40 w-12">{time}</span>
        <span
          className="w-10 rounded px-1.5 py-0.5 text-center text-[10px] font-bold"
          style={{ backgroundColor: outcomeColor + "20", color: outcomeColor }}
        >
          {bet.outcome}
        </span>
        {models.map((model) => {
          const s = bet.settlements[model as keyof typeof bet.settlements];
          if (!s) return <span key={model} className="w-20 text-white/20">—</span>;
          const color = MODEL_COLORS[model] ?? "#888";
          const short = MODEL_SHORT[model] ?? model;
          return (
            <span key={model} className="w-20 flex items-center gap-1">
              <span style={{ color }} className="font-bold">
                {short}
              </span>
              <span className={s.won ? "text-green-400" : "text-red-400"}>
                {s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(2)}
              </span>
            </span>
          );
        })}
        <span className="ml-auto text-white/20">{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && <BetDetail bet={bet} />}
    </div>
  );
}
```

- [ ] **Step 2: Create BetDetail.tsx**

This reuses the same timeline chart pattern as BetTimeline but for historical data.

```typescript
"use client";

import { MODEL_COLORS, MODEL_SHORT, THEME } from "@/lib/constants";
import type { PastBet } from "@/lib/types";

const W = 700;
const H = 140;
const PAD = { top: 15, right: 10, bottom: 20, left: 35 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

export function BetDetail({ bet }: { bet: PastBet }) {
  const { snapshots, entries } = bet;

  if (snapshots.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-white/30 font-mono">
        No snapshot data for this candle
      </div>
    );
  }

  const upPrices = snapshots.map((s) => s.up_ask).filter((p): p is number => p !== null);
  const downPrices = snapshots.map((s) => s.down_ask).filter((p): p is number => p !== null);
  const allPrices = [...upPrices, ...downPrices];
  const minP = allPrices.length > 0 ? Math.min(...allPrices) : 0;
  const maxP = allPrices.length > 0 ? Math.max(...allPrices) : 1;
  const range = maxP - minP || 0.1;
  const pad = range * 0.1;

  function x(elapsed: number): number {
    return PAD.left + Math.min(elapsed, 1) * INNER_W;
  }
  function y(price: number): number {
    return PAD.top + INNER_H - ((price - minP + pad) / (range + pad * 2)) * INNER_H;
  }

  function buildPath(prices: { elapsed_pct: number; price: number | null }[]): string {
    const valid = prices.filter((p) => p.price !== null);
    if (valid.length === 0) return "";
    return valid
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.elapsed_pct)},${y(p.price!)}`)
      .join(" ");
  }

  const upPath = buildPath(snapshots.map((s) => ({ elapsed_pct: s.elapsed_pct, price: s.up_ask })));
  const downPath = buildPath(snapshots.map((s) => ({ elapsed_pct: s.elapsed_pct, price: s.down_ask })));

  const outcomeColor = bet.outcome === "UP" ? THEME.colors.green : THEME.colors.red;

  return (
    <div className="mx-3 mb-2 rounded bg-[#131720] p-3">
      <div className="mb-1 flex items-center gap-2 font-mono text-[10px] text-white/40">
        <span>Outcome:</span>
        <span style={{ color: outcomeColor }} className="font-bold">
          {bet.outcome}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {/* Grid */}
        {[0.25, 0.5, 0.75].map((pct) => (
          <line
            key={pct}
            x1={x(pct)} x2={x(pct)}
            y1={PAD.top} y2={PAD.top + INNER_H}
            stroke="white" strokeOpacity={0.05}
          />
        ))}

        {upPath && <path d={upPath} fill="none" stroke={THEME.colors.green} strokeWidth={1.5} strokeOpacity={0.7} />}
        {downPath && <path d={downPath} fill="none" stroke={THEME.colors.red} strokeWidth={1.5} strokeOpacity={0.7} />}

        {/* Model entry markers */}
        {entries.map((entry, i) => {
          const color = MODEL_COLORS[entry.model] ?? "#888";
          const short = MODEL_SHORT[entry.model] ?? entry.model;
          const cy = y(entry.price);
          const cx = x(entry.elapsed_pct);
          return (
            <g key={`${entry.model}-${entry.checkpoint}-${i}`}>
              <circle cx={cx} cy={cy} r={4} fill={color} stroke="white" strokeWidth={0.5} />
              <text x={cx} y={cy - 8} fill={color} fontSize={7} textAnchor="middle" fontFamily="monospace" fontWeight="bold">
                {short}
              </text>
            </g>
          );
        })}

        {/* X-axis */}
        {[0, 0.5, 1].map((pct) => (
          <text key={pct} x={x(pct)} y={H - 3} fill="white" fillOpacity={0.3} fontSize={8} textAnchor="middle" fontFamily="monospace">
            {`${Math.round(pct * 5)}:00`}
          </text>
        ))}
      </svg>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
mkdir -p dashboard-next/src/components/history
git add dashboard-next/src/components/history/
git commit -m "feat(dashboard): Section 4 — BetList + BetDetail"
```

---

### Task 8: Main page + cleanup

**Files:**
- Rewrite: `dashboard-next/src/app/page.tsx`
- Delete: legacy components, pages, hooks

- [ ] **Step 1: Delete legacy files**

```bash
rm -rf dashboard-next/src/components/trading
rm -rf dashboard-next/src/components/status
rm -rf dashboard-next/src/components/candles
rm -rf dashboard-next/src/app/status
rm -rf dashboard-next/src/app/history
rm -rf dashboard-next/src/app/forensics
rm -rf dashboard-next/src/app/api
rm -f dashboard-next/src/hooks/useTradingData.ts
rm -f dashboard-next/src/hooks/useStatusData.ts
rm -f dashboard-next/src/hooks/useFallbackData.ts
rm -f dashboard-next/src/components/shared/StatusBadge.tsx
rm -f dashboard-next/src/components/shared/ConnectionStatus.tsx
```

- [ ] **Step 2: Rewrite page.tsx**

```typescript
import { CandleChart } from "@/components/candles/CandleChart";
import { BetTimeline } from "@/components/current-bet/BetTimeline";
import { BetPnlPanel } from "@/components/current-bet/BetPnlPanel";
import { EquityChart } from "@/components/portfolios/EquityChart";
import { PortfolioCards } from "@/components/portfolios/PortfolioCards";
import { BetList } from "@/components/history/BetList";

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      {/* Section 1: Candle History */}
      <CandleChart />

      {/* Section 2: Current Bet */}
      <div className="grid grid-cols-[1fr_280px] gap-4">
        <BetTimeline />
        <BetPnlPanel />
      </div>

      {/* Section 3: Portfolio Comparison */}
      <EquityChart />
      <PortfolioCards />

      {/* Section 4: Previous Bets */}
      <BetList />
    </div>
  );
}
```

- [ ] **Step 3: Update layout.tsx if needed**

Verify `layout.tsx` wraps children with `AppShell`. It should already do this from the existing codebase. If not, ensure:

```typescript
import { AppShell } from "@/components/layout/AppShell";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
```

- [ ] **Step 4: Verify build**

```bash
cd dashboard-next && npm run build
```

Fix any TypeScript or import errors.

- [ ] **Step 5: Commit**

```bash
git add -A dashboard-next/
git commit -m "feat(dashboard): rewrite main page with 4-section multi-model layout"
```

---

### Task 9: Smoke test — verify with live bot

- [ ] **Step 1: Start the polybot** (if not already running)

```bash
uv run python -m polybot
```

Verify logs show 3 model runners loading.

- [ ] **Step 2: Start the dashboard**

```bash
cd dashboard-next && npm run dev
```

Open `http://localhost:3000`.

- [ ] **Step 3: Verify each section**

- Section 1: Candle chart shows bars as candles close
- Section 2: UP/DOWN price lines update in real-time, model entry markers appear
- Section 3: Equity curves grow on each settlement, portfolio cards update
- Section 4: Past bets accumulate after candle_close, expandable

- [ ] **Step 4: Fix any issues found during smoke test**

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "fix(dashboard): smoke test fixes"
```
