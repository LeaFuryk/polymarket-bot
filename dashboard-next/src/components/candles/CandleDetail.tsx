"use client";

import { useState } from "react";
import { CandleSnapshot, TradeEntry } from "@/lib/types";
import {
  formatCandleSlug,
  formatBtcPrice,
  formatCurrency,
  formatFillSource,
  formatTime,
} from "@/lib/format";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { CandlePriceChart } from "./CandlePriceChart";

interface CandleDetailProps {
  slug: string;
  candle: CandleSnapshot;
  trades?: TradeEntry[];
}

function MetricCell({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <div className="text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-sm text-zinc-200">
        {value ?? "—"}
      </div>
    </div>
  );
}

function winnerVariant(winner: string | null): "green" | "red" | "zinc" {
  if (winner === "Up") return "green";
  if (winner === "Down") return "red";
  return "zinc";
}

function winnerLabel(winner: string | null): string {
  if (winner === "Up") return "UP WIN";
  if (winner === "Down") return "DOWN WIN";
  return "OPEN";
}

export function CandleDetail({ slug, candle, trades }: CandleDetailProps) {
  const [expandedTradeTs, setExpandedTradeTs] = useState<string | null>(null);

  const handleTradeClick = (trade: TradeEntry) => {
    setExpandedTradeTs((prev) =>
      prev === trade.timestamp ? null : trade.timestamp,
    );
  };
  const pts = candle.points;
  if (pts.length === 0) return null;

  // Use the last point (earliest time, i.e. final values) for final metrics
  const last = pts[0]; // pts[0] has lowest tr = end of candle
  const first = pts[pts.length - 1]; // highest tr = start of candle

  // Use first point that has values for "final" state (lowest tr)
  const final = last;

  // Compute averages for spreads and depth
  const validSpreads = pts.filter((p) => p.u_sp != null && p.d_sp != null);
  const avgUpSpread =
    validSpreads.length > 0
      ? validSpreads.reduce((s, p) => s + p.u_sp!, 0) / validSpreads.length
      : null;
  const avgDnSpread =
    validSpreads.length > 0
      ? validSpreads.reduce((s, p) => s + p.d_sp!, 0) / validSpreads.length
      : null;

  const validDepth = pts.filter((p) => p.u_dep != null && p.d_dep != null);
  const avgUpDepth =
    validDepth.length > 0
      ? validDepth.reduce((s, p) => s + p.u_dep!, 0) / validDepth.length
      : null;
  const avgDnDepth =
    validDepth.length > 0
      ? validDepth.reduce((s, p) => s + p.d_dep!, 0) / validDepth.length
      : null;

  return (
    <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
      {/* Header */}
      <div className="mb-4 flex items-center gap-3">
        <span className="text-sm font-medium text-zinc-200">
          {formatCandleSlug(slug)}
        </span>
        <StatusBadge
          label={winnerLabel(candle.winner)}
          variant={winnerVariant(candle.winner)}
        />
        <span className="text-xs text-zinc-500">
          BTC {formatBtcPrice(candle.btc_open)}
        </span>
      </div>

      {/* Chart */}
      <CandlePriceChart
        points={pts}
        trades={trades}
        onTradeClick={handleTradeClick}
      />

      {/* Metrics grid */}
      <div className="mt-4 grid grid-cols-3 gap-x-6 gap-y-3 sm:grid-cols-4 lg:grid-cols-6">
        <MetricCell
          label="Final UP"
          value={final.up != null ? final.up.toFixed(4) : null}
        />
        <MetricCell
          label="Final DN"
          value={final.dn != null ? final.dn.toFixed(4) : null}
        />
        <MetricCell
          label="BTC Move"
          value={
            final.btc_mv != null
              ? `${final.btc_mv > 0 ? "+" : ""}${final.btc_mv.toFixed(1)}`
              : null
          }
        />
        <MetricCell
          label="Avg Spread"
          value={
            avgUpSpread != null && avgDnSpread != null
              ? `${avgUpSpread.toFixed(1)} / ${avgDnSpread.toFixed(1)}`
              : null
          }
        />
        <MetricCell
          label="Avg Depth"
          value={
            avgUpDepth != null && avgDnDepth != null
              ? `${avgUpDepth.toFixed(0)} / ${avgDnDepth.toFixed(0)}`
              : null
          }
        />
        <MetricCell
          label="R/R"
          value={
            final.rr_u != null && final.rr_d != null
              ? `${final.rr_u.toFixed(2)} / ${final.rr_d.toFixed(2)}`
              : null
          }
        />
        <MetricCell
          label="Streak"
          value={final.stk != null ? `${final.stk} ${final.stk_d ?? ""}` : null}
        />
        <MetricCell label="Samples" value={`${pts.length}`} />
      </div>

      {/* Trades for this candle */}
      {trades && trades.length > 0 && (
        <div className="mt-4">
          <h4 className="mb-2 text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
            Trades ({trades.length})
          </h4>
          <div className="space-y-1.5">
            {trades.map((t, i) => {
              const isExpanded = expandedTradeTs === t.timestamp;
              const lo = t.live_order;
              const filled = lo ? !!lo.fill_source : true;
              return (
                <button
                  key={`${t.timestamp}-${i}`}
                  onClick={() => handleTradeClick(t)}
                  className={`w-full rounded border text-left text-xs transition-colors ${
                    isExpanded
                      ? "border-cyan-500/40 bg-cyan-500/5"
                      : "border-white/5 bg-[#0d1017] hover:border-white/10"
                  }`}
                >
                  {/* Collapsed row — always visible */}
                  <div className="flex items-center gap-2 p-2">
                    <StatusBadge
                      label={t.action}
                      variant={
                        t.action === "BUY"
                          ? "green"
                          : t.action === "SELL"
                            ? "red"
                            : "zinc"
                      }
                    />
                    <StatusBadge
                      label={t.token_side}
                      variant={t.token_side === "up" ? "green" : "red"}
                    />
                    {lo && (
                      <StatusBadge
                        label={filled ? "FILLED" : "TIMEOUT"}
                        variant={filled ? "green" : "amber"}
                      />
                    )}
                    {t.risk_blocked && (
                      <StatusBadge label="BLOCKED" variant="red" />
                    )}
                    <span className="ml-auto flex items-center gap-3">
                      <span className="font-mono text-zinc-300">
                        {t.fill_price ? `$${t.fill_price.toFixed(4)}` : "---"}
                      </span>
                      <span className="font-mono text-zinc-400">
                        {t.size?.toFixed(2) ?? "0"}
                      </span>
                      <span className="font-mono text-[11px] text-zinc-500">
                        {formatTime(t.timestamp)}
                      </span>
                      <svg
                        className={`h-3.5 w-3.5 text-zinc-500 transition-transform ${isExpanded ? "rotate-180" : ""}`}
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
                    </span>
                  </div>

                  {/* Expanded detail — only when tapped */}
                  {isExpanded && (
                    <div className="space-y-3 border-t border-white/5 px-3 py-3">
                      {/* Price / Size / Conf / PnL */}
                      <div className="grid grid-cols-3 gap-x-4 gap-y-2 sm:grid-cols-6">
                        <div>
                          <div className="text-[10px] text-zinc-500">
                            Fill Price
                          </div>
                          <div className="font-mono text-zinc-200">
                            {t.fill_price
                              ? `$${t.fill_price.toFixed(4)}`
                              : "---"}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-zinc-500">Size</div>
                          <div className="font-mono text-zinc-200">
                            {t.size?.toFixed(2) ?? "---"}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-zinc-500">
                            Confidence
                          </div>
                          <div className="font-mono text-zinc-200">
                            {(t.confidence * 100).toFixed(0)}%
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-zinc-500">Fee</div>
                          <div className="font-mono text-zinc-200">
                            {formatCurrency(t.fee, 4)}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-zinc-500">
                            Realized PnL
                          </div>
                          <div
                            className={`font-mono ${t.realized_pnl > 0 ? "text-green-400" : t.realized_pnl < 0 ? "text-red-400" : "text-zinc-400"}`}
                          >
                            {formatCurrency(t.realized_pnl, 4)}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-zinc-500">
                            Unrealized
                          </div>
                          <div
                            className={`font-mono ${t.unrealized_pnl > 0 ? "text-green-400" : t.unrealized_pnl < 0 ? "text-red-400" : "text-zinc-400"}`}
                          >
                            {formatCurrency(t.unrealized_pnl, 4)}
                          </div>
                        </div>
                      </div>

                      {/* Execution details (live orders only) */}
                      {lo && (
                        <div className="rounded border border-white/5 bg-[#0d1017] p-2">
                          <div className="mb-1 text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
                            Execution
                          </div>
                          <div className="grid grid-cols-3 gap-x-4 gap-y-1 sm:grid-cols-6">
                            <div>
                              <span className="text-zinc-500">Limit: </span>
                              <span className="font-mono text-zinc-300">
                                ${lo.limit_price?.toFixed(4)}
                              </span>
                            </div>
                            <div>
                              <span className="text-zinc-500">Matched: </span>
                              <span className="font-mono text-zinc-300">
                                {lo.size_matched?.toFixed(2) ?? "---"}
                              </span>
                            </div>
                            <div>
                              <span className="text-zinc-500">Source: </span>
                              <span className="font-mono text-zinc-300">
                                {formatFillSource(lo.fill_source)}
                              </span>
                            </div>
                            <div>
                              <span className="text-zinc-500">TTL: </span>
                              <span className="font-mono text-zinc-300">
                                {lo.ttl_used
                                  ? `${lo.ttl_used.toFixed(1)}s`
                                  : "---"}
                              </span>
                            </div>
                            <div>
                              <span className="text-zinc-500">Polls: </span>
                              <span className="font-mono text-zinc-300">
                                {lo.polls ?? 0}
                              </span>
                            </div>
                            <div>
                              <span className="text-zinc-500">OB Ask: </span>
                              <span className="font-mono text-zinc-300">
                                ${lo.decision_ob_ask?.toFixed(4) ?? "---"}
                              </span>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Reasoning */}
                      {t.reasoning && (
                        <div>
                          <div className="mb-1 text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
                            Reasoning
                          </div>
                          <div className="text-[11px] leading-relaxed whitespace-pre-wrap text-zinc-400">
                            {t.reasoning}
                          </div>
                        </div>
                      )}

                      {/* Market view */}
                      {t.market_view && (
                        <div>
                          <div className="mb-1 text-[10px] font-semibold tracking-wider text-zinc-500 uppercase">
                            Market View
                          </div>
                          <div className="text-[11px] leading-relaxed whitespace-pre-wrap text-zinc-400">
                            {t.market_view}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
