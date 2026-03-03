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

export function ResolutionTable({
  resolutions,
  maxItems = 20,
}: ResolutionTableProps) {
  const displayed = resolutions.slice(-maxItems).reverse();

  if (displayed.length === 0) {
    return (
      <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
        <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          Resolutions
        </h3>
        <div className="text-sm text-zinc-600">No resolutions yet</div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Resolutions ({resolutions.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/5 tracking-wider text-zinc-500 uppercase">
              <th className="pr-3 pb-2 text-left">Time</th>
              <th className="pr-3 pb-2 text-left">Candle</th>
              <th className="pr-3 pb-2 text-left">Winner</th>
              <th className="pr-3 pb-2 text-right">BTC Move</th>
              <th className="pb-2 text-right">PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {displayed.map((r, i) => (
              <tr key={`${r.slug}-${i}`} className="hover:bg-white/[0.02]">
                <td className="py-2 pr-3 font-mono text-zinc-400">
                  {hasTimestamp(r) ? formatTime(r.timestamp) : "---"}
                </td>
                <td className="max-w-[150px] truncate py-2 pr-3 text-zinc-300">
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
