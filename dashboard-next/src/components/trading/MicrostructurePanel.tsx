"use client";

import type { MicrostructureEntry } from "@/lib/types";

interface MicrostructurePanelProps {
  microstructure: MicrostructureEntry[] | null;
}

function relativeTime(ts: number): string {
  const ago = Math.round((Date.now() / 1000 - ts) / 60);
  if (ago < 1) return "now";
  return `${ago}m ago`;
}

export function MicrostructurePanel({
  microstructure,
}: MicrostructurePanelProps) {
  if (!microstructure || microstructure.length === 0) return null;

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Microstructure (Last {microstructure.length} Candles)
      </h3>

      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-zinc-500">
              <th className="pb-1.5 text-left font-semibold">Time</th>
              <th className="pb-1.5 text-right font-semibold">UP Spread</th>
              <th className="pb-1.5 text-right font-semibold">DN Spread</th>
              <th className="pb-1.5 text-right font-semibold">Depth</th>
              <th className="pb-1.5 text-right font-semibold">Imbalance</th>
              <th className="pb-1.5 text-right font-semibold">BTC Range</th>
              <th className="pb-1.5 text-right font-semibold">BTC Move</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {microstructure.map((ms, i) => {
              const imbColor =
                ms.avg_imbalance > 1
                  ? "text-green-400"
                  : ms.avg_imbalance < 1
                    ? "text-red-400"
                    : "text-zinc-300";
              const moveColor =
                ms.btc_final_move > 0
                  ? "text-green-400"
                  : ms.btc_final_move < 0
                    ? "text-red-400"
                    : "text-zinc-300";
              return (
                <tr
                  key={i}
                  className="border-t border-white/[0.03] text-zinc-300"
                >
                  <td className="py-1 text-zinc-500">
                    {relativeTime(ms.timestamp)}
                  </td>
                  <td className="py-1 text-right">
                    {ms.avg_spread_up.toFixed(2)}%
                  </td>
                  <td className="py-1 text-right">
                    {ms.avg_spread_down.toFixed(2)}%
                  </td>
                  <td className="py-1 text-right">{ms.avg_depth.toFixed(1)}</td>
                  <td className={`py-1 text-right ${imbColor}`}>
                    {ms.avg_imbalance.toFixed(3)}
                  </td>
                  <td className="py-1 text-right">
                    ${ms.btc_range.toFixed(1)}
                  </td>
                  <td className={`py-1 text-right ${moveColor}`}>
                    {ms.btc_final_move > 0 ? "+" : ""}$
                    {ms.btc_final_move.toFixed(1)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
