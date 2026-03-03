"use client";

import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatCurrency, formatTime } from "@/lib/format";
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
  const displayed = trades.slice(-maxItems).reverse();

  if (displayed.length === 0) {
    return (
      <div className="rounded-lg bg-[#131720] border border-white/5 p-4">
        <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-2">
          Trades
        </h3>
        <div className="text-zinc-600 text-sm">No trades yet</div>
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-[#131720] border border-white/5 p-4">
      <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-3">
        Trades ({trades.length})
      </h3>
      <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
        {displayed.map((t, i) => {
          const actionColor =
            t.action === "BUY" ? "green" : t.action === "SELL" ? "red" : "zinc";
          const sideColor =
            t.token_side === "up" ? "green" : "red";

          return (
            <div
              key={`${t.timestamp}-${i}`}
              className={`rounded bg-[#0d1017] border border-white/5 p-3 ${
                t.risk_blocked ? "opacity-40" : ""
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <StatusBadge label={t.action} variant={actionColor} />
                  <StatusBadge label={t.token_side} variant={sideColor} />
                  {t.risk_blocked && (
                    <StatusBadge label="BLOCKED" variant="red" />
                  )}
                </div>
                <span className="text-[11px] text-zinc-500 font-mono">
                  {formatTime(t.timestamp)}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs mt-2">
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
              </div>
              {t.reasoning && (
                <div className="text-[11px] text-zinc-500 mt-2 line-clamp-2">
                  {t.reasoning}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
