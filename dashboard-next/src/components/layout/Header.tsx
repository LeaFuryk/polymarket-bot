"use client";

import { ConnectionStatus } from "@/components/shared/ConnectionStatus";
import type { WSState } from "@/hooks/useWebSocket";

interface HeaderProps {
  wsState: WSState;
  botVersion?: string;
}

export function Header({ wsState, botVersion }: HeaderProps) {
  return (
    <header className="h-11 bg-[#0d1017] border-b border-white/5 flex items-center justify-between px-4 shrink-0">
      <div className="flex items-center gap-4">
        <ConnectionStatus state={wsState} />
        {wsState === "disconnected" && (
          <span className="text-[11px] text-amber-500 font-mono">
            Offline — using cached data
          </span>
        )}
      </div>
      <div className="flex items-center gap-4 text-xs text-zinc-500 font-mono">
        {botVersion && <span>v{botVersion}</span>}
      </div>
    </header>
  );
}
