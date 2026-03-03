"use client";

import { ConnectionStatus } from "@/components/shared/ConnectionStatus";
import type { WSState } from "@/hooks/useWebSocket";

interface HeaderProps {
  wsState: WSState;
  botVersion?: string;
}

export function Header({ wsState, botVersion }: HeaderProps) {
  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-white/5 bg-[#0d1017] px-4">
      <div className="flex items-center gap-4">
        <ConnectionStatus state={wsState} />
        {wsState === "disconnected" && (
          <span className="font-mono text-[11px] text-amber-500">
            Offline — using cached data
          </span>
        )}
      </div>
      <div className="flex items-center gap-4 font-mono text-xs text-zinc-500">
        {botVersion && <span>v{botVersion}</span>}
      </div>
    </header>
  );
}
