"use client";

import { CandleSnapshot } from "@/lib/types";
import { formatCandleSlug, formatBtcPrice } from "@/lib/format";
import { StatusBadge } from "@/components/shared/StatusBadge";

interface CandleCardProps {
  slug: string;
  candle: CandleSnapshot;
  selected: boolean;
  onClick: () => void;
  tradeCount?: number;
}

function MiniSparkline({ candle }: { candle: CandleSnapshot }) {
  const pts = candle.points;
  if (pts.length < 2) return null;

  const w = 120;
  const h = 32;
  const pad = 2;

  // Collect all non-null UP and DOWN values for scaling
  const allVals: number[] = [];
  for (const p of pts) {
    if (p.up != null) allVals.push(p.up);
    if (p.dn != null) allVals.push(p.dn);
  }
  if (allVals.length === 0) return null;

  const min = Math.min(...allVals);
  const max = Math.max(...allVals);
  const range = max - min || 0.01;

  const toX = (i: number) => pad + (i / (pts.length - 1)) * (w - pad * 2);
  const toY = (v: number) => pad + (1 - (v - min) / range) * (h - pad * 2);

  // Points already ordered chronologically (high tr → low tr)
  const upPoints: string[] = [];
  const dnPoints: string[] = [];
  for (let i = 0; i < pts.length; i++) {
    if (pts[i].up != null) upPoints.push(`${toX(i)},${toY(pts[i].up!)}`);
    if (pts[i].dn != null) dnPoints.push(`${toX(i)},${toY(pts[i].dn!)}`);
  }

  const baseY = toY(0.5);

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="h-8 w-full"
      preserveAspectRatio="none"
    >
      <line
        x1={pad}
        y1={baseY}
        x2={w - pad}
        y2={baseY}
        stroke="rgba(255,255,255,0.06)"
        strokeWidth="0.5"
      />
      {upPoints.length > 1 && (
        <polyline
          points={upPoints.join(" ")}
          fill="none"
          stroke="#22c55e"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      )}
      {dnPoints.length > 1 && (
        <polyline
          points={dnPoints.join(" ")}
          fill="none"
          stroke="#ef4444"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      )}
    </svg>
  );
}

function winnerVariant(winner: string | null): "green" | "red" | "zinc" {
  if (winner === "Up") return "green";
  if (winner === "Down") return "red";
  return "zinc";
}

function winnerLabel(winner: string | null): string {
  if (winner === "Up") return "UP";
  if (winner === "Down") return "DOWN";
  return "OPEN";
}

export function CandleCard({
  slug,
  candle,
  selected,
  onClick,
  tradeCount,
}: CandleCardProps) {
  return (
    <button
      onClick={onClick}
      className={`flex min-w-[160px] flex-col gap-1.5 rounded-lg border p-3 text-left transition-colors ${
        selected
          ? "border-cyan-500/40 bg-[#131720]"
          : "border-white/5 bg-[#131720] hover:border-white/10"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium text-zinc-300">
          {formatCandleSlug(slug)}
        </span>
        <StatusBadge
          label={winnerLabel(candle.winner)}
          variant={winnerVariant(candle.winner)}
        />
      </div>
      <MiniSparkline candle={candle} />
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-zinc-500">
          BTC {formatBtcPrice(candle.btc_open)}
        </span>
        {tradeCount != null && tradeCount > 0 && (
          <span className="rounded-full bg-cyan-500/15 px-1.5 py-0.5 text-[9px] font-medium text-cyan-400">
            {tradeCount} trade{tradeCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    </button>
  );
}
