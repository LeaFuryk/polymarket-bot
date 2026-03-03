"use client";

import type { WSState } from "@/hooks/useWebSocket";

const stateConfig: Record<WSState, { color: string; label: string }> = {
  connected: { color: "bg-green-500", label: "Live" },
  connecting: { color: "bg-amber-500", label: "Connecting" },
  reconnecting: { color: "bg-amber-500", label: "Reconnecting" },
  disconnected: { color: "bg-red-500", label: "Offline" },
};

interface ConnectionStatusProps {
  state: WSState;
}

export function ConnectionStatus({ state }: ConnectionStatusProps) {
  const { color, label } = stateConfig[state];

  return (
    <div className="flex items-center gap-2">
      <span className={`inline-block h-2 w-2 rounded-full ${color} ${
        state === "connected" ? "animate-pulse" : ""
      }`} />
      <span className="text-xs text-zinc-400 font-mono">{label}</span>
    </div>
  );
}
