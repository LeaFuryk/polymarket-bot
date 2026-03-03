"use client";

import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatCurrency } from "@/lib/format";
import type { RiskState } from "@/lib/types";

interface RiskBarProps {
  risk: RiskState | null;
}

export function RiskBar({ risk }: RiskBarProps) {
  if (!risk) return null;

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-4 text-xs">
          <div>
            <span className="mr-1 text-zinc-500">Daily PnL:</span>
            <span
              className={`font-mono ${risk.daily_pnl >= 0 ? "text-green-400" : "text-red-400"}`}
            >
              {formatCurrency(risk.daily_pnl, 4)}
            </span>
          </div>
          <div>
            <span className="mr-1 text-zinc-500">Trades:</span>
            <span className="font-mono text-zinc-300">{risk.daily_trades}</span>
          </div>
          <div>
            <span className="mr-1 text-zinc-500">Drawdown:</span>
            <span className="font-mono text-zinc-300">
              {formatCurrency(risk.max_drawdown, 4)}
            </span>
          </div>
        </div>
        {risk.is_halted && <StatusBadge label="HALTED" variant="red" />}
      </div>
    </div>
  );
}
