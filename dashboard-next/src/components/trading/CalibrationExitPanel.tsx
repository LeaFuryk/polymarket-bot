"use client";

import type { CalibrationData, ExitAnalysisData } from "@/lib/types";

interface CalibrationExitPanelProps {
  calibration: CalibrationData;
  exitAnalysis: ExitAnalysisData;
}

export function CalibrationExitPanel({
  calibration,
  exitAnalysis,
}: CalibrationExitPanelProps) {
  const rateColor =
    exitAnalysis.good_exit_rate >= 0.6
      ? "text-green-400"
      : exitAnalysis.good_exit_rate >= 0.4
        ? "text-amber-400"
        : "text-red-400";

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      {/* Calibration section */}
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          Calibration
        </h3>
        <span className="font-mono text-[11px] text-zinc-500">
          {calibration.total_records} rec
        </span>
      </div>

      {calibration.shadow_accuracy !== null ? (
        <div className="mb-1.5 flex items-baseline gap-2">
          <span
            className={`font-mono text-base font-semibold ${
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
        <div className="mb-1.5 text-xs text-zinc-500">No shadow data</div>
      )}

      {calibration.bins.length > 0 && (
        <div className="mb-3 space-y-0.5">
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

      {/* Exit Analysis section */}
      <div className="border-t border-white/5 pt-2.5">
        <h3 className="mb-1.5 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          Exit Analysis
        </h3>
        <div className="grid grid-cols-4 gap-1.5">
          <div>
            <div className="text-[10px] text-zinc-500">Rate</div>
            <div className={`font-mono text-xs font-semibold ${rateColor}`}>
              {(exitAnalysis.good_exit_rate * 100).toFixed(0)}%
            </div>
          </div>
          <div>
            <div className="text-[10px] text-zinc-500">Exits</div>
            <div className="font-mono text-xs font-semibold text-zinc-200">
              {exitAnalysis.total_exits}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-zinc-500">Saved</div>
            <div className="font-mono text-xs font-semibold text-green-400">
              ${exitAnalysis.total_saved.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-zinc-500">Missed</div>
            <div className="font-mono text-xs font-semibold text-red-400">
              ${exitAnalysis.total_missed.toFixed(2)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
