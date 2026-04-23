"use client";

import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT } from "@/lib/constants";

export function BetPnlPanel() {
  const { currentEntries, latestSnapshot } = useDashboard();

  const byModel = new Map<string, typeof currentEntries>();
  for (const entry of currentEntries) {
    const list = byModel.get(entry.model) ?? [];
    list.push(entry);
    byModel.set(entry.model, list);
  }

  if (byModel.size === 0) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl bg-[#0d1017] p-5 font-mono text-sm text-white/30">
        No entries yet
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-[#0d1017] p-5">
      <h2 className="mb-4 font-mono text-base font-semibold text-white/70">
        Open Positions
      </h2>
      <div className="space-y-3">
        {Array.from(byModel.entries()).map(([model, entries]) => {
          const color = MODEL_COLORS[model] ?? "#888";
          const short = MODEL_SHORT[model] ?? model;
          const direction = entries[0]?.direction ?? "—";
          const totalCost = entries.reduce((sum, e) => sum + e.amount_usd, 0);

          let unrealized = 0;
          if (latestSnapshot) {
            const currentBid =
              direction === "UP"
                ? latestSnapshot.up_bids?.[0]?.[0]
                : latestSnapshot.down_bids?.[0]?.[0];
            if (currentBid != null && currentBid >= 0) {
              for (const e of entries) {
                const grossShares = e.amount_usd / e.price;
                const feeShares = grossShares * 0.072 * e.price * (1 - e.price);
                const netShares = grossShares - feeShares;
                unrealized += netShares * currentBid - e.amount_usd;
              }
            }
          }

          const isPositive = unrealized >= 0;

          return (
            <div
              key={model}
              className="rounded-lg border border-white/5 p-3"
              style={{ borderLeftColor: color, borderLeftWidth: 3 }}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm font-bold" style={{ color }}>
                  {short}
                </span>
                <span
                  className={`font-mono text-sm font-bold ${isPositive ? "text-green-400" : "text-red-400"}`}
                >
                  {isPositive ? "+" : ""}${unrealized.toFixed(2)}
                </span>
              </div>
              <div className="mt-2 flex gap-4 font-mono text-xs text-white/40">
                <span
                  className={
                    direction === "UP" ? "text-green-400/70" : "text-red-400/70"
                  }
                >
                  {direction}
                </span>
                <span>
                  {entries.length} entry{entries.length > 1 ? "s" : ""}
                </span>
                <span>${totalCost.toFixed(2)} wagered</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
