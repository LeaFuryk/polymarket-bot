"use client";

import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatCurrency, formatTime, pnlColor } from "@/lib/format";
import type { ResolutionEntry, ResolutionEvent } from "@/lib/types";

type ResItem = ResolutionEntry | ResolutionEvent;

interface ResolutionTableProps {
  resolutions: ResItem[];
  maxItems?: number;
}

function hasTimestamp(r: ResItem): r is ResolutionEntry {
  return "timestamp" in r;
}

export function ResolutionTable({ resolutions, maxItems = 20 }: ResolutionTableProps) {
  const displayed = resolutions.slice(-maxItems).reverse();

  if (displayed.length === 0) {
    return (
      <div className="rounded-lg bg-[#131720] border border-white/5 p-4">
        <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-2">
          Resolutions
        </h3>
        <div className="text-zinc-600 text-sm">No resolutions yet</div>
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-[#131720] border border-white/5 p-4">
      <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-3">
        Resolutions ({resolutions.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-zinc-500 uppercase tracking-wider border-b border-white/5">
              <th className="text-left pb-2 pr-3">Time</th>
              <th className="text-left pb-2 pr-3">Candle</th>
              <th className="text-left pb-2 pr-3">Winner</th>
              <th className="text-right pb-2 pr-3">BTC Move</th>
              <th className="text-right pb-2">PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {displayed.map((r, i) => (
              <tr key={`${r.slug}-${i}`} className="hover:bg-white/[0.02]">
                <td className="py-2 pr-3 font-mono text-zinc-400">
                  {hasTimestamp(r) ? formatTime(r.timestamp) : "---"}
                </td>
                <td className="py-2 pr-3 text-zinc-300 max-w-[150px] truncate">
                  {r.slug}
                </td>
                <td className="py-2 pr-3">
                  <StatusBadge
                    label={r.winner}
                    variant={r.winner === "up" ? "green" : "red"}
                  />
                </td>
                <td className="py-2 pr-3 text-right font-mono text-zinc-300">
                  {r.btc_move >= 0 ? "+" : ""}
                  {r.btc_move.toFixed(2)}
                </td>
                <td className={`py-2 text-right font-mono ${pnlColor(r.pnl)}`}>
                  {formatCurrency(r.pnl, 4)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
