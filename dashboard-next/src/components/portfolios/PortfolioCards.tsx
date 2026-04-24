"use client";

import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT } from "@/lib/constants";

const MODEL_ORDER: Record<string, number> = {
  LogisticRegression: 0,
  RandomForest: 1,
  XGBoost: 2,
  DNN: 3,
};

export function PortfolioCards() {
  const { portfolios } = useDashboard();
  const models = Object.keys(portfolios).sort(
    (a, b) => (MODEL_ORDER[a] ?? 99) - (MODEL_ORDER[b] ?? 99),
  );

  return (
    <div
      className="grid gap-4"
      style={{
        gridTemplateColumns: `repeat(${Math.max(models.length, 1)}, minmax(0, 1fr))`,
      }}
    >
      {models.map((model) => {
        const p = portfolios[model];
        if (!p) {
          return (
            <div
              key={model}
              className="rounded-xl bg-[#0d1017] p-5 font-mono text-sm text-white/20"
            >
              {MODEL_SHORT[model]} — waiting...
            </div>
          );
        }
        const color = MODEL_COLORS[model] ?? "#888";
        const short = MODEL_SHORT[model] ?? model;
        const isPositive = (p.total_return_pct ?? 0) >= 0;

        return (
          <div
            key={model}
            className="rounded-xl bg-[#0d1017] p-5"
            style={{ borderTop: `3px solid ${color}` }}
          >
            <div className="mb-4 flex items-baseline gap-3">
              <span className="font-mono text-lg font-bold" style={{ color }}>
                {short}
              </span>
              <span
                className={`font-mono text-base font-semibold ${isPositive ? "text-green-400" : "text-red-400"}`}
              >
                {isPositive ? "+" : ""}
                {(p.total_return_pct ?? 0).toFixed(1)}%
              </span>
            </div>
            <div className="space-y-2 font-mono text-sm">
              <div className="flex justify-between text-white/50">
                <span>Balance</span>
                <span className="text-base font-semibold text-white">
                  ${p.final_balance.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-white/50">
                <span>W / L</span>
                <span className="text-white">
                  {p.wins} / {p.losses}
                </span>
              </div>
              <div className="flex justify-between text-white/50">
                <span>Win Rate</span>
                <span className="text-white">
                  {((p.win_rate ?? 0) * 100).toFixed(1)}%
                </span>
              </div>
              <div className="flex justify-between text-white/50">
                <span>PnL</span>
                <span
                  className={`text-base font-semibold ${isPositive ? "text-green-400" : "text-red-400"}`}
                >
                  {isPositive ? "+" : ""}${(p.net_pnl ?? 0).toFixed(2)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
