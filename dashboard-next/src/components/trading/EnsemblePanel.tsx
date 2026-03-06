"use client";

import type { EnsembleStats } from "@/lib/types";

interface EnsemblePanelProps {
  ensemble: EnsembleStats;
}

function Metric({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-md bg-white/[0.03] p-2.5">
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className="font-mono text-sm font-semibold text-zinc-200">
        {value}
      </div>
      {sub && <div className="font-mono text-[11px] text-zinc-500">{sub}</div>}
    </div>
  );
}

export function EnsemblePanel({ ensemble }: EnsemblePanelProps) {
  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Ensemble
      </h3>
      <div className="grid grid-cols-2 gap-2">
        <Metric
          label="Screen Pass Rate"
          value={`${(ensemble.screen_pass_rate * 100).toFixed(0)}%`}
          sub={`${ensemble.screen_passes}/${ensemble.screen_calls}`}
        />
        <Metric label="Sonnet Trades" value={String(ensemble.sonnet_trades)} />
        <Metric
          label="ML-Sonnet Agree"
          value={`${(ensemble.ml_sonnet_agree_rate * 100).toFixed(0)}%`}
          sub={`${ensemble.ml_sonnet_agree}/${ensemble.ml_sonnet_total}`}
        />
        <Metric label="Total Screened" value={String(ensemble.screen_calls)} />
      </div>
    </div>
  );
}
