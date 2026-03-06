"use client";

import { useState, useCallback, useRef, useMemo } from "react";
import { CandleSnapshotPoint } from "@/lib/types";

interface BtcMoveChartProps {
  points: CandleSnapshotPoint[];
}

const W = 600;
const H = 160;
const PAD = { top: 12, right: 36, bottom: 28, left: 44 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;
const CANDLE_DURATION = 300;

export function BtcMoveChart({ points }: BtcMoveChartProps) {
  const [visible, setVisible] = useState(true);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const data = useMemo(() => points.filter((p) => p.btc_mv != null), [points]);

  // Compute symmetric Y range around 0
  const maxAbs = useMemo(() => {
    if (data.length === 0) return 50;
    const m = Math.max(...data.map((p) => Math.abs(p.btc_mv!)));
    return Math.max(m * 1.15, 5); // at least $5 range, 15% padding
  }, [data]);

  const trToX = (tr: number) =>
    PAD.left + ((CANDLE_DURATION - tr) / CANDLE_DURATION) * PLOT_W;
  const valToY = useCallback(
    (v: number) => PAD.top + PLOT_H / 2 - (v / maxAbs) * (PLOT_H / 2),
    [maxAbs],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!svgRef.current || data.length === 0) return;
      const rect = svgRef.current.getBoundingClientRect();
      const relX = ((e.clientX - rect.left) / rect.width) * W;
      const elapsed = ((relX - PAD.left) / PLOT_W) * CANDLE_DURATION;
      const targetTr = CANDLE_DURATION - elapsed;
      let closest = 0;
      let minDist = Infinity;
      for (let i = 0; i < data.length; i++) {
        const dist = Math.abs(data[i].tr - targetTr);
        if (dist < minDist) {
          minDist = dist;
          closest = i;
        }
      }
      setHoverIdx(closest);
    },
    [data],
  );

  // Build SVG path
  const linePath = useMemo(() => {
    if (data.length === 0) return "";
    return data
      .map((p, i) => {
        const x = trToX(p.tr);
        const y = valToY(p.btc_mv!);
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [data, valToY]);

  // Gradient fill path (area between line and zero)
  const areaPath = useMemo(() => {
    if (data.length === 0) return "";
    const zeroY = valToY(0);
    const first = data[0];
    const last = data[data.length - 1];
    return `${linePath} L${trToX(last.tr).toFixed(1)},${zeroY.toFixed(1)} L${trToX(first.tr).toFixed(1)},${zeroY.toFixed(1)} Z`;
  }, [data, linePath, valToY]);

  // Time labels
  const timeLabels = [0, 60, 120, 180, 240, 300];
  const fmtTime = (s: number) =>
    `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  // Y-axis labels
  const yTicks = useMemo(() => {
    const step = maxAbs > 100 ? 50 : maxAbs > 40 ? 20 : maxAbs > 15 ? 10 : 5;
    const ticks: number[] = [0];
    for (let v = step; v <= maxAbs; v += step) {
      ticks.push(v);
      ticks.push(-v);
    }
    return ticks;
  }, [maxAbs]);

  if (data.length < 2) return null;

  const hoverPt = hoverIdx != null ? data[hoverIdx] : null;
  const lastMove = data[data.length - 1]?.btc_mv ?? 0;
  const lineColor = lastMove >= 0 ? "#4ade80" : "#f87171";

  return (
    <div className="mt-3">
      <div className="mb-2 flex items-center justify-between">
        <button
          onClick={() => setVisible((v) => !v)}
          className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wider text-zinc-500 uppercase hover:text-zinc-300"
        >
          <svg
            className={`h-3 w-3 transition-transform ${visible ? "rotate-0" : "-rotate-90"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19 9l-7 7-7-7"
            />
          </svg>
          BTC Move
        </button>
        {hoverPt ? (
          <span className="font-mono text-[11px] text-zinc-400">
            {fmtTime(CANDLE_DURATION - hoverPt.tr)}{" "}
            <span
              className={
                hoverPt.btc_mv! >= 0 ? "text-green-400" : "text-red-400"
              }
            >
              {hoverPt.btc_mv! > 0 ? "+" : ""}${hoverPt.btc_mv!.toFixed(1)}
            </span>
          </span>
        ) : (
          <span
            className={`font-mono text-[11px] ${lastMove >= 0 ? "text-green-400" : "text-red-400"}`}
          >
            {lastMove > 0 ? "+" : ""}${lastMove.toFixed(1)}
          </span>
        )}
      </div>

      {visible && (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {/* Y-axis grid + labels */}
          {yTicks.map((v) => {
            const y = valToY(v);
            return (
              <g key={v}>
                <line
                  x1={PAD.left}
                  y1={y}
                  x2={W - PAD.right}
                  y2={y}
                  stroke={
                    v === 0
                      ? "rgba(255,255,255,0.15)"
                      : "rgba(255,255,255,0.04)"
                  }
                  strokeWidth={v === 0 ? 1 : 0.5}
                  strokeDasharray={v === 0 ? undefined : "4 4"}
                />
                <text
                  x={PAD.left - 4}
                  y={y + 3}
                  textAnchor="end"
                  fill="#71717a"
                  fontSize={9}
                  fontFamily="monospace"
                >
                  {v > 0 ? "+" : ""}
                  {v}
                </text>
              </g>
            );
          })}

          {/* Time labels */}
          {timeLabels.map((s) => (
            <text
              key={s}
              x={PAD.left + (s / CANDLE_DURATION) * PLOT_W}
              y={H - 6}
              textAnchor="middle"
              fill="#52525b"
              fontSize={9}
              fontFamily="monospace"
            >
              {fmtTime(s)}
            </text>
          ))}

          {/* Area fill */}
          <path
            d={areaPath}
            fill={
              lastMove >= 0 ? "rgba(74,222,128,0.08)" : "rgba(248,113,113,0.08)"
            }
          />

          {/* Line */}
          <path d={linePath} fill="none" stroke={lineColor} strokeWidth={1.5} />

          {/* Hover crosshair */}
          {hoverPt && (
            <>
              <line
                x1={trToX(hoverPt.tr)}
                y1={PAD.top}
                x2={trToX(hoverPt.tr)}
                y2={H - PAD.bottom}
                stroke="rgba(255,255,255,0.2)"
                strokeWidth={1}
              />
              <circle
                cx={trToX(hoverPt.tr)}
                cy={valToY(hoverPt.btc_mv!)}
                r={3.5}
                fill={lineColor}
                stroke="#131720"
                strokeWidth={1.5}
              />
            </>
          )}
        </svg>
      )}
    </div>
  );
}
