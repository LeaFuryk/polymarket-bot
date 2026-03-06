"use client";

import type { CalibrationData } from "@/lib/types";

interface CalibrationPanelProps {
  calibration: CalibrationData;
}

export function CalibrationPanel({ calibration }: CalibrationPanelProps) {
  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          Calibration
        </h3>
        <span className="font-mono text-[11px] text-zinc-500">
          {calibration.total_records} records
        </span>
      </div>

      {calibration.shadow_accuracy !== null ? (
        <div className="mb-3 flex items-baseline gap-2">
          <span className="text-[11px] text-zinc-500">Shadow Accuracy</span>
          <span
            className={`font-mono text-lg font-semibold ${
              calibration.shadow_accuracy >= 0.6
                ? "text-green-400"
                : calibration.shadow_accuracy >= 0.5
                  ? "text-amber-400"
                  : "text-red-400"
            }`}
          >
            {(calibration.shadow_accuracy * 100).toFixed(1)}%
          </span>
          {calibration.shadow_total != null && (
            <span className="font-mono text-[11px] text-zinc-500">
              ({calibration.shadow_correct ?? 0}/{calibration.shadow_total})
            </span>
          )}
        </div>
      ) : (
        <div className="mb-3 text-xs text-zinc-500">
          No shadow predictions yet
        </div>
      )}

      {calibration.bins.length > 0 && (
        <div className="space-y-0.5">
          <div className="grid grid-cols-4 gap-1 text-[10px] font-semibold text-zinc-500">
            <span>Range</span>
            <span className="text-right">W</span>
            <span className="text-right">L</span>
            <span className="text-right">Rate</span>
          </div>
          {calibration.bins.map((bin) => (
            <div
              key={bin.range}
              className={`grid grid-cols-4 gap-1 rounded-sm py-0.5 text-[11px] ${
                bin.reliable ? "border-l-2 border-green-500/50 pl-1.5" : "pl-2"
              }`}
            >
              <span className="font-mono text-zinc-300">{bin.range}</span>
              <span className="text-right font-mono text-zinc-300">
                {bin.wins}
              </span>
              <span className="text-right font-mono text-zinc-300">
                {bin.losses}
              </span>
              <span
                className={`text-right font-mono ${
                  bin.win_rate >= 0.6
                    ? "text-green-400"
                    : bin.win_rate >= 0.5
                      ? "text-amber-400"
                      : "text-red-400"
                }`}
              >
                {(bin.win_rate * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
