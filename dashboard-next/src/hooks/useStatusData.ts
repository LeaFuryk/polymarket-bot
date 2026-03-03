"use client";

import { useMemo } from "react";
import type { WSData } from "./useWebSocket";

/** Derive tech/status metrics from WS data. */
export function useStatusData(ws: WSData) {
  const { snapshot, status } = ws;

  const infra = useMemo(() => {
    const s = status ?? null;
    const snap = snapshot ?? null;
    return {
      api_latencies: s?.api_latencies ?? {},
      ws_clients: s?.ws_clients ?? snap?.ws_clients ?? 0,
      sqlite_queue_depth: s?.sqlite_queue_depth ?? 0,
      prefilter: s?.prefilter ?? {
        skip_rate: snap?.session?.prefilter_skip_rate ?? 0,
        skipped: snap?.session?.prefilter_skipped ?? 0,
        checked: snap?.session?.prefilter_checked ?? 0,
      },
      monitor: s?.monitor ?? snap?.monitor ?? null,
    };
  }, [status, snapshot]);

  const execution = useMemo(() => {
    const s = status ?? null;
    const snap = snapshot ?? null;
    return {
      risk: s?.risk ?? snap?.risk ?? null,
      ensemble: s?.ensemble ?? snap?.ensemble ?? null,
      ai_cooldown:
        s?.monitor?.ai_cooldown_remaining ??
        snap?.monitor?.ai_cooldown_remaining ??
        0,
      last_trigger:
        s?.monitor?.last_trigger_reason ??
        snap?.monitor?.last_trigger_reason ??
        "",
      gate_pipeline: s?.monitor?.status ?? snap?.monitor?.status ?? {},
    };
  }, [status, snapshot]);

  return { infra, execution };
}
