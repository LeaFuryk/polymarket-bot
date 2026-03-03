/** Theme constants and shared configuration. */

export const THEME = {
  bg: {
    base: "#080a0e",
    raised: "#0d1017",
    surface: "#131720",
  },
  colors: {
    green: "#22c55e",
    red: "#ef4444",
    amber: "#f59e0b",
    cyan: "#06b6d4",
    blue: "#3b82f6",
    purple: "#a78bfa",
  },
} as const;

export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8765";

export const FORENSICS_API_URL =
  process.env.NEXT_PUBLIC_FORENSICS_API_URL || "http://localhost:8888/api";

export const RECONNECT_INTERVALS = {
  initial: 1000,
  max: 30000,
  multiplier: 2,
} as const;
