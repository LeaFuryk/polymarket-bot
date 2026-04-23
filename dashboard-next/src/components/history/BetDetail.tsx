"use client";

import { MODEL_COLORS, MODEL_SHORT, THEME } from "@/lib/constants";
import type { PastBet } from "@/lib/types";

const W = 700;
const H = 140;
const PAD = { top: 15, right: 10, bottom: 20, left: 35 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

export function BetDetail({ bet }: { bet: PastBet }) {
  const { snapshots, entries } = bet;

  if (snapshots.length === 0) {
    return (
      <div className="px-3 py-2 font-mono text-xs text-white/30">
        No snapshot data for this candle
      </div>
    );
  }

  const upPrices = snapshots
    .map((s) => s.up_ask)
    .filter((p): p is number => p !== null);
  const downPrices = snapshots
    .map((s) => s.down_ask)
    .filter((p): p is number => p !== null);
  const allPrices = [...upPrices, ...downPrices];
  const minP = allPrices.length > 0 ? Math.min(...allPrices) : 0;
  const maxP = allPrices.length > 0 ? Math.max(...allPrices) : 1;
  const range = maxP - minP || 0.1;
  const ppad = range * 0.1;

  function xPos(elapsed: number): number {
    return PAD.left + Math.min(elapsed, 1) * INNER_W;
  }
  function yPos(price: number): number {
    return (
      PAD.top + INNER_H - ((price - minP + ppad) / (range + ppad * 2)) * INNER_H
    );
  }

  function buildPath(
    points: { elapsed_pct: number; price: number | null }[],
  ): string {
    const valid = points.filter((p) => p.price !== null);
    if (valid.length === 0) return "";
    return valid
      .map(
        (p, i) =>
          `${i === 0 ? "M" : "L"}${xPos(p.elapsed_pct)},${yPos(p.price!)}`,
      )
      .join(" ");
  }

  const upPath = buildPath(
    snapshots.map((s) => ({ elapsed_pct: s.elapsed_pct, price: s.up_ask })),
  );
  const downPath = buildPath(
    snapshots.map((s) => ({ elapsed_pct: s.elapsed_pct, price: s.down_ask })),
  );
  const outcomeColor =
    bet.outcome === "UP" ? THEME.colors.green : THEME.colors.red;

  return (
    <div className="mx-3 mb-2 rounded bg-[#131720] p-3">
      <div className="mb-1 flex items-center gap-2 font-mono text-[10px] text-white/40">
        <span>Outcome:</span>
        <span style={{ color: outcomeColor }} className="font-bold">
          {bet.outcome}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {[0.25, 0.5, 0.75].map((pct) => (
          <line
            key={pct}
            x1={xPos(pct)}
            x2={xPos(pct)}
            y1={PAD.top}
            y2={PAD.top + INNER_H}
            stroke="white"
            strokeOpacity={0.05}
          />
        ))}

        {upPath && (
          <path
            d={upPath}
            fill="none"
            stroke={THEME.colors.green}
            strokeWidth={1.5}
            strokeOpacity={0.7}
          />
        )}
        {downPath && (
          <path
            d={downPath}
            fill="none"
            stroke={THEME.colors.red}
            strokeWidth={1.5}
            strokeOpacity={0.7}
          />
        )}

        {entries.map((entry, i) => {
          const color = MODEL_COLORS[entry.model] ?? "#888";
          const short = MODEL_SHORT[entry.model] ?? entry.model;
          const cy = yPos(entry.price);
          const cx = xPos(entry.elapsed_pct);
          return (
            <g key={`${entry.model}-${entry.checkpoint}-${i}`}>
              <circle
                cx={cx}
                cy={cy}
                r={4}
                fill={color}
                stroke="white"
                strokeWidth={0.5}
              />
              <text
                x={cx}
                y={cy - 8}
                fill={color}
                fontSize={7}
                textAnchor="middle"
                fontFamily="monospace"
                fontWeight="bold"
              >
                {short}
              </text>
            </g>
          );
        })}

        {[0, 0.5, 1].map((pct) => (
          <text
            key={pct}
            x={xPos(pct)}
            y={H - 3}
            fill="white"
            fillOpacity={0.3}
            fontSize={8}
            textAnchor="middle"
            fontFamily="monospace"
          >
            {`${Math.floor(pct * 5)}:${String(Math.round(((pct * 5) % 1) * 60)).padStart(2, "0")}`}
          </text>
        ))}
      </svg>
    </div>
  );
}
