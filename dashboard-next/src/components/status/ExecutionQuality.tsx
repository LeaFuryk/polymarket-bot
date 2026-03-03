"use client";

import { MetricCard } from "@/components/shared/MetricCard";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatCurrency } from "@/lib/format";
import type { RiskState } from "@/lib/types";

interface ExecutionQualityProps {
  risk: RiskState | null;
  ensemble: {
    screen_calls: number;
    screen_passes: number;
  } | null;
  aiCooldown: number;
  lastTrigger: string;
  gatePipeline: Record<string, unknown>;
}

export function ExecutionQuality({
  risk,
  ensemble,
  aiCooldown,
  lastTrigger,
  gatePipeline,
}: ExecutionQualityProps) {
  const screenPassRate =
    ensemble && ensemble.screen_calls > 0
      ? ((ensemble.screen_passes / ensemble.screen_calls) * 100).toFixed(0)
      : "---";

  return (
    <div className="space-y-4">
      {/* AI Decision Stats */}
      <div>
        <h4 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-3">
          AI Decision Engine
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard
            label="AI Cooldown"
            value={
              aiCooldown > 0 ? (
                <span className="text-amber-400">{aiCooldown.toFixed(0)}s</span>
              ) : (
                <span className="text-green-400">Ready</span>
              )
            }
          />
          <MetricCard
            label="Screen Pass Rate"
            value={`${screenPassRate}%`}
            subText={
              ensemble
                ? `${ensemble.screen_passes}/${ensemble.screen_calls}`
                : undefined
            }
          />
          <MetricCard
            label="Last Trigger"
            value={
              lastTrigger ? (
                <StatusBadge
                  label={lastTrigger.slice(0, 20)}
                  variant="cyan"
                />
              ) : (
                <span className="text-zinc-600">---</span>
              )
            }
          />
          <MetricCard
            label="Daily Trades"
            value={risk?.daily_trades ?? 0}
            subText={`Fees: ${formatCurrency(risk?.daily_fees ?? 0)}`}
          />
        </div>
      </div>

      {/* Risk State */}
      {risk && (
        <div>
          <h4 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-3">
            Risk State
          </h4>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard
              label="Daily PnL"
              value={
                <span className={risk.daily_pnl >= 0 ? "text-green-400" : "text-red-400"}>
                  {formatCurrency(risk.daily_pnl, 4)}
                </span>
              }
            />
            <MetricCard
              label="Max Drawdown"
              value={
                <span className="text-red-400">
                  {formatCurrency(risk.max_drawdown, 4)}
                </span>
              }
            />
            <MetricCard
              label="Status"
              value={
                risk.is_halted ? (
                  <StatusBadge label="HALTED" variant="red" />
                ) : (
                  <StatusBadge label="ACTIVE" variant="green" />
                )
              }
            />
            <MetricCard
              label="Daily Fees"
              value={formatCurrency(risk.daily_fees, 4)}
            />
          </div>
        </div>
      )}

      {/* Gate Pipeline Detail */}
      {Object.keys(gatePipeline).length > 0 && (
        <div>
          <h4 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-3">
            Gate Pipeline Detail
          </h4>
          <div className="rounded-lg bg-[#0d1017] border border-white/5 p-4">
            <pre className="text-xs text-zinc-400 font-mono whitespace-pre-wrap overflow-x-auto">
              {JSON.stringify(gatePipeline, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
