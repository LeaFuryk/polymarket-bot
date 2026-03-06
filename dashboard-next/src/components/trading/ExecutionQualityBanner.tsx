"use client";

import { useMemo } from "react";
import { formatFillSource } from "@/lib/format";
import type { TradeEntry, TradeEvent } from "@/lib/types";

type TradeItem = TradeEntry | TradeEvent;

interface ExecutionQualityBannerProps {
  trades: TradeItem[];
}

export function ExecutionQualityBanner({
  trades,
}: ExecutionQualityBannerProps) {
  const stats = useMemo(() => {
    const withLive = trades.filter((t) => t.live_order);
    if (withLive.length === 0) return null;

    const filled = withLive.filter((t) => t.live_order!.fill_source);
    const fillRate = filled.length / withLive.length;

    const bySource: Record<string, number> = {};
    for (const t of filled) {
      const src = t.live_order!.fill_source;
      bySource[src] = (bySource[src] ?? 0) + 1;
    }

    return {
      total: withLive.length,
      filled: filled.length,
      fillRate,
      bySource,
    };
  }, [trades]);

  if (!stats) return null;

  const rateColor =
    stats.fillRate >= 0.7
      ? "text-green-400"
      : stats.fillRate >= 0.4
        ? "text-amber-400"
        : "text-red-400";

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-lg border border-white/5 bg-[#131720] px-4 py-2">
      <span className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Fill Rate
      </span>
      <span className={`font-mono text-sm font-semibold ${rateColor}`}>
        {(stats.fillRate * 100).toFixed(0)}%
      </span>
      <span className="font-mono text-xs text-zinc-400">
        {stats.filled}/{stats.total} filled
      </span>
      {Object.entries(stats.bySource).map(([src, count]) => (
        <span key={src} className="text-[11px] text-zinc-500">
          {formatFillSource(src)}: {count}
        </span>
      ))}
    </div>
  );
}
