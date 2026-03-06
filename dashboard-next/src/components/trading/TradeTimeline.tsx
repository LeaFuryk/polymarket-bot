"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/shared/StatusBadge";
import {
  formatCurrency,
  formatTime,
  formatCandleSlug,
  formatFillSource,
} from "@/lib/format";
import type { TradeEntry, TradeEvent } from "@/lib/types";

type TradeItem = TradeEntry | TradeEvent;

interface TradeTimelineProps {
  trades: TradeItem[];
  maxItems?: number;
}

function isFull(t: TradeItem): t is TradeEntry {
  return "cycle" in t;
}

export function TradeTimeline({ trades, maxItems = 20 }: TradeTimelineProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  const displayed = trades.slice(-maxItems).reverse();

  if (displayed.length === 0) {
    return (
      <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          Trades
        </h3>
        <div className="text-sm text-zinc-600">No trades yet</div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Trades ({trades.filter((t) => t.action !== "HOLD").length})
      </h3>
      <div className="max-h-[400px] space-y-2 overflow-y-auto pr-1">
        {displayed.map((t, i) => {
          const actionColor =
            t.action === "BUY" ? "green" : t.action === "SELL" ? "red" : "zinc";
          const sideColor = t.token_side === "up" ? "green" : "red";

          return (
            <div
              key={`${t.timestamp}-${i}`}
              className={`rounded border border-white/5 bg-[#0d1017] p-3 ${
                t.risk_blocked ? "opacity-40" : ""
              }`}
            >
              <div className="mb-1 flex items-center justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge label={t.action} variant={actionColor} />
                  <StatusBadge label={t.token_side} variant={sideColor} />
                  {t.risk_blocked && (
                    <StatusBadge label="BLOCKED" variant="red" />
                  )}
                  {t.live_order && (
                    <StatusBadge
                      label={t.live_order.fill_source ? "FILLED" : "TIMEOUT"}
                      variant={t.live_order.fill_source ? "green" : "amber"}
                    />
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {t.candle_slug && (
                    <span className="font-mono text-[10px] text-cyan-400/70">
                      {formatCandleSlug(t.candle_slug)}
                    </span>
                  )}
                  <span className="font-mono text-[11px] text-zinc-500">
                    {formatTime(t.timestamp)}
                  </span>
                </div>
              </div>
              <div className="mt-2 grid grid-cols-4 gap-2 text-xs">
                <div>
                  <span className="text-zinc-500">Price: </span>
                  <span className="font-mono text-zinc-300">
                    {t.fill_price ? `$${t.fill_price.toFixed(4)}` : "---"}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-500">Size: </span>
                  <span className="font-mono text-zinc-300">
                    {t.size?.toFixed(2) ?? "---"}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-500">Conf: </span>
                  <span className="font-mono text-zinc-300">
                    {(t.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                {isFull(t) && t.midpoint_gap != null && (
                  <div>
                    <span className="text-zinc-500">Gap: </span>
                    <span
                      className={`font-mono ${
                        Math.abs(t.midpoint_gap) > 0.03
                          ? "text-amber-400"
                          : "text-zinc-300"
                      }`}
                    >
                      {t.midpoint_gap > 0 ? "+" : ""}
                      {(t.midpoint_gap * 100).toFixed(1)}%
                    </span>
                  </div>
                )}
              </div>
              {t.live_order && (
                <div className="mt-1.5 grid grid-cols-4 gap-2 border-t border-white/5 pt-1.5 text-xs">
                  <div>
                    <span className="text-zinc-500">Source: </span>
                    <span className="font-mono text-zinc-300">
                      {formatFillSource(t.live_order.fill_source)}
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-500">Matched: </span>
                    <span className="font-mono text-zinc-300">
                      {t.live_order.size_matched?.toFixed(2) ?? "---"}
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-500">Limit: </span>
                    <span className="font-mono text-zinc-300">
                      ${t.live_order.limit_price?.toFixed(4) ?? "---"}
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-500">TTL: </span>
                    <span className="font-mono text-zinc-300">
                      {t.live_order.ttl_used
                        ? `${t.live_order.ttl_used.toFixed(1)}s`
                        : "---"}
                    </span>
                  </div>
                </div>
              )}
              {t.reasoning && (
                <div className="mt-2">
                  <div
                    className={`text-[11px] text-zinc-500 ${
                      expandedIndex === i ? "" : "line-clamp-2"
                    }`}
                  >
                    {t.reasoning}
                  </div>
                  {t.reasoning.length > 120 && (
                    <button
                      onClick={() =>
                        setExpandedIndex(expandedIndex === i ? null : i)
                      }
                      className="mt-1 text-[10px] text-zinc-600 hover:text-zinc-400"
                    >
                      {expandedIndex === i ? "Show less" : "Show more"}
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
