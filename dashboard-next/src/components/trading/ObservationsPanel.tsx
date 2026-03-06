"use client";

import type { ObservationEntry } from "@/lib/types";

interface ObservationsPanelProps {
  observations: ObservationEntry[] | null;
  resolutionsSinceReflection?: number;
  totalResolutions?: number;
}

const CATEGORY_COLORS: Record<string, string> = {
  pattern: "bg-cyan-500/15 text-cyan-400",
  bias: "bg-amber-500/15 text-amber-400",
  edge: "bg-green-500/15 text-green-400",
  regime: "bg-purple-500/15 text-purple-400",
};

function freshnessDot(
  obs: ObservationEntry,
  totalResolutions: number | undefined,
): string {
  if (totalResolutions === undefined) return "bg-zinc-500";
  const age = totalResolutions - obs.based_on_resolutions;
  const lifespan = obs.expires_after_resolutions;
  const ratio = age / lifespan;
  if (ratio < 0.33) return "bg-green-400";
  if (ratio < 0.66) return "bg-amber-400";
  return "bg-red-400";
}

export function ObservationsPanel({
  observations,
  resolutionsSinceReflection,
  totalResolutions,
}: ObservationsPanelProps) {
  if (!observations || observations.length === 0) return null;

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          Knowledge Observations
        </h3>
        <div className="flex items-center gap-3">
          {resolutionsSinceReflection !== undefined && (
            <span className="text-[11px] text-zinc-500">
              {resolutionsSinceReflection} since reflection
            </span>
          )}
          <span className="font-mono text-[11px] text-zinc-500">
            {observations.length} active
          </span>
        </div>
      </div>

      <div className="space-y-2">
        {observations.map((obs) => (
          <div
            key={obs.id}
            className="flex items-start gap-2 rounded-md bg-white/[0.02] px-3 py-2"
          >
            <div
              className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${freshnessDot(obs, totalResolutions)}`}
            />
            <div className="min-w-0 flex-1">
              <div className="mb-0.5 flex items-center gap-2">
                <span
                  className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                    CATEGORY_COLORS[obs.category] ??
                    "bg-zinc-500/15 text-zinc-400"
                  }`}
                >
                  {obs.category}
                </span>
                <span className="text-[10px] text-zinc-600">
                  {obs.based_on_resolutions}r / expires{" "}
                  {obs.expires_after_resolutions}r
                </span>
              </div>
              <div className="text-xs leading-relaxed text-zinc-300">
                {obs.text}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
