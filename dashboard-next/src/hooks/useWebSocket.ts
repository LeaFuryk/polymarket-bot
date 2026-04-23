"use client";

import { useEffect, useRef, useState } from "react";
import type {
  CandleClose,
  CandleCorrection,
  InitialState,
  ModelEntry,
  ModelSettlement,
  PortfolioSummary,
  Snapshot,
  SnapshotPoint,
  PastBet,
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
const INITIAL_CASH = 1000; // default, overridden by initial_state

export function useWebSocket(url: string = WS_URL): DashboardData {
  const [wsState, setWsState] = useState<WSState>("disconnected");
  const [candles, setCandles] = useState<CandleClose[]>([]);
  const [currentCandleId, setCurrentCandleId] = useState<string | null>(null);
  const [currentSnapshots, setCurrentSnapshots] = useState<SnapshotPoint[]>([]);
  const [currentEntries, setCurrentEntries] = useState<ModelEntry[]>([]);
  const [portfolios, setPortfolios] = useState<
    Record<string, PortfolioSummary>
  >({});
  const [equityHistory, setEquityHistory] = useState<Record<string, number[]>>(
    {},
  );
  const [pastBets, setPastBets] = useState<PastBet[]>([]);
  const [latestSnapshot, setLatestSnapshot] = useState<Snapshot | null>(null);

  // Refs to avoid stale closures — these track current candle data for past bet creation
  const currentEntriesRef = useRef<ModelEntry[]>([]);
  const currentSnapshotsRef = useRef<SnapshotPoint[]>([]);
  const currentCandleIdRef = useRef<string | null>(null);
  const initialCashRef = useRef<number>(INITIAL_CASH);

  // Buffer: store entries/snapshots per candle_id for settlements that arrive after candle_close
  const candleBufferRef = useRef<
    Map<string, { entries: ModelEntry[]; snapshots: SnapshotPoint[] }>
  >(new Map());

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
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(raw) as Record<string, unknown>;
      } catch {
        return; // ignore malformed JSON
      }

      const type = msg.type as string | undefined;
      if (!type) return;

      // Type casts below are safe: messages come from our own polybot WS,
      // and each branch only runs when `type` matches the expected shape.
      // Full runtime validation (e.g. zod) would be warranted for external feeds.
      switch (type) {
        case "initial_state": {
          const init = msg as unknown as InitialState;
          setCandles(init.candles ?? []);
          setPortfolios(init.portfolios ?? {});

          // Store initial_cash for PnL calculations
          const firstPortfolio = Object.values(init.portfolios ?? {})[0];
          if (firstPortfolio?.initial_cash) {
            initialCashRef.current = firstPortfolio.initial_cash;
          }

          // Hydrate full equity history from server (survives refresh)
          if (init.equity_history) {
            setEquityHistory(init.equity_history);
          } else {
            // Fallback: just current balance
            const hist: Record<string, number[]> = {};
            for (const [model, p] of Object.entries(init.portfolios ?? {})) {
              hist[model] = [p.final_balance];
            }
            setEquityHistory(hist);
          }

          // Hydrate current candle state from snapshots_so_far (or reset if empty)
          if (init.snapshots_so_far?.length > 0) {
            const firstSnap = init.snapshots_so_far[0];
            currentCandleIdRef.current = firstSnap.candle_id;
            setCurrentCandleId(firstSnap.candle_id);

            const points = init.snapshots_so_far.map((s) => ({
              elapsed_pct: s.elapsed_pct,
              timestamp: s.timestamp,
              up_ask: s.up_asks?.[0]?.[0] ?? null,
              down_ask: s.down_asks?.[0]?.[0] ?? null,
              btc_price: s.btc_price,
            }));
            currentSnapshotsRef.current = points;
            setCurrentSnapshots(points);
            setLatestSnapshot(
              init.snapshots_so_far[init.snapshots_so_far.length - 1],
            );
          } else {
            // No active candle — clear stale state
            currentCandleIdRef.current = null;
            currentSnapshotsRef.current = [];
            setCurrentCandleId(null);
            setCurrentSnapshots([]);
            setLatestSnapshot(null);
          }

          // Hydrate current entries from initial_state (or reset if empty)
          if (init.current_entries?.length) {
            currentEntriesRef.current = init.current_entries;
            setCurrentEntries(init.current_entries);
          } else {
            currentEntriesRef.current = [];
            setCurrentEntries([]);
          }
          break;
        }
        case "snapshot": {
          const snap = msg as unknown as Snapshot;
          setLatestSnapshot(snap);

          if (snap.candle_id !== currentCandleIdRef.current) {
            // Save buffer for the previous candle before switching
            // (only if there was a previous candle with data — skip the null→new transition)
            const prevId = currentCandleIdRef.current;
            if (prevId && currentSnapshotsRef.current.length > 0) {
              candleBufferRef.current.set(prevId, {
                entries: [...currentEntriesRef.current],
                snapshots: [...currentSnapshotsRef.current],
              });
            }
            currentCandleIdRef.current = snap.candle_id;
            currentSnapshotsRef.current = [];
            // Preserve entries that were already received for this new candle
            const keptEntries = currentEntriesRef.current.filter(
              (e) => e.candle_id === snap.candle_id,
            );
            currentEntriesRef.current = keptEntries;
            setCurrentCandleId(snap.candle_id);
            setCurrentEntries(keptEntries);
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
          const entry = msg as unknown as ModelEntry;
          // If entry arrives for a candle we haven't seen a snapshot for yet,
          // set it as current so the snapshot handler doesn't clear it
          if (!currentCandleIdRef.current && entry.candle_id) {
            currentCandleIdRef.current = entry.candle_id;
            setCurrentCandleId(entry.candle_id);
          }
          // Only add to current candle if candle_id matches
          if (entry.candle_id === currentCandleIdRef.current) {
            currentEntriesRef.current = [...currentEntriesRef.current, entry];
            setCurrentEntries([...currentEntriesRef.current]);
          }
          break;
        }
        case "model_settlement": {
          const settlement = msg as unknown as ModelSettlement;
          const ic = initialCashRef.current;

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
              net_pnl: settlement.cash - ic,
              total_return_pct: ((settlement.cash - ic) / ic) * 100,
            },
          }));

          setEquityHistory((prev) => ({
            ...prev,
            [settlement.model]: [
              ...(prev[settlement.model] ?? []),
              settlement.cash,
            ],
          }));

          // Get entries/snapshots from current refs or from the candle buffer
          const buffered = candleBufferRef.current.get(settlement.candle_id);
          const entriesForCandle =
            buffered?.entries ??
            [...currentEntriesRef.current].filter(
              (e) => e.candle_id === settlement.candle_id,
            );
          const snapshotsForCandle = buffered?.snapshots ?? [
            ...currentSnapshotsRef.current,
          ];

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
                entries: entriesForCandle,
                settlements: { [settlement.model]: settlement },
                snapshots: snapshotsForCandle,
              },
              ...prev,
            ].slice(0, MAX_PAST_BETS);
          });
          break;
        }
        case "candle_close": {
          const candle = msg as unknown as CandleClose;
          setCandles((prev) => [...prev.slice(-19), candle]);

          // Save current candle data to buffer before clearing
          if (currentCandleIdRef.current) {
            candleBufferRef.current.set(currentCandleIdRef.current, {
              entries: [...currentEntriesRef.current],
              snapshots: [...currentSnapshotsRef.current],
            });
          }

          // Prune old buffer entries (keep last 10)
          if (candleBufferRef.current.size > 10) {
            const keys = Array.from(candleBufferRef.current.keys());
            for (const key of keys.slice(0, keys.length - 10)) {
              candleBufferRef.current.delete(key);
            }
          }

          currentCandleIdRef.current = null;
          currentSnapshotsRef.current = [];
          currentEntriesRef.current = [];
          setCurrentSnapshots([]);
          setCurrentEntries([]);
          setCurrentCandleId(null);
          break;
        }
        case "candle_correction": {
          const correction = msg as unknown as CandleCorrection;
          // Update full candle data (OHLC, outcome, final_ret)
          setCandles((prev) =>
            prev.map((c) =>
              c.candle_id === correction.candle_id
                ? {
                    ...c,
                    open: correction.open,
                    high: correction.high,
                    low: correction.low,
                    close: correction.close,
                    volume: correction.volume,
                    outcome: correction.outcome,
                    final_ret: correction.final_ret,
                  }
                : c,
            ),
          );
          // Update past bet outcome + invalidate settlement won/pnl
          setPastBets((prev) =>
            prev.map((b) => {
              if (b.candle_id !== correction.candle_id) return b;
              const updatedSettlements = { ...b.settlements };
              for (const [model, s] of Object.entries(updatedSettlements)) {
                if (s) {
                  updatedSettlements[model as keyof typeof updatedSettlements] =
                    {
                      ...s,
                      outcome: correction.outcome,
                      won: s.direction === correction.outcome,
                    };
                }
              }
              return {
                ...b,
                outcome: correction.outcome,
                settlements: updatedSettlements,
              };
            }),
          );
          break;
        }
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

      ws.onmessage = (event) => handleMessage(event.data as string);

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
