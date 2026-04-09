/** TypeScript types for the multi-model trading dashboard. */

// --- Model identification ---

export type ModelName = "LogisticRegression" | "RandomForest" | "XGBoost";

// --- Collector events (forwarded by polybot) ---

export interface Snapshot {
  type: "snapshot";
  candle_id: string;
  timestamp: number;
  elapsed_pct: number;
  btc_price: number;
  btc_bid: number;
  btc_ask: number;
  up_bids: [number, number][];
  up_asks: [number, number][];
  down_bids: [number, number][];
  down_asks: [number, number][];
  market_volume: number;
}

export interface CandleClose {
  type: "candle_close";
  candle_id: string;
  start_time: number;
  end_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  outcome: "UP" | "DOWN";
  final_ret: number;
}

export interface CandleCorrection {
  type: "candle_correction";
  candle_id: string;
  start_time: number;
  end_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  outcome: "UP" | "DOWN";
  final_ret: number;
}

// --- Model events (from polybot runners) ---

export interface BetEntry {
  price: number;
  amount_usd: number;
  elapsed_pct: number;
  confidence: number;
  checkpoint: number;
}

export interface ModelEntry {
  type: "model_entry";
  model: ModelName;
  candle_id: string;
  direction: "UP" | "DOWN";
  price: number;
  amount_usd: number;
  confidence: number;
  inference_ms: number;
  checkpoint: number;
  elapsed_pct: number;
  timestamp: number;
}

export interface ModelSettlement {
  type: "model_settlement";
  model: ModelName;
  candle_id: string;
  outcome: "UP" | "DOWN";
  direction: "UP" | "DOWN";
  won: boolean;
  entries: BetEntry[];
  pnl: number;
  cash: number;
  wins: number;
  losses: number;
  timestamp: number;
}

// --- Initial state (sent on WS connect) ---

export interface PortfolioSummary {
  initial_cash: number;
  final_balance: number;
  wins: number;
  losses: number;
  win_rate: number;
  realized_pnl: number;
  net_pnl: number;
  total_fees: number;
  total_return_pct: number;
}

export interface InitialState {
  type: "initial_state";
  candles: CandleClose[];
  snapshots_so_far: Snapshot[];
  portfolios: Record<string, PortfolioSummary>;
  equity_history?: Record<string, number[]>;
  current_entries?: ModelEntry[];
}

// --- Derived types for dashboard state ---

export interface SnapshotPoint {
  elapsed_pct: number;
  timestamp: number;
  up_ask: number | null;
  down_ask: number | null;
  btc_price: number;
}

export interface PastBet {
  candle_id: string;
  outcome: "UP" | "DOWN";
  timestamp: number;
  entries: ModelEntry[];
  settlements: Partial<Record<ModelName, ModelSettlement>>;
  snapshots: SnapshotPoint[];
}

// --- Union type for all incoming messages ---

export type WSMessage =
  | Snapshot
  | CandleClose
  | CandleCorrection
  | ModelEntry
  | ModelSettlement
  | InitialState;
