"use client";

import type { MonitorState } from "@/lib/types";

interface MonitorPanelProps {
  monitor: MonitorState;
}

function GateDot({ passed }: { passed: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${
        passed ? "bg-green-400" : "bg-red-400"
      }`}
    />
  );
}

export function MonitorPanel({ monitor }: MonitorPanelProps) {
  const cooldownActive = monitor.ai_cooldown_remaining > 0;
  const statusEntries = Object.entries(monitor.status ?? {});

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
        Monitor / Prefilter
      </h3>

      <div className="space-y-2.5">
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-md bg-white/[0.03] p-2.5">
            <div className="text-[11px] text-zinc-500">Snapshots</div>
            <div className="font-mono text-sm font-semibold text-zinc-200">
              {monitor.prefilter_snapshots}
            </div>
          </div>
          <div className="rounded-md bg-white/[0.03] p-2.5">
            <div className="text-[11px] text-zinc-500">AI Cooldown</div>
            <div
              className={`font-mono text-sm font-semibold ${
                cooldownActive ? "text-amber-400" : "text-zinc-200"
              }`}
            >
              {cooldownActive
                ? `${Math.ceil(monitor.ai_cooldown_remaining)}s`
                : "Ready"}
            </div>
          </div>
        </div>

        {monitor.last_trigger_reason && (
          <div>
            <div className="text-[11px] text-zinc-500">Last Trigger</div>
            <div className="text-xs text-zinc-300">
              {monitor.last_trigger_reason}
            </div>
          </div>
        )}

        {statusEntries.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] text-zinc-500">Gate Pipeline</div>
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {statusEntries.map(([gate, passed]) => (
                <div key={gate} className="flex items-center gap-1.5">
                  <GateDot passed={Boolean(passed)} />
                  <span className="text-[11px] text-zinc-400">{gate}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
