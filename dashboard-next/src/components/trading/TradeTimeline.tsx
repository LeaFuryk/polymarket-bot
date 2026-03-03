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
        Trades ({trades.length})
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
                <div className="flex items-center gap-2">
                  <StatusBadge label={t.action} variant={actionColor} />
                  <StatusBadge label={t.token_side} variant={sideColor} />
                  {t.risk_blocked && (
                    <StatusBadge label="BLOCKED" variant="red" />
                  )}
                </div>
                <span className="font-mono text-[11px] text-zinc-500">
                  {formatTime(t.timestamp)}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
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
                <div className="mt-2 line-clamp-2 text-[11px] text-zinc-500">
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
