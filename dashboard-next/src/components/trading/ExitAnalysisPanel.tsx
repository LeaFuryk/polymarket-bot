"use client";

import type { ExitAnalysisData } from "@/lib/types";

interface ExitAnalysisPanelProps {
  exitAnalysis: ExitAnalysisData;
}

function Metric({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded-md bg-white/[0.03] p-2.5">
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div
        className={`font-mono text-sm font-semibold ${color ?? "text-zinc-200"}`}
      >
        {value}
      </div>
    </div>
  );
}

export function ExitAnalysisPanel({ exitAnalysis }: ExitAnalysisPanelProps) {
  const rateColor =
    exitAnalysis.good_exit_rate >= 0.6
      ? "text-green-400"
      : exitAnalysis.good_exit_rate >= 0.4
        ? "text-amber-400"
        : "text-red-400";

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Exit Analysis
      </h3>
      <div className="grid grid-cols-2 gap-2">
        <Metric
          label="Good Exit Rate"
          value={`${(exitAnalysis.good_exit_rate * 100).toFixed(0)}%`}
          color={rateColor}
        />
        <Metric label="Total Exits" value={String(exitAnalysis.total_exits)} />
        <Metric
          label="Saved"
          value={`$${exitAnalysis.total_saved.toFixed(4)}`}
          color="text-green-400"
        />
        <Metric
          label="Missed"
          value={`$${exitAnalysis.total_missed.toFixed(4)}`}
          color="text-red-400"
        />
      </div>
    </div>
  );
}
