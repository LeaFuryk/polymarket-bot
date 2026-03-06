"use client";

import type { AdaptiveEntry } from "@/lib/types";

interface AdaptiveEntryPanelProps {
  adaptiveEntry: AdaptiveEntry;
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ${color}`}
    >
      {label}
    </span>
  );
}

const REGIME_COLORS: Record<string, string> = {
  CALM: "bg-cyan-500/15 text-cyan-400",
  MODERATE: "bg-amber-500/15 text-amber-400",
  CHOPPY: "bg-red-500/15 text-red-400",
};

const SIGNAL_COLORS: Record<string, string> = {
  MOMENTUM: "bg-green-500/15 text-green-400",
  CONTRARIAN: "bg-purple-500/15 text-purple-400",
  UNCERTAIN: "bg-amber-500/15 text-amber-400",
};

const TREND_COLORS: Record<string, string> = {
  "STRONG BULL": "bg-green-500/15 text-green-400",
  BULL: "bg-green-500/10 text-green-300",
  NEUTRAL: "bg-zinc-500/15 text-zinc-400",
  BEAR: "bg-red-500/10 text-red-300",
  "STRONG BEAR": "bg-red-500/15 text-red-400",
};

export function AdaptiveEntryPanel({ adaptiveEntry }: AdaptiveEntryPanelProps) {
  const ae = adaptiveEntry;

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
          Adaptive Entry
        </h3>
        <div className="flex gap-1.5">
          <Badge
            label={ae.regime}
            color={REGIME_COLORS[ae.regime] ?? "bg-zinc-500/15 text-zinc-400"}
          />
          <Badge
            label={ae.signal_type}
            color={
              SIGNAL_COLORS[ae.signal_type] ?? "bg-zinc-500/15 text-zinc-400"
            }
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs">
        <div>
          <div className="text-zinc-500">BTC Threshold</div>
          <div className="font-mono text-zinc-200">
            ${ae.btc_threshold.toFixed(0)}
          </div>
        </div>
        <div>
          <div className="text-zinc-500">Max Entry</div>
          <div className="font-mono text-zinc-200">
            ${ae.max_entry_price.toFixed(4)}
          </div>
        </div>
        <div>
          <div className="text-zinc-500">Reversal Rate</div>
          <div className="font-mono text-zinc-200">
            {(ae.reversal_rate * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {ae.market_trend_label && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-[11px] text-zinc-500">Trend</span>
          <Badge
            label={ae.market_trend_label}
            color={
              TREND_COLORS[ae.market_trend_label] ??
              "bg-zinc-500/15 text-zinc-400"
            }
          />
          {ae.market_trend !== undefined && (
            <span className="font-mono text-[11px] text-zinc-400">
              {ae.market_trend.toFixed(3)}
            </span>
          )}
        </div>
      )}

      {ae.using_fakeout && (
        <div className="mt-3 border-t border-white/5 pt-3">
          <div className="mb-1 text-[11px] font-semibold text-zinc-500">
            Fakeout Detection
          </div>
          <div className="grid grid-cols-4 gap-2 text-xs">
            <div>
              <div className="text-zinc-500">Median</div>
              <div className="font-mono text-zinc-200">
                ${ae.fakeout_median?.toFixed(0)}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">P75</div>
              <div className="font-mono text-zinc-200">
                ${ae.fakeout_p75?.toFixed(0)}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Max</div>
              <div className="font-mono text-zinc-200">
                ${ae.fakeout_max?.toFixed(0)}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Cap</div>
              <div className="font-mono text-amber-400">
                ${ae.adaptive_cap?.toFixed(0)}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
