"use client";

import { useEffect, useState } from "react";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { FORENSICS_API_URL } from "@/lib/constants";

interface ForensicsCandle {
  slug: string;
  winner: string;
  btc_open: number;
  btc_close: number;
  resolution_pnl: number;
  forensics?: {
    score: number;
    label: string;
    features: Record<string, number>;
  };
}

export default function ForensicsPage() {
  const [candles, setCandles] = useState<ForensicsCandle[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ForensicsCandle | null>(null);

  useEffect(() => {
    async function fetchForensics() {
      try {
        const res = await fetch(`${FORENSICS_API_URL}/forensics/candles`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setCandles(data.candles ?? data ?? []);
        setError(null);
      } catch (e) {
        setError(
          e instanceof Error
            ? e.message
            : "Failed to connect to forensics server",
        );
      } finally {
        setLoading(false);
      }
    }
    fetchForensics();
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-pulse text-sm text-zinc-500">
          Connecting to forensics server...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-4xl space-y-4">
        <h1 className="text-lg font-semibold text-zinc-200">Forensics</h1>
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-4">
          <div className="text-sm text-red-400">
            Could not connect to forensics server at{" "}
            <code className="font-mono">{FORENSICS_API_URL}</code>
          </div>
          <div className="mt-1 text-xs text-red-400/60">
            Start it with:{" "}
            <code className="font-mono">uv run polybot-server</code>
          </div>
          <div className="mt-2 text-xs text-zinc-500">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-200">Forensics</h1>
        <span className="text-xs text-zinc-500">{candles.length} candles</span>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Candle list */}
        <div className="max-h-[70vh] space-y-1 overflow-y-auto pr-1 lg:col-span-1">
          {candles.map((c) => (
            <button
              key={c.slug}
              onClick={() => setSelected(c)}
              className={`w-full rounded-lg p-3 text-left text-xs transition-colors ${
                selected?.slug === c.slug
                  ? "border border-cyan-500/30 bg-white/5"
                  : "border border-white/5 bg-[#131720] hover:bg-white/[0.02]"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="max-w-[200px] truncate font-mono text-zinc-300">
                  {c.slug}
                </span>
                <StatusBadge
                  label={c.winner}
                  variant={c.winner === "up" ? "green" : "red"}
                />
              </div>
              {c.forensics && (
                <div className="mt-1 flex items-center gap-2">
                  <span className="text-zinc-500">Score:</span>
                  <span className="font-mono text-zinc-300">
                    {c.forensics.score.toFixed(2)}
                  </span>
                  <StatusBadge
                    label={c.forensics.label}
                    variant={
                      c.forensics.label === "GOOD"
                        ? "green"
                        : c.forensics.label === "BAD"
                          ? "red"
                          : "amber"
                    }
                  />
                </div>
              )}
            </button>
          ))}
        </div>

        {/* Detail panel */}
        <div className="lg:col-span-2">
          {selected ? (
            <div className="space-y-4 rounded-lg border border-white/5 bg-[#131720] p-6">
              <div className="flex items-center justify-between">
                <h2 className="font-mono text-sm text-cyan-400">
                  {selected.slug}
                </h2>
                <StatusBadge
                  label={selected.winner}
                  variant={selected.winner === "up" ? "green" : "red"}
                />
              </div>

              <div className="grid grid-cols-3 gap-4 text-xs">
                <div>
                  <span className="text-zinc-500">BTC Open</span>
                  <div className="font-mono text-zinc-200">
                    ${selected.btc_open?.toFixed(2) ?? "---"}
                  </div>
                </div>
                <div>
                  <span className="text-zinc-500">BTC Close</span>
                  <div className="font-mono text-zinc-200">
                    ${selected.btc_close?.toFixed(2) ?? "---"}
                  </div>
                </div>
                <div>
                  <span className="text-zinc-500">PnL</span>
                  <div
                    className={`font-mono ${
                      (selected.resolution_pnl ?? 0) >= 0
                        ? "text-green-400"
                        : "text-red-400"
                    }`}
                  >
                    ${selected.resolution_pnl?.toFixed(4) ?? "---"}
                  </div>
                </div>
              </div>

              {selected.forensics && (
                <div>
                  <h3 className="mb-3 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
                    Feature Analysis
                  </h3>
                  <div className="space-y-2">
                    {Object.entries(selected.forensics.features).map(
                      ([feat, val]) => (
                        <div
                          key={feat}
                          className="flex items-center justify-between text-xs"
                        >
                          <span className="text-zinc-400">{feat}</span>
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-24 overflow-hidden rounded-full bg-zinc-800">
                              <div
                                className="h-full rounded-full bg-cyan-500"
                                style={{
                                  width: `${Math.min(100, Math.abs(val) * 100)}%`,
                                }}
                              />
                            </div>
                            <span className="w-12 text-right font-mono text-zinc-300">
                              {val.toFixed(3)}
                            </span>
                          </div>
                        </div>
                      ),
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center rounded-lg border border-white/5 bg-[#131720] p-12">
              <span className="text-sm text-zinc-600">
                Select a candle to view forensics detail
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
