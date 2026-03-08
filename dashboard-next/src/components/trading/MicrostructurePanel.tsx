"use client";

import type { MicrostructureEntry, ReversalRegime } from "@/lib/types";

interface MicrostructurePanelProps {
  microstructure: MicrostructureEntry[] | null;
  reversalRegime?: ReversalRegime | null;
}

function relativeTime(ts: number): string {
  const ago = Math.round((Date.now() / 1000 - ts) / 60);
  if (ago < 1) return "now";
  return `${ago}m ago`;
}

const REGIME_STYLES: Record<
  string,
  { bg: string; text: string; border: string }
> = {
  HIGH_REVERSAL: {
    bg: "bg-red-500/10",
    text: "text-red-400",
    border: "border-red-500/30",
  },
  MODERATE_REVERSAL: {
    bg: "bg-amber-500/10",
    text: "text-amber-400",
    border: "border-amber-500/30",
  },
  DIRECTIONAL: {
    bg: "bg-emerald-500/10",
    text: "text-emerald-400",
    border: "border-emerald-500/30",
  },
};

function RegimeBadge({ regime }: { regime: ReversalRegime }) {
  const style = REGIME_STYLES[regime.label] ?? REGIME_STYLES.DIRECTIONAL;
  return (
    <div
      className={`mb-3 flex items-center gap-3 rounded-md border px-3 py-1.5 ${style.bg} ${style.border}`}
    >
      <span className={`text-xs font-bold tracking-wider ${style.text}`}>
        {regime.label.replace("_", " ")}
      </span>
      <span className="font-mono text-[11px] text-zinc-400">
        score {regime.score.toFixed(2)} · avg crossings{" "}
        {regime.avg_crossings.toFixed(1)} · avg intensity{" "}
        {regime.avg_intensity.toFixed(2)}
      </span>
    </div>
  );
}

export function MicrostructurePanel({
  microstructure,
  reversalRegime,
}: MicrostructurePanelProps) {
  if (!microstructure || microstructure.length === 0) return null;

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Microstructure (Last {microstructure.length} Candles)
      </h3>

      {reversalRegime && <RegimeBadge regime={reversalRegime} />}

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
              <th className="pb-1.5 text-right font-semibold">Crossings</th>
              <th className="pb-1.5 text-right font-semibold">Rev Int</th>
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
              const crossColor =
                ms.zero_crossings >= 4
                  ? "text-red-400"
                  : ms.zero_crossings >= 2
                    ? "text-amber-400"
                    : "text-zinc-300";
              const intColor =
                ms.reversal_intensity >= 0.7
                  ? "text-red-400"
                  : ms.reversal_intensity >= 0.4
                    ? "text-amber-400"
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
                  <td className={`py-1 text-right ${crossColor}`}>
                    {ms.zero_crossings}
                  </td>
                  <td className={`py-1 text-right ${intColor}`}>
                    {ms.reversal_intensity.toFixed(2)}
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
