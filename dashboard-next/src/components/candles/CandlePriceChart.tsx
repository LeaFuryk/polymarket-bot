"use client";

import { useState, useCallback, useRef } from "react";
import { CandleSnapshotPoint, TradeEntry } from "@/lib/types";

interface CandlePriceChartProps {
  points: CandleSnapshotPoint[];
  trades?: TradeEntry[];
  onTradeClick?: (trade: TradeEntry) => void;
}

const W = 600;
const H = 220;
const PAD = { top: 16, right: 36, bottom: 40, left: 36 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;
const CANDLE_DURATION = 300; // 5 minutes in seconds

export function CandlePriceChart({
  points,
  trades,
  onTradeClick,
}: CandlePriceChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const data = points;

  // X axis always represents the full 300s candle
  // elapsed = CANDLE_DURATION - tr (tr=300 → elapsed=0, tr=0 → elapsed=300)
  const elapsedToX = (elapsed: number) =>
    PAD.left + (elapsed / CANDLE_DURATION) * PLOT_W;

  const trToX = (tr: number) => elapsedToX(CANDLE_DURATION - tr);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!svgRef.current || data.length === 0) return;
      const rect = svgRef.current.getBoundingClientRect();
      const relX = ((e.clientX - rect.left) / rect.width) * W;
      // Convert pixel X to elapsed time, then find closest data point
      const elapsed = ((relX - PAD.left) / PLOT_W) * CANDLE_DURATION;
      const targetTr = CANDLE_DURATION - elapsed;
      // Binary-ish search: data is sorted high-tr → low-tr
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

  const handleMouseLeave = useCallback(() => setHoverIdx(null), []);

  if (data.length < 2) {
    return (
      <div className="flex h-[220px] items-center justify-center text-xs text-zinc-500">
        Not enough data
      </div>
    );
  }

  // Fixed Y axis: 0 at bottom, 1 at top
  const toY = (v: number) => PAD.top + (1 - v) * PLOT_H;

  // Current prices (last data point with valid values)
  let currentUp: number | null = null;
  let currentDn: number | null = null;
  for (let i = data.length - 1; i >= 0; i--) {
    if (currentUp == null && data[i].up != null) currentUp = data[i].up;
    if (currentDn == null && data[i].dn != null) currentDn = data[i].dn;
    if (currentUp != null && currentDn != null) break;
  }

  // Build line paths — X positioned by time remaining
  const upLine: string[] = [];
  const dnLine: string[] = [];
  const upFill: string[] = [];
  const dnFill: string[] = [];

  for (let i = 0; i < data.length; i++) {
    const x = trToX(data[i].tr);
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

  // Fill polygons — close to bottom at the last data point's X (not full width)
  const bottomY = PAD.top + PLOT_H;
  const lastX = trToX(data[data.length - 1].tr);
  const firstX = trToX(data[0].tr);
  const upFillPoly =
    upFill.length > 1
      ? `${upFill.join(" ")} ${lastX},${bottomY} ${firstX},${bottomY}`
      : "";
  const dnFillPoly =
    dnFill.length > 1
      ? `${dnFill.join(" ")} ${lastX},${bottomY} ${firstX},${bottomY}`
      : "";

  // Y-axis ticks
  const yTicks = [0, 0.25, 0.5, 0.75, 1.0];

  const hoverPoint = hoverIdx != null ? data[hoverIdx] : null;
  const hoverX = hoverIdx != null ? trToX(data[hoverIdx].tr) : 0;

  // Time axis ticks — always full 5 minutes (0:00 → 5:00)
  const timeTicks: { x: number; label: string }[] = [];
  for (let elapsed = 0; elapsed <= CANDLE_DURATION; elapsed += 60) {
    const x = elapsedToX(elapsed);
    const m = Math.floor(elapsed / 60);
    timeTicks.push({ x, label: `${m}:00` });
  }

  // Trade markers — position by time_remaining_at_trade
  const tradeMarkers =
    trades && trades.length > 0
      ? trades
          .filter((t) => !t.risk_blocked)
          .map((t) => {
            const x = trToX(t.time_remaining_at_trade);
            let y: number;
            if (t.fill_price != null) {
              y = toY(t.fill_price);
            } else {
              // HOLDs: find closest data point for midpoint
              let closest = 0;
              let minDist = Infinity;
              for (let i = 0; i < data.length; i++) {
                const d = Math.abs(data[i].tr - t.time_remaining_at_trade);
                if (d < minDist) {
                  minDist = d;
                  closest = i;
                }
              }
              const pt = data[closest];
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
        className="h-[220px] w-full"
        preserveAspectRatio="none"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {/* Y-axis grid lines and labels */}
        {yTicks.map((v) => {
          const y = toY(v);
          const isBound = v === 0 || v === 1;
          return (
            <g key={`y-${v}`}>
              <line
                x1={PAD.left}
                y1={y}
                x2={W - PAD.right}
                y2={y}
                stroke={
                  isBound ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.05)"
                }
                strokeWidth={isBound ? "1" : "0.5"}
                strokeDasharray={isBound ? undefined : "4,4"}
              />
              <text
                x={PAD.left - 4}
                y={y + 3}
                textAnchor="end"
                fill="rgba(255,255,255,0.3)"
                fontSize="8"
                fontFamily="monospace"
              >
                {v.toFixed(2)}
              </text>
            </g>
          );
        })}

        {/* Fill areas */}
        {upFillPoly && (
          <polygon points={upFillPoly} fill="#22c55e" opacity="0.1" />
        )}
        {dnFillPoly && (
          <polygon points={dnFillPoly} fill="#ef4444" opacity="0.1" />
        )}

        {/* Current UP price line */}
        {currentUp != null && (
          <>
            <line
              x1={PAD.left}
              y1={toY(currentUp)}
              x2={W - PAD.right}
              y2={toY(currentUp)}
              stroke="#22c55e"
              strokeWidth="0.75"
              strokeDasharray="6,3"
              opacity={0.5}
            />
            <text
              x={W - PAD.right + 2}
              y={toY(currentUp) + 3}
              fill="#22c55e"
              fontSize="8"
              fontFamily="monospace"
              opacity={0.7}
            >
              {currentUp.toFixed(2)}
            </text>
          </>
        )}

        {/* Current DOWN price line */}
        {currentDn != null && (
          <>
            <line
              x1={PAD.left}
              y1={toY(currentDn)}
              x2={W - PAD.right}
              y2={toY(currentDn)}
              stroke="#ef4444"
              strokeWidth="0.75"
              strokeDasharray="6,3"
              opacity={0.5}
            />
            <text
              x={W - PAD.right + 2}
              y={toY(currentDn) + 3}
              fill="#ef4444"
              fontSize="8"
              fontFamily="monospace"
              opacity={0.7}
            >
              {currentDn.toFixed(2)}
            </text>
          </>
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
            x1={hoverX}
            y1={PAD.top}
            x2={hoverX}
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

        {/* Time axis — always full 0:00 → 5:00 */}
        {timeTicks.map((tick, ti) => (
          <g key={ti}>
            <line
              x1={tick.x}
              y1={bottomY}
              x2={tick.x}
              y2={bottomY + 4}
              stroke="rgba(255,255,255,0.15)"
              strokeWidth="1"
            />
            <text
              x={tick.x}
              y={bottomY + 16}
              textAnchor="middle"
              fill="rgba(255,255,255,0.3)"
              fontSize="9"
              fontFamily="monospace"
            >
              {tick.label}
            </text>
          </g>
        ))}
      </svg>

      {/* Tooltip */}
      {hoverPoint && hoverIdx != null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded border border-white/10 bg-[#0d1117] px-2.5 py-1.5 text-[11px] leading-relaxed shadow-lg"
          style={{
            left: `${(hoverX / W) * 100}%`,
            transform: hoverX > W / 2 ? "translateX(-110%)" : "translateX(10%)",
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
