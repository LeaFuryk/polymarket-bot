"use client";

import { useState, useMemo } from "react";
import { CandleSnapshots, TradeEntry, TradeEvent } from "@/lib/types";
import { CandleCard } from "./CandleCard";
import { CandleDetail } from "./CandleDetail";

type TradeItem = TradeEntry | TradeEvent;

function isFullTrade(t: TradeItem): t is TradeEntry {
  return "cycle" in t;
}

interface CandleTimelineProps {
  snapshots: CandleSnapshots;
  trades?: TradeItem[];
}

export function CandleTimeline({ snapshots, trades }: CandleTimelineProps) {
  const slugs = useMemo(() => Object.keys(snapshots), [snapshots]);

  // Auto-select the most recent candle (last key)
  const [selectedSlug, setSelectedSlug] = useState<string | null>(
    slugs.length > 0 ? slugs[slugs.length - 1] : null,
  );

  // If the previously selected slug is gone, fall back to most recent
  const activeSlug =
    selectedSlug && snapshots[selectedSlug]
      ? selectedSlug
      : slugs.length > 0
        ? slugs[slugs.length - 1]
        : null;

  // Compute trade counts per candle (only full TradeEntry items have position data)
  const tradesBySlug = useMemo(() => {
    if (!trades) return {};
    const map: Record<string, TradeEntry[]> = {};
    for (const t of trades) {
      if (t.candle_slug && isFullTrade(t)) {
        (map[t.candle_slug] ??= []).push(t);
      }
    }
    return map;
  }, [trades]);

  const activeTrades = activeSlug ? (tradesBySlug[activeSlug] ?? []) : [];

  if (slugs.length === 0) return null;

  return (
    <div className="space-y-4">
      {/* Section label */}
      <h2 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Candle Timeline
      </h2>

      {/* Horizontal scroll row of cards */}
      <div className="flex gap-3 overflow-x-auto pb-1">
        {slugs.map((slug) => (
          <CandleCard
            key={slug}
            slug={slug}
            candle={snapshots[slug]}
            selected={slug === activeSlug}
            onClick={() => setSelectedSlug(slug)}
            tradeCount={tradesBySlug[slug]?.length}
          />
        ))}
      </div>

      {/* Detail panel for selected candle */}
      {activeSlug && (
        <CandleDetail
          slug={activeSlug}
          candle={snapshots[activeSlug]}
          trades={activeTrades.length > 0 ? activeTrades : undefined}
        />
      )}
    </div>
  );
}
