"use client";

import { useState, useCallback, useRef } from "react";
import { CandleSnapshotPoint, TradeEntry } from "@/lib/types";

interface CandlePriceChartProps {
  points: CandleSnapshotPoint[];
  trades?: TradeEntry[];
  onTradeClick?: (trade: TradeEntry) => void;
}

const W = 600;
const H = 200;
const PAD = { top: 16, right: 16, bottom: 24, left: 16 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

export function CandlePriceChart({
  points,
  trades,
  onTradeClick,
}: CandlePriceChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // Points already ordered chronologically (high tr → low tr = start → end)
  const data = points;

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      const relX = ((e.clientX - rect.left) / rect.width) * W;
      const idx = Math.round(((relX - PAD.left) / PLOT_W) * (data.length - 1));
      setHoverIdx(Math.max(0, Math.min(data.length - 1, idx)));
    },
    [data.length],
  );

  const handleMouseLeave = useCallback(() => setHoverIdx(null), []);

  // Collect all values for Y scaling
  const allVals: number[] = [];
  for (const p of data) {
    if (p.up != null) allVals.push(p.up);
    if (p.dn != null) allVals.push(p.dn);
  }
  if (data.length < 2 || allVals.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center text-xs text-zinc-500">
        Not enough data
      </div>
    );
  }

  const minVal = Math.min(...allVals);
  const maxVal = Math.max(...allVals);
  const range = maxVal - minVal || 0.01;

  const toX = (i: number) => PAD.left + (i / (data.length - 1)) * PLOT_W;
  const toY = (v: number) => PAD.top + (1 - (v - minVal) / range) * PLOT_H;

  // Build line paths
  const upLine: string[] = [];
  const dnLine: string[] = [];
  const upFill: string[] = [];
  const dnFill: string[] = [];

  for (let i = 0; i < data.length; i++) {
    const x = toX(i);
    if (data[i].up != null) {
      const y = toY(data[i].up!);
      upLine.push(`${x},${y}`);
      upFill.push(`${x},${y}`);
    }
    if (data[i].dn != null) {
      const y = toY(data[i].dn!);
      dnLine.push(`${x},${y}`);
      dnFill.push(`${x},${y}`);
    }
  }

  // Fill polygons (close to bottom of plot)
  const bottomY = PAD.top + PLOT_H;
  const upFillPoly =
    upFill.length > 1
      ? `${upFill.join(" ")} ${toX(data.length - 1)},${bottomY} ${PAD.left},${bottomY}`
      : "";
  const dnFillPoly =
    dnFill.length > 1
      ? `${dnFill.join(" ")} ${toX(data.length - 1)},${bottomY} ${PAD.left},${bottomY}`
      : "";

  // 0.50 baseline
  const baselineY = 0.5 >= minVal && 0.5 <= maxVal ? toY(0.5) : null;

  const hoverPoint = hoverIdx != null ? data[hoverIdx] : null;

  // Map trades to chart coordinates
  const trMin = data[0].tr;
  const trMax = data[data.length - 1].tr;
  const trSpan = trMax - trMin || 1;

  const tradeMarkers =
    trades && trades.length > 0
      ? trades
          .filter((t) => !t.risk_blocked)
          .map((t) => {
            const tr = t.time_remaining_at_trade;
            const frac = (tr - trMin) / trSpan;
            const x = PAD.left + frac * PLOT_W;
            let y: number;
            if (t.fill_price != null) {
              y = toY(t.fill_price);
            } else {
              const idx = Math.round(frac * (data.length - 1));
              const pt = data[Math.max(0, Math.min(data.length - 1, idx))];
              const mid =
                pt.up != null && pt.dn != null
                  ? (pt.up + pt.dn) / 2
                  : (pt.up ?? pt.dn ?? 0.5);
              y = toY(mid);
            }
            const filled = t.live_order ? !!t.live_order.fill_source : true;
            return { trade: t, x, y, filled };
          })
      : [];

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="h-[200px] w-full"
        preserveAspectRatio="none"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {/* Fill areas */}
        {upFillPoly && (
          <polygon points={upFillPoly} fill="#22c55e" opacity="0.1" />
        )}
        {dnFillPoly && (
          <polygon points={dnFillPoly} fill="#ef4444" opacity="0.1" />
        )}

        {/* Baseline at 0.50 */}
        {baselineY != null && (
          <line
            x1={PAD.left}
            y1={baselineY}
            x2={W - PAD.right}
            y2={baselineY}
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="0.5"
            strokeDasharray="4,4"
          />
        )}

        {/* UP line */}
        {upLine.length > 1 && (
          <polyline
            points={upLine.join(" ")}
            fill="none"
            stroke="#22c55e"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        )}

        {/* DOWN line */}
        {dnLine.length > 1 && (
          <polyline
            points={dnLine.join(" ")}
            fill="none"
            stroke="#ef4444"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        )}

        {/* Hover crosshair */}
        {hoverIdx != null && (
          <line
            x1={toX(hoverIdx)}
            y1={PAD.top}
            x2={toX(hoverIdx)}
            y2={bottomY}
            stroke="rgba(255,255,255,0.2)"
            strokeWidth="1"
          />
        )}

        {/* Trade markers */}
        {tradeMarkers.map((m, i) => {
          const action = m.trade.action;
          const isHold = action === "HOLD";
          const isBuy = action === "BUY";

          return (
            <g
              key={`trade-${i}`}
              className="cursor-pointer"
              onClick={(e) => {
                e.stopPropagation();
                onTradeClick?.(m.trade);
              }}
            >
              {isHold ? (
                <line
                  x1={m.x - 5}
                  y1={m.y}
                  x2={m.x + 5}
                  y2={m.y}
                  stroke="#a1a1aa"
                  strokeWidth="2"
                  strokeLinecap="round"
                  opacity={0.7}
                />
              ) : (
                <>
                  {(() => {
                    const color = isBuy ? "#22c55e" : "#ef4444";
                    const s = 6;
                    const tri = isBuy
                      ? `M${m.x},${m.y - s} L${m.x - s},${m.y + s} L${m.x + s},${m.y + s} Z`
                      : `M${m.x},${m.y + s} L${m.x - s},${m.y - s} L${m.x + s},${m.y - s} Z`;
                    return (
                      <path
                        d={tri}
                        fill={m.filled ? color : "none"}
                        stroke={color}
                        strokeWidth={m.filled ? 0 : 1.5}
                        strokeDasharray={m.filled ? undefined : "3,2"}
                        opacity={0.9}
                      />
                    );
                  })()}
                  {!m.filled && (
                    <>
                      <line
                        x1={m.x - 3}
                        y1={m.y - 3}
                        x2={m.x + 3}
                        y2={m.y + 3}
                        stroke="#f59e0b"
                        strokeWidth="1.5"
                      />
                      <line
                        x1={m.x + 3}
                        y1={m.y - 3}
                        x2={m.x - 3}
                        y2={m.y + 3}
                        stroke="#f59e0b"
                        strokeWidth="1.5"
                      />
                    </>
                  )}
                </>
              )}
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hoverPoint && hoverIdx != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded border border-white/10 bg-[#0d1117] px-2.5 py-1.5 text-[11px] leading-relaxed shadow-lg"
          style={{
            left: `${(toX(hoverIdx) / W) * 100}%`,
            transform:
              hoverIdx > data.length / 2
                ? "translateX(-110%)"
                : "translateX(10%)",
          }}
        >
          <div className="text-zinc-400">
            {Math.round(hoverPoint.tr)}s remaining
          </div>
          {hoverPoint.up != null && (
            <div className="text-green-400">UP: {hoverPoint.up.toFixed(4)}</div>
          )}
          {hoverPoint.dn != null && (
            <div className="text-red-400">DN: {hoverPoint.dn.toFixed(4)}</div>
          )}
          {hoverPoint.btc != null && (
            <div className="text-zinc-300">
              BTC: ${hoverPoint.btc.toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
