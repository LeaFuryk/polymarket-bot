"use client";

import { useMemo, useState } from "react";
import { useDashboard } from "@/context/DashboardContext";
import { MODEL_COLORS, MODEL_SHORT, THEME } from "@/lib/constants";
import type { ModelEntry } from "@/lib/types";

const W = 1000;
const H = 220;
const PAD = { top: 20, right: 50, bottom: 30, left: 10 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

// Fixed Y-axis: 0 to 1 (token prices)
const Y_MIN = 0;
const Y_MAX = 1;

// Fixed X-axis: 0% to 100% elapsed (0 to 5 minutes)
const X_TICKS = [0, 0.25, 0.5, 0.75, 1];
const Y_TICKS = [0, 0.2, 0.4, 0.6, 0.8, 1.0];

function xPos(elapsed: number): number {
  return PAD.left + Math.min(Math.max(elapsed, 0), 1) * INNER_W;
}
function yPos(price: number): number {
  return PAD.top + INNER_H - ((price - Y_MIN) / (Y_MAX - Y_MIN)) * INNER_H;
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

function formatTime(pct: number): string {
  const totalSec = pct * 300;
  const m = Math.floor(totalSec / 60);
  const s = Math.round(totalSec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

interface ModalData {
  entry: ModelEntry;
  svgX: number;
  svgY: number;
}

export function BetTimeline() {
  const { currentSnapshots, currentEntries, currentCandleId } = useDashboard();
  const [modal, setModal] = useState<ModalData | null>(null);

  const hasData = currentCandleId && currentSnapshots.length > 0;

  const upPath = useMemo(
    () =>
      buildPath(
        currentSnapshots.map((s) => ({
          elapsed_pct: s.elapsed_pct,
          price: s.up_ask,
        })),
      ),
    [currentSnapshots],
  );

  const downPath = useMemo(
    () =>
      buildPath(
        currentSnapshots.map((s) => ({
          elapsed_pct: s.elapsed_pct,
          price: s.down_ask,
        })),
      ),
    [currentSnapshots],
  );

  // Group entries and stagger overlapping ones
  const markers = useMemo(() => {
    return currentEntries.map((entry, i) => {
      const sameSpot = currentEntries.filter(
        (other, j) =>
          j < i && Math.abs(other.elapsed_pct - entry.elapsed_pct) < 0.015,
      );
      return { entry, yOffset: sameSpot.length * 24 };
    });
  }, [currentEntries]);

  return (
    <div className="relative rounded-lg bg-[#0d1017] p-4">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="font-mono text-base font-semibold text-white/70">
          {hasData
            ? `Current Bet — ${currentCandleId!.split("-").pop()}`
            : "Current Bet"}
        </h2>
        {markers.length > 0 && (
          <span className="font-mono text-[10px] text-white/30">
            click markers for details
          </span>
        )}
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ minHeight: 220 }}
      >
        {/* Grid lines */}
        {Y_TICKS.map((price) => (
          <g key={`y-${price}`}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={yPos(price)}
              y2={yPos(price)}
              stroke="white"
              strokeOpacity={0.05}
            />
            <text
              x={W - PAD.right + 4}
              y={yPos(price) + 3}
              fill="white"
              fillOpacity={0.3}
              fontSize={9}
              fontFamily="monospace"
            >
              {price.toFixed(1)}
            </text>
          </g>
        ))}
        {X_TICKS.map((pct) => (
          <g key={`x-${pct}`}>
            <line
              x1={xPos(pct)}
              x2={xPos(pct)}
              y1={PAD.top}
              y2={PAD.top + INNER_H}
              stroke="white"
              strokeOpacity={0.05}
            />
            <text
              x={xPos(pct)}
              y={H - 8}
              fill="white"
              fillOpacity={0.3}
              fontSize={10}
              fontFamily="monospace"
              textAnchor="middle"
            >
              {formatTime(pct)}
            </text>
          </g>
        ))}

        {/* 0.5 reference line (even odds) */}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={yPos(0.5)}
          y2={yPos(0.5)}
          stroke="white"
          strokeOpacity={0.1}
          strokeDasharray="4 4"
        />

        {/* UP price line */}
        {upPath && (
          <path
            d={upPath}
            fill="none"
            stroke={THEME.colors.green}
            strokeWidth={2}
            strokeOpacity={0.8}
          />
        )}

        {/* DOWN price line */}
        {downPath && (
          <path
            d={downPath}
            fill="none"
            stroke={THEME.colors.red}
            strokeWidth={2}
            strokeOpacity={0.8}
          />
        )}

        {/* Entry markers */}
        {markers.map((m, i) => {
          const color = MODEL_COLORS[m.entry.model] ?? "#888";
          const short = MODEL_SHORT[m.entry.model] ?? m.entry.model;
          const cx = xPos(m.entry.elapsed_pct);
          const cy = yPos(m.entry.price);
          const isSelected = modal?.entry === m.entry;

          return (
            <g
              key={`${m.entry.model}-${m.entry.checkpoint}-${i}`}
              style={{ cursor: "pointer" }}
              onClick={() =>
                setModal(
                  isSelected ? null : { entry: m.entry, svgX: cx, svgY: cy },
                )
              }
            >
              {/* Vertical line from marker to price */}
              <line
                x1={cx}
                x2={cx}
                y1={PAD.top + m.yOffset + 8}
                y2={cy}
                stroke={color}
                strokeOpacity={0.3}
                strokeWidth={1}
                strokeDasharray="2 2"
              />
              {/* Marker pill */}
              <rect
                x={cx - 22}
                y={PAD.top + m.yOffset - 8}
                width={44}
                height={16}
                rx={8}
                fill={color + "30"}
                stroke={isSelected ? color : color + "60"}
                strokeWidth={isSelected ? 2 : 1}
              />
              <text
                x={cx}
                y={PAD.top + m.yOffset + 2}
                fill={color}
                fontSize={8}
                fontFamily="monospace"
                fontWeight="bold"
                textAnchor="middle"
              >
                {short} {m.entry.direction === "UP" ? "▲" : "▼"}
              </text>
              {/* Price dot on the line */}
              <circle
                cx={cx}
                cy={cy}
                r={3}
                fill={color}
                stroke="white"
                strokeWidth={0.5}
              />
            </g>
          );
        })}

        {/* Legend */}
        <circle cx={PAD.left + 8} cy={10} r={4} fill={THEME.colors.green} />
        <text
          x={PAD.left + 16}
          y={13}
          fill={THEME.colors.green}
          fontSize={10}
          fontFamily="monospace"
        >
          UP
        </text>
        <circle cx={PAD.left + 48} cy={10} r={4} fill={THEME.colors.red} />
        <text
          x={PAD.left + 56}
          y={13}
          fill={THEME.colors.red}
          fontSize={10}
          fontFamily="monospace"
        >
          DOWN
        </text>

        {/* No data message */}
        {!hasData && (
          <text
            x={W / 2}
            y={H / 2}
            fill="white"
            fillOpacity={0.2}
            fontSize={14}
            fontFamily="monospace"
            textAnchor="middle"
          >
            Waiting for candle...
          </text>
        )}
      </svg>

      {/* Entry detail modal */}
      {modal && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setModal(null)} />
          <div
            className="absolute z-50 rounded-lg border border-white/10 bg-[#131720] p-3 font-mono text-xs shadow-xl"
            style={{
              left: `${(modal.svgX / W) * 100}%`,
              top: `${(modal.svgY / H) * 100 + 5}%`,
              transform: "translateX(-50%)",
              minWidth: 200,
            }}
          >
            <div className="mb-2 flex items-center justify-between">
              <span
                className="text-sm font-bold"
                style={{ color: MODEL_COLORS[modal.entry.model] ?? "#888" }}
              >
                {modal.entry.model}
              </span>
              <button
                className="text-white/30 hover:text-white"
                onClick={() => setModal(null)}
              >
                ✕
              </button>
            </div>
            <div className="space-y-1 text-white/60">
              <Row
                label="Direction"
                value={modal.entry.direction}
                color={
                  modal.entry.direction === "UP"
                    ? THEME.colors.green
                    : THEME.colors.red
                }
              />
              <Row
                label="Entry Price"
                value={`$${modal.entry.price.toFixed(4)}`}
              />
              <Row
                label="Amount"
                value={`$${modal.entry.amount_usd.toFixed(2)}`}
              />
              <Row
                label="Confidence"
                value={`${(modal.entry.confidence * 100).toFixed(1)}%`}
              />
              <Row
                label="Inference"
                value={`${modal.entry.inference_ms.toFixed(1)}ms`}
              />
              <Row label="Checkpoint" value={`#${modal.entry.checkpoint}`} />
              <Row
                label="Elapsed"
                value={`${(modal.entry.elapsed_pct * 100).toFixed(1)}%`}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="flex justify-between gap-4">
      <span>{label}</span>
      <span className="text-white" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}
