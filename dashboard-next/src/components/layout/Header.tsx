"use client";

import type { WSState } from "@/hooks/useWebSocket";

const STATE_COLORS: Record<WSState, string> = {
  connected: "#22c55e",
  connecting: "#f59e0b",
  reconnecting: "#f59e0b",
  disconnected: "#ef4444",
};

export function Header({ wsState }: { wsState: WSState }) {
  return (
    <header className="flex items-center justify-between border-b border-white/5 px-6 py-4">
      <div className="flex items-center gap-4">
        <h1 className="font-mono text-xl font-bold text-white">
          Polymarket Bot
        </h1>
        <span className="text-sm text-white/40">Multi-Model Dashboard</span>
      </div>
      <div className="flex items-center gap-2">
        <div
          className="h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: STATE_COLORS[wsState] }}
        />
        <span className="font-mono text-sm text-white/60">{wsState}</span>
      </div>
    </header>
  );
}
