"use client";

import { AnimatedNumber } from "@/components/shared/AnimatedNumber";
import { formatPnlPercent, pnlColor } from "@/lib/format";

interface PositionPanelProps {
  position: {
    up_shares: number;
    up_avg_entry: number;
    down_shares: number;
    down_avg_entry: number;
    cash: number;
    pnl: Record<string, number>;
    dynamic_sl: Record<string, number>;
    dynamic_tp: Record<string, number>;
  } | null;
}

function SideRow({
  label,
  shares,
  avgEntry,
  pnlPct,
  sl,
  tp,
  color,
}: {
  label: string;
  shares: number;
  avgEntry: number;
  pnlPct: number | undefined;
  sl: number | undefined;
  tp: number | undefined;
  color: string;
}) {
  const hasPosition = shares > 0.001;

  return (
    <div
      className={`rounded-lg border border-white/5 bg-[#0d1017] p-3 ${!hasPosition ? "opacity-40" : ""}`}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className={`text-sm font-semibold ${color}`}>{label}</span>
        {hasPosition && pnlPct !== undefined && (
          <span className={`font-mono text-sm ${pnlColor(pnlPct)}`}>
            {formatPnlPercent(pnlPct)}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-zinc-500">Shares</div>
          <div className="font-mono text-zinc-200">
            <AnimatedNumber value={shares} format={(n) => n.toFixed(2)} />
          </div>
        </div>
        <div>
          <div className="text-zinc-500">Avg Entry</div>
          <div className="font-mono text-zinc-200">
            {hasPosition ? `$${avgEntry.toFixed(4)}` : "---"}
          </div>
        </div>
        <div>
          <div className="text-zinc-500">SL / TP</div>
          <div className="font-mono text-zinc-400">
            {hasPosition && sl !== undefined && tp !== undefined
              ? `${formatPnlPercent(sl)} / ${formatPnlPercent(tp)}`
              : "---"}
          </div>
        </div>
      </div>
    </div>
  );
}

export function PositionPanel({ position }: PositionPanelProps) {
  if (!position) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Positions
      </h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SideRow
          label="UP"
          shares={position.up_shares}
          avgEntry={position.up_avg_entry}
          pnlPct={position.pnl["up"]}
          sl={position.dynamic_sl["up"]}
          tp={position.dynamic_tp["up"]}
          color="text-green-400"
        />
        <SideRow
          label="DOWN"
          shares={position.down_shares}
          avgEntry={position.down_avg_entry}
          pnlPct={position.pnl["down"]}
          sl={position.dynamic_sl["down"]}
          tp={position.dynamic_tp["down"]}
          color="text-red-400"
        />
      </div>
    </div>
  );
}
