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

export const MODEL_COLORS: Record<string, string> = {
  LogisticRegression: "#3498db",
  RandomForest: "#e74c3c",
  XGBoost: "#e67e22",
  DNN: "#9b59b6",
};

export const MODEL_SHORT: Record<string, string> = {
  LogisticRegression: "LR",
  RandomForest: "RF",
  XGBoost: "XGB",
  DNN: "DNN",
};

export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8766";

export const RECONNECT_INTERVALS = {
  initial: 1000,
  max: 30000,
  multiplier: 2,
} as const;
