"use client";

import { useState } from "react";
import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT, THEME } from "@/lib/constants";
import { BetDetail } from "./BetDetail";
import type { PastBet } from "@/lib/types";

const MODEL_ORDER: Record<string, number> = {
  LogisticRegression: 0,
  RandomForest: 1,
  XGBoost: 2,
  DNN: 3,
};

export function BetList() {
  const { pastBets } = useDashboard();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Derive model list from settlement data
  const modelSet = new Set<string>();
  for (const bet of pastBets) {
    for (const m of Object.keys(bet.settlements)) modelSet.add(m);
  }
  const models = [...modelSet].sort(
    (a, b) => (MODEL_ORDER[a] ?? 99) - (MODEL_ORDER[b] ?? 99),
  );

  if (pastBets.length === 0) {
    return (
      <div className="flex h-28 items-center justify-center rounded-xl bg-[#0d1017] font-mono text-sm text-white/30">
        No resolved bets yet
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-[#0d1017] p-5">
      <h2 className="mb-4 font-mono text-base font-semibold text-white/70">
        Previous Bets
      </h2>

      {/* Header row */}
      <div className="mb-2 flex items-center gap-4 px-4 font-mono text-xs text-white/30">
        <span className="w-16">Time</span>
        <span className="w-14 text-center">Result</span>
        {models.map((model) => (
          <span
            key={model}
            className="w-28"
            style={{ color: MODEL_COLORS[model] + "80" }}
          >
            {MODEL_SHORT[model]}
          </span>
        ))}
        <span className="ml-auto" />
      </div>

      <div className="space-y-1">
        {pastBets.map((bet) => (
          <BetRow
            key={bet.candle_id}
            bet={bet}
            models={models}
            expanded={expandedId === bet.candle_id}
            onToggle={() =>
              setExpandedId(expandedId === bet.candle_id ? null : bet.candle_id)
            }
          />
        ))}
      </div>
    </div>
  );
}

function BetRow({
  bet,
  models,
  expanded,
  onToggle,
}: {
  bet: PastBet;
  models: string[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const ts = new Date(bet.timestamp * 1000);
  const time = ts.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  const outcomeColor =
    bet.outcome === "UP" ? THEME.colors.green : THEME.colors.red;

  return (
    <div>
      <button
        onClick={onToggle}
        className={`flex w-full items-center gap-4 rounded-lg px-4 py-3 text-left font-mono text-sm transition-colors ${
          expanded ? "bg-white/5 ring-1 ring-white/10" : "hover:bg-white/[0.03]"
        }`}
      >
        <span className="w-16 text-white/40">{time}</span>
        <span
          className="w-14 rounded-md px-2 py-1 text-center text-xs font-bold"
          style={{
            backgroundColor: outcomeColor + "20",
            color: outcomeColor,
          }}
        >
          {bet.outcome}
        </span>
        {models.map((model) => {
          const s = bet.settlements[model as keyof typeof bet.settlements];
          if (!s) {
            return (
              <span key={model} className="w-28 text-white/15">
                —
              </span>
            );
          }
          const color = MODEL_COLORS[model] ?? "#888";
          return (
            <span key={model} className="flex w-28 items-center gap-2">
              <span className="font-semibold" style={{ color }}>
                {MODEL_SHORT[model]}
              </span>
              <span
                className={`font-semibold ${s.won ? "text-green-400" : "text-red-400"}`}
              >
                {s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(2)}
              </span>
            </span>
          );
        })}
        <span className="ml-auto text-xs text-white/20">
          {expanded ? "▲" : "▼"}
        </span>
      </button>
      {expanded && <BetDetail bet={bet} />}
    </div>
  );
}
