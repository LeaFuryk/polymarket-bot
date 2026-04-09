"use client";

import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT } from "@/lib/constants";

const W = 900;
const H = 220;
const PAD = { top: 15, right: 60, bottom: 30, left: 55 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

export function EquityChart() {
  const { equityHistory, portfolios } = useDashboard();

  const models = Object.keys(equityHistory);
  if (models.length === 0) {
    return (
      <div className="flex h-52 items-center justify-center rounded-lg bg-[#0d1017] font-mono text-sm text-white/30">
        Waiting for settlements...
      </div>
    );
  }

  const firstPortfolio = Object.values(portfolios)[0];
  const initialCash = firstPortfolio?.initial_cash ?? 1000;

  const allValues = models.flatMap((m) => equityHistory[m]);
  const maxLen = Math.max(...models.map((m) => equityHistory[m].length));
  const minV = Math.min(initialCash, ...allValues);
  const maxV = Math.max(initialCash, ...allValues);
  const range = maxV - minV || 1;
  const pad = range * 0.1;

  function xPos(i: number): number {
    return PAD.left + (maxLen > 1 ? (i / (maxLen - 1)) * INNER_W : INNER_W / 2);
  }
  function yPos(val: number): number {
    return (
      PAD.top + INNER_H - ((val - minV + pad) / (range + pad * 2)) * INNER_H
    );
  }

  // Y-axis ticks: ~5 nice round values
  const yStep = Math.ceil(range / 4 / 10) * 10; // round to nearest 10
  const yTickStart = Math.floor((minV - pad) / yStep) * yStep;
  const yTicks: number[] = [];
  for (let v = yTickStart; v <= maxV + pad; v += yStep) {
    yTicks.push(v);
  }

  // X-axis ticks: every N bets
  const xStep = maxLen <= 10 ? 1 : maxLen <= 50 ? 5 : maxLen <= 200 ? 10 : 25;
  const xTicks: number[] = [];
  for (let i = 0; i < maxLen; i += xStep) {
    xTicks.push(i);
  }
  if (xTicks[xTicks.length - 1] !== maxLen - 1 && maxLen > 1) {
    xTicks.push(maxLen - 1);
  }

  const refY = yPos(initialCash);

  return (
    <div className="rounded-lg bg-[#0d1017] p-4">
      <h2 className="mb-3 font-mono text-base font-semibold text-white/70">
        Portfolio Equity
      </h2>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ minHeight: 220 }}
      >
        {/* Y-axis grid + labels */}
        {yTicks.map((v) => {
          const y = yPos(v);
          if (y < PAD.top || y > PAD.top + INNER_H) return null;
          return (
            <g key={`y-${v}`}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y}
                y2={y}
                stroke="white"
                strokeOpacity={0.05}
              />
              <text
                x={PAD.left - 6}
                y={y + 3}
                fill="white"
                fillOpacity={0.3}
                fontSize={11}
                textAnchor="end"
                fontFamily="monospace"
              >
                ${v.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* X-axis grid + labels (bet number) */}
        {xTicks.map((i) => {
          const x = xPos(i);
          return (
            <g key={`x-${i}`}>
              <line
                x1={x}
                x2={x}
                y1={PAD.top}
                y2={PAD.top + INNER_H}
                stroke="white"
                strokeOpacity={0.03}
              />
              <text
                x={x}
                y={H - 8}
                fill="white"
                fillOpacity={0.3}
                fontSize={11}
                textAnchor="middle"
                fontFamily="monospace"
              >
                {i}
              </text>
            </g>
          );
        })}

        {/* X-axis label */}
        <text
          x={W / 2}
          y={H - 0}
          fill="white"
          fillOpacity={0.2}
          fontSize={10}
          textAnchor="middle"
          fontFamily="monospace"
        >
          bets
        </text>

        {/* Initial cash reference line */}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={refY}
          y2={refY}
          stroke="white"
          strokeOpacity={0.15}
          strokeDasharray="4 2"
        />

        {/* Equity lines */}
        {models.map((model) => {
          const data = equityHistory[model];
          if (data.length < 2) return null;
          const path = data
            .map((v, i) => `${i === 0 ? "M" : "L"}${xPos(i)},${yPos(v)}`)
            .join(" ");
          const color = MODEL_COLORS[model] ?? "#888";
          const short = MODEL_SHORT[model] ?? model;
          const last = data[data.length - 1];
          return (
            <g key={model}>
              <path d={path} fill="none" stroke={color} strokeWidth={2} />
              {/* End label */}
              <text
                x={W - PAD.right + 4}
                y={yPos(last)}
                fill={color}
                fontSize={11}
                fontFamily="monospace"
                dominantBaseline="middle"
              >
                {short} ${last.toFixed(0)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
