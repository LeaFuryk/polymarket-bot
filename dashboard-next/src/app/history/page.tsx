"use client";

import { useEffect, useState } from "react";
import { useWSContext } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { MetricCard } from "@/components/shared/MetricCard";
import { formatCurrency, formatUsd, pnlColor } from "@/lib/format";
import type { IterationSummary } from "@/lib/types";

function IterationCard({
  iter,
  expanded,
  onToggle,
}: {
  iter: IterationSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const totalGames = iter.wins + iter.losses;
  const winRate = totalGames > 0 ? (iter.wins / totalGames) * 100 : 0;

  const dateLabel = iter.date_range
    ? new Date(iter.date_range.start).toLocaleDateString()
    : iter.archived_at
      ? new Date(iter.archived_at).toLocaleDateString()
      : "";

  return (
    <div className="rounded-lg bg-[#131720] border border-white/5 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full p-4 flex items-center justify-between hover:bg-white/[0.02] transition-colors text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="font-mono text-sm text-cyan-400 shrink-0">
            {iter.label}
          </span>
          <StatusBadge label={iter.version || "---"} variant="purple" />
          <span className="text-xs text-zinc-500 shrink-0">
            {iter.total_candles} candles
          </span>
          {dateLabel && (
            <span className="text-[11px] text-zinc-600 hidden sm:inline">
              {dateLabel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <span className={`font-mono text-sm ${pnlColor(iter.total_pnl)}`}>
            {formatCurrency(iter.total_pnl, 2)}
          </span>
          <span className="text-xs text-zinc-400">
            {winRate.toFixed(0)}% WR
          </span>
          <svg
            className={`w-4 h-4 text-zinc-500 transition-transform ${
              expanded ? "rotate-180" : ""
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-white/5 p-4 bg-[#0d1017] space-y-4">
          {/* Core stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            <MetricCard
              label="Wins"
              value={<span className="text-green-400">{iter.wins}</span>}
            />
            <MetricCard
              label="Losses"
              value={<span className="text-red-400">{iter.losses}</span>}
            />
            <MetricCard
              label="Win Rate"
              value={
                <span className={pnlColor(winRate - 50)}>
                  {winRate.toFixed(1)}%
                </span>
              }
            />
            <MetricCard
              label="PnL"
              value={
                <span className={pnlColor(iter.total_pnl)}>
                  {formatCurrency(iter.total_pnl, 4)}
                </span>
              }
            />
            {iter.total_fees !== undefined && (
              <MetricCard
                label="Fees"
                value={formatUsd(iter.total_fees, 2)}
              />
            )}
            {iter.ai_cost !== undefined && (
              <MetricCard
                label="AI Cost"
                value={formatUsd(iter.ai_cost, 2)}
              />
            )}
          </div>

          {/* Trade Analysis */}
          {iter.trade_analysis && (
            <div>
              <h4 className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold mb-2">
                Trade Analysis
              </h4>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
                <MetricCard
                  label="Buys"
                  value={iter.trade_analysis.total_buys}
                />
                <MetricCard
                  label="Sells"
                  value={iter.trade_analysis.total_sells}
                />
                <MetricCard
                  label="Avg Fill"
                  value={`$${iter.trade_analysis.avg_fill_price.toFixed(4)}`}
                />
                <MetricCard
                  label="Avg Conf"
                  value={`${(iter.trade_analysis.avg_confidence * 100).toFixed(0)}%`}
                />
                <MetricCard
                  label="Hold Rate"
                  value={`${(iter.trade_analysis.hold_rate * 100).toFixed(0)}%`}
                />
              </div>
              {/* Entry price distribution */}
              <div className="mt-2 flex items-center gap-1 text-[11px]">
                <span className="text-zinc-500 mr-1">Entries:</span>
                <span className="text-green-400">
                  {iter.trade_analysis.cheap_entries} cheap
                </span>
                <span className="text-zinc-600">/</span>
                <span className="text-amber-400">
                  {iter.trade_analysis.mid_entries} mid
                </span>
                <span className="text-zinc-600">/</span>
                <span className="text-red-400">
                  {iter.trade_analysis.expensive_entries} expensive
                </span>
              </div>
            </div>
          )}

          {/* Resolution Analysis */}
          {iter.resolution_analysis && (
            <div>
              <h4 className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold mb-2">
                Resolution Analysis
              </h4>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
                <MetricCard
                  label="Avg BTC Move"
                  value={`$${iter.resolution_analysis.avg_btc_move.toFixed(0)}`}
                />
                <MetricCard
                  label="Max BTC Move"
                  value={`$${iter.resolution_analysis.max_btc_move.toFixed(0)}`}
                />
                <MetricCard
                  label="Avg Win"
                  value={
                    <span className="text-green-400">
                      {formatCurrency(iter.resolution_analysis.avg_win_pnl, 4)}
                    </span>
                  }
                />
                <MetricCard
                  label="Avg Loss"
                  value={
                    <span className="text-red-400">
                      {formatCurrency(iter.resolution_analysis.avg_loss_pnl, 4)}
                    </span>
                  }
                />
                <MetricCard
                  label="Best Win"
                  value={
                    <span className="text-green-400">
                      {formatCurrency(iter.resolution_analysis.biggest_win, 4)}
                    </span>
                  }
                />
                <MetricCard
                  label="Worst Loss"
                  value={
                    <span className="text-red-400">
                      {formatCurrency(iter.resolution_analysis.biggest_loss, 4)}
                    </span>
                  }
                />
              </div>

              {/* Cumulative PnL sparkline */}
              {iter.resolution_analysis.cumulative_pnl.length > 1 && (
                <PnlSparkline data={iter.resolution_analysis.cumulative_pnl} />
              )}
            </div>
          )}

          {/* Calibration */}
          {iter.calibration && iter.calibration.shadow_accuracy !== null && (
            <div className="flex items-center gap-4 text-xs">
              <span className="text-zinc-500">Shadow Accuracy:</span>
              <span className="font-mono text-zinc-200">
                {(iter.calibration.shadow_accuracy * 100).toFixed(1)}%
              </span>
              <span className="text-zinc-600">
                ({iter.calibration.shadow_total} samples)
              </span>
            </div>
          )}

          {/* Exit Analysis */}
          {iter.exit_analysis && iter.exit_analysis.total_exits > 0 && (
            <div className="flex items-center gap-4 text-xs">
              <span className="text-zinc-500">Exit Quality:</span>
              <span className="font-mono text-zinc-200">
                {(iter.exit_analysis.good_exit_rate * 100).toFixed(0)}% good
              </span>
              <span className="text-zinc-600">
                ({iter.exit_analysis.good_exits}/{iter.exit_analysis.total_exits})
              </span>
            </div>
          )}

          {/* Per-candle resolution detail */}
          {iter.resolutions_detail && iter.resolutions_detail.length > 0 && (
            <div>
              <h4 className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold mb-2">
                Resolutions
              </h4>
              <div className="max-h-48 overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-zinc-600 uppercase tracking-wider border-b border-white/5">
                      <th className="text-left pb-1 pr-2">Candle</th>
                      <th className="text-right pb-1 pr-2">BTC Move</th>
                      <th className="text-right pb-1">PnL</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {iter.resolutions_detail.map((r, i) => (
                      <tr key={`${r.slug}-${i}`}>
                        <td className="py-1 pr-2 font-mono text-zinc-400 truncate max-w-[200px]">
                          {r.slug.replace("btc-updown-5m-", "")}
                        </td>
                        <td className="py-1 pr-2 text-right font-mono text-zinc-400">
                          {r.btc_move >= 0 ? "+" : ""}
                          {r.btc_move.toFixed(1)}
                        </td>
                        <td className={`py-1 text-right font-mono ${pnlColor(r.pnl)}`}>
                          {r.pnl !== 0 ? formatCurrency(r.pnl, 4) : "---"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Date range */}
          {iter.date_range && (
            <div className="text-[11px] text-zinc-600 pt-1">
              {new Date(iter.date_range.start).toLocaleString()} —{" "}
              {new Date(iter.date_range.end).toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Simple SVG sparkline for cumulative PnL. */
function PnlSparkline({ data }: { data: number[] }) {
  const w = 300;
  const h = 40;
  const padding = 2;

  const min = Math.min(0, ...data);
  const max = Math.max(0, ...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = padding + (i / (data.length - 1)) * (w - padding * 2);
    const y = padding + (1 - (v - min) / range) * (h - padding * 2);
    return `${x},${y}`;
  });

  const zeroY = padding + (1 - (0 - min) / range) * (h - padding * 2);
  const finalValue = data[data.length - 1];
  const color = finalValue >= 0 ? "#22c55e" : "#ef4444";

  return (
    <div className="mt-2">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-10" preserveAspectRatio="none">
        {/* Zero line */}
        <line
          x1={padding}
          y1={zeroY}
          x2={w - padding}
          y2={zeroY}
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="0.5"
        />
        {/* PnL line */}
        <polyline
          points={points.join(" ")}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

export default function HistoryPage() {
  const ws = useWSContext();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [fetchedIterations, setFetchedIterations] = useState<IterationSummary[] | null>(null);

  // Always fetch iterations from API (works even when bot is offline)
  useEffect(() => {
    async function load() {
      try {
        const res = await fetch("/api/iterations");
        if (res.ok) {
          const data = await res.json();
          setFetchedIterations(data);
        }
      } catch {
        // ignore — will fall back to WS data
      }
    }
    load();
  }, []);

  // Use fetched data (from iterations.json), or fall back to WS snapshot
  const iterations: IterationSummary[] =
    fetchedIterations ?? ws.snapshot?.iterations ?? [];

  // Sort by label descending (most recent first)
  const sorted = [...iterations].sort((a, b) =>
    b.label.localeCompare(a.label)
  );

  const totalPnl = sorted.reduce((sum, i) => sum + i.total_pnl, 0);
  const totalWins = sorted.reduce((sum, i) => sum + i.wins, 0);
  const totalLosses = sorted.reduce((sum, i) => sum + i.losses, 0);
  const totalCandles = sorted.reduce((sum, i) => sum + i.total_candles, 0);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-lg font-semibold text-zinc-200">
          Iteration History
        </h1>
        <div className="flex items-center gap-4 text-xs text-zinc-400">
          <span>{sorted.length} iterations</span>
          <span>{totalCandles} candles</span>
          <span className={`font-mono ${pnlColor(totalPnl)}`}>
            {formatCurrency(totalPnl, 2)} total
          </span>
          <span>
            {totalWins}W / {totalLosses}L
          </span>
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="text-zinc-600 text-sm text-center py-12">
          No iterations found. Run the bot and archive sessions to generate iteration data.
        </div>
      ) : (
        <div className="space-y-2">
          {sorted.map((iter) => (
            <IterationCard
              key={iter.label}
              iter={iter}
              expanded={expanded === iter.label}
              onToggle={() =>
                setExpanded(expanded === iter.label ? null : iter.label)
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
