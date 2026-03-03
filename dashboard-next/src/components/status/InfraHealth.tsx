"use client";

import { MetricCard } from "@/components/shared/MetricCard";
import { StatusBadge } from "@/components/shared/StatusBadge";

interface InfraHealthProps {
  apiLatencies: Record<string, number>;
  wsClients: number;
  sqliteQueueDepth: number;
  prefilter: {
    skip_rate: number;
    skipped: number;
    checked: number;
  };
  monitor: {
    prefilter_snapshots: number;
    ai_cooldown_remaining: number;
    last_trigger_reason: string;
    status: Record<string, unknown>;
  } | null;
}

function latencyBadge(ms: number): {
  variant: "green" | "amber" | "red";
  label: string;
} {
  if (ms < 200) return { variant: "green", label: `${ms.toFixed(0)}ms` };
  if (ms < 1000) return { variant: "amber", label: `${ms.toFixed(0)}ms` };
  return { variant: "red", label: `${(ms / 1000).toFixed(1)}s` };
}

export function InfraHealth({
  apiLatencies,
  wsClients,
  sqliteQueueDepth,
  prefilter,
  monitor,
}: InfraHealthProps) {
  const gateStatus = monitor?.status as Record<string, unknown> | undefined;

  return (
    <div className="space-y-4">
      {/* API Latencies */}
      <div>
        <h4 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          API Response Times
        </h4>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(apiLatencies).length > 0 ? (
            Object.entries(apiLatencies).map(([name, ms]) => {
              const badge = latencyBadge(ms);
              return (
                <div
                  key={name}
                  className="flex items-center justify-between rounded-lg border border-white/5 bg-[#0d1017] p-3"
                >
                  <span className="text-xs text-zinc-400 capitalize">
                    {name}
                  </span>
                  <StatusBadge label={badge.label} variant={badge.variant} />
                </div>
              );
            })
          ) : (
            <div className="col-span-4 text-xs text-zinc-600">
              No latency data yet
            </div>
          )}
        </div>
      </div>

      {/* System Health */}
      <div>
        <h4 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          System Health
        </h4>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard
            label="WS Clients"
            value={wsClients}
            subText="Connected dashboards"
          />
          <MetricCard
            label="SQLite Queue"
            value={sqliteQueueDepth}
            subText="Pending writes"
          />
          <MetricCard
            label="Prefilter Rate"
            value={`${(prefilter.skip_rate * 100).toFixed(0)}%`}
            subText={`${prefilter.skipped}/${prefilter.checked} skipped`}
          />
          <MetricCard
            label="Snapshots"
            value={monitor?.prefilter_snapshots ?? 0}
            subText="Prefilter history size"
          />
        </div>
      </div>

      {/* Gate Pipeline */}
      {gateStatus && Object.keys(gateStatus).length > 0 && (
        <div>
          <h4 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
            Gate Pipeline
          </h4>
          <div className="rounded-lg border border-white/5 bg-[#0d1017] p-4">
            <div className="flex flex-wrap items-center gap-2">
              {Object.entries(gateStatus).map(([gate, value], i) => {
                const passed =
                  value === true || value === "pass" || value === "passed";
                const failed =
                  value === false || value === "fail" || value === "blocked";
                const variant = passed ? "green" : failed ? "red" : "amber";
                return (
                  <div key={gate} className="flex items-center gap-2">
                    {i > 0 && (
                      <svg
                        className="h-4 w-4 text-zinc-600"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M9 5l7 7-7 7"
                        />
                      </svg>
                    )}
                    <div className="flex flex-col items-center">
                      <StatusBadge
                        label={gate.replace(/_/g, " ")}
                        variant={variant}
                      />
                      <span className="mt-0.5 text-[10px] text-zinc-600">
                        {String(value)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
