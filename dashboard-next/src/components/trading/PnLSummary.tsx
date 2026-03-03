"use client";

import { AnimatedNumber } from "@/components/shared/AnimatedNumber";
import { MetricCard } from "@/components/shared/MetricCard";
import { formatCurrency, formatUsd, pnlColor } from "@/lib/format";
import type { AllTimeStats, SessionStats } from "@/lib/types";

interface PnLSummaryProps {
  session: SessionStats | null;
  allTime: AllTimeStats | null;
}

export function PnLSummary({ session, allTime }: PnLSummaryProps) {
  if (!session) return null;

  const totalGames = session.wins + session.losses;
  const winRate = totalGames > 0 ? (session.wins / totalGames) * 100 : 0;

  return (
    <div className="space-y-3">
      <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold">
        Session Performance
      </h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <MetricCard
          label="PnL"
          value={
            <AnimatedNumber
              value={session.total_pnl}
              format={(n) => formatCurrency(n, 4)}
              className={pnlColor(session.total_pnl)}
            />
          }
          subText={`Fees: ${formatUsd(session.total_fees, 2)}`}
        />
        <MetricCard
          label="Win Rate"
          value={
            <span className={pnlColor(winRate - 50)}>
              {winRate.toFixed(0)}%
            </span>
          }
          subText={`${session.wins}W / ${session.losses}L`}
        />
        <MetricCard
          label="Cash"
          value={
            <AnimatedNumber
              value={session.cash}
              format={(n) => formatUsd(n)}
              className="text-zinc-100"
            />
          }
        />
        <MetricCard
          label="Portfolio"
          value={
            <AnimatedNumber
              value={session.portfolio_value}
              format={(n) => formatUsd(n)}
              className="text-zinc-100"
            />
          }
          subText={`Initial: ${formatUsd(session.initial_cash)}`}
        />
      </div>

      {allTime && (allTime.total_resolutions > 0) && (
        <>
          <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mt-4">
            All Time
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard
              label="Total PnL"
              value={
                <span className={pnlColor(allTime.total_pnl)}>
                  {formatCurrency(allTime.total_pnl, 4)}
                </span>
              }
            />
            <MetricCard
              label="Win Rate"
              value={`${allTime.win_rate.toFixed(0)}%`}
              subText={`${allTime.wins}W / ${allTime.losses}L`}
            />
            <MetricCard
              label="Resolutions"
              value={allTime.total_resolutions}
            />
            <MetricCard
              label="Trades"
              value={allTime.total_trades}
            />
          </div>
        </>
      )}
    </div>
  );
}
