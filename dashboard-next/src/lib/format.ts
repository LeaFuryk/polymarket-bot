/** Formatting utilities for currency, percent, time display. */

export function formatCurrency(value: number, decimals = 2): string {
  const sign = value < 0 ? "-" : value > 0 ? "+" : "";
  return `${sign}$${Math.abs(value).toFixed(decimals)}`;
}

export function formatUsd(value: number, decimals = 2): string {
  return `$${value.toFixed(decimals)}`;
}

export function formatBtcPrice(value: number): string {
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPercent(value: number, decimals = 1): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

export function formatPnlPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}%`;
}

export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatTime(isoString: string): string {
  const d = new Date(isoString);
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelativeTime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

export function pnlColor(value: number): string {
  if (value > 0.001) return "text-green-400";
  if (value < -0.001) return "text-red-400";
  return "text-zinc-400";
}

export function pnlBgColor(value: number): string {
  if (value > 0.001) return "bg-green-500/10";
  if (value < -0.001) return "bg-red-500/10";
  return "bg-zinc-500/10";
}
