"use client";

import { useMemo } from "react";
import type { MLModelData } from "@/lib/types";

interface MLModelPanelProps {
  mlModel: MLModelData;
}

export function MLModelPanel({ mlModel }: MLModelPanelProps) {
  const sortedWeights = useMemo(() => {
    if (!mlModel.weights) return [];
    return Object.entries(mlModel.weights)
      .map(([name, weight]) => ({ name, weight }))
      .sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  }, [mlModel.weights]);

  const maxAbs = useMemo(
    () =>
      sortedWeights.length > 0
        ? Math.max(...sortedWeights.map((w) => Math.abs(w.weight)), 0.001)
        : 1,
    [sortedWeights],
  );

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          ML Model
        </h3>
        {mlModel.model_trained ? (
          <span className="inline-flex items-center rounded-full bg-green-500/15 px-2 py-0.5 text-[11px] font-semibold text-green-400">
            TRAINED
          </span>
        ) : (
          <span className="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-400">
            TRAINING {mlModel.training_samples}/10
          </span>
        )}
      </div>

      {mlModel.model_trained ? (
        sortedWeights.length > 0 ? (
          <div className="space-y-1.5">
            {sortedWeights.map(({ name, weight }) => {
              const pct = (Math.abs(weight) / maxAbs) * 100;
              const isPositive = weight >= 0;
              return (
                <div key={name} className="flex items-center gap-2">
                  <span className="w-28 shrink-0 truncate text-[11px] text-zinc-400">
                    {name}
                  </span>
                  <div className="relative h-3 flex-1 rounded-sm bg-white/5">
                    <div
                      className={`absolute top-0 h-full rounded-sm ${
                        isPositive ? "bg-green-500/60" : "bg-red-500/60"
                      }`}
                      style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                  </div>
                  <span
                    className={`w-12 shrink-0 text-right font-mono text-[11px] ${
                      isPositive ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {weight > 0 ? "+" : ""}
                    {weight.toFixed(3)}
                  </span>
                </div>
              );
            })}
            {mlModel.bias !== undefined && (
              <div className="mt-1 text-right font-mono text-[11px] text-zinc-500">
                bias: {mlModel.bias.toFixed(4)}
              </div>
            )}
          </div>
        ) : (
          <div className="text-xs text-zinc-400">
            {mlModel.training_samples} samples trained
          </div>
        )
      ) : (
        <div className="text-xs text-zinc-500">
          Need {Math.max(0, 10 - mlModel.training_samples)} more samples to
          train
        </div>
      )}
    </div>
  );
}
