"use client";

import { useState, useMemo, useEffect, useRef } from "react";
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
  const prevCountRef = useRef(slugs.length);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Auto-select the most recent candle (last key)
  const [selectedSlug, setSelectedSlug] = useState<string | null>(
    slugs.length > 0 ? slugs[slugs.length - 1] : null,
  );

  // Auto-select latest candle when a new one appears
  useEffect(() => {
    if (slugs.length > prevCountRef.current) {
      const latest = slugs[slugs.length - 1];
      setSelectedSlug(latest);
      // Scroll the card row to the right end
      requestAnimationFrame(() => {
        if (scrollContainerRef.current) {
          scrollContainerRef.current.scrollTo({
            left: scrollContainerRef.current.scrollWidth,
            behavior: "smooth",
          });
        }
      });
    }
    prevCountRef.current = slugs.length;
  }, [slugs]);

  // If the previously selected slug is gone, fall back to most recent
  const activeSlug =
    selectedSlug && snapshots[selectedSlug]
      ? selectedSlug
      : slugs.length > 0
        ? slugs[slugs.length - 1]
        : null;

  // All entries per candle (including HOLDs — for chart markers and detail list)
  const allBySlug = useMemo(() => {
    if (!trades) return {};
    const map: Record<string, TradeEntry[]> = {};
    for (const t of trades) {
      if (t.candle_slug && isFullTrade(t)) {
        (map[t.candle_slug] ??= []).push(t);
      }
    }
    return map;
  }, [trades]);

  // Trade counts exclude HOLDs (for badge display)
  const tradeCountBySlug = useMemo(() => {
    const map: Record<string, number> = {};
    for (const [slug, entries] of Object.entries(allBySlug)) {
      const count = entries.filter((t) => t.action !== "HOLD").length;
      if (count > 0) map[slug] = count;
    }
    return map;
  }, [allBySlug]);

  const activeTrades = activeSlug ? (allBySlug[activeSlug] ?? []) : [];

  if (slugs.length === 0) return null;

  return (
    <div className="space-y-4">
      {/* Section label */}
      <h2 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Candle Timeline
      </h2>

      {/* Horizontal scroll row of cards */}
      <div ref={scrollContainerRef} className="flex gap-3 overflow-x-auto pb-1">
        {slugs.map((slug) => (
          <CandleCard
            key={slug}
            slug={slug}
            candle={snapshots[slug]}
            selected={slug === activeSlug}
            onClick={() => setSelectedSlug(slug)}
            tradeCount={tradeCountBySlug[slug]}
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
