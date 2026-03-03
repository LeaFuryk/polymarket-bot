/** TypeScript types matching the Python WS protocol. */

// --- WS Message Types ---

export type WSMessageType =
  | "snapshot"
  | "trade"
  | "resolution"
  | "market"
  | "position"
  | "status";

export interface WSMessage<T = unknown> {
  type: WSMessageType;
  data: T;
}

// --- Snapshot (full state) ---

export interface SessionStats {
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  total_fees: number;
  total_ai_cost: number;
  cash: number;
  portfolio_value: number;
  initial_cash: number;
  market_trading_pnl: number;
  cycles_run: number;
  prefilter_skip_rate: number;
  prefilter_skipped: number;
  prefilter_checked: number;
  calibration_records: number;
}

export interface AllTimeStats {
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  total_resolutions: number;
  total_trades: number;
}

export interface CurrentMarket {
  slug: string;
  title: string;
  polymarket_url: string;
  time_remaining: number;
  up_mid: number | null;
  down_mid: number | null;
}

export interface BtcInfo {
  price_usd: number;
  change_24h_pct: number;
  last_candle_direction: string;
  chainlink_price: number | null;
  price_divergence: number | null;
  price_source: string;
  candle_sources: {
    chainlink: number;
    binance: number;
    total: number;
  };
}

export interface Positions {
  up_shares: number;
  up_avg_entry: number;
  down_shares: number;
  down_avg_entry: number;
}

export interface RiskState {
  daily_pnl: number;
  daily_trades: number;
  daily_fees: number;
  max_drawdown: number;
  is_halted: boolean;
}

export interface MonitorState {
  prefilter_snapshots: number;
  ai_cooldown_remaining: number;
  last_trigger_reason: string;
  status: Record<string, unknown>;
}

export interface AdaptiveEntry {
  enabled: boolean;
  btc_threshold: number;
  max_entry_price: number;
  reversal_rate: number;
  regime: string;
  signal_type: string;
  has_enough_history: boolean;
  window_size: number;
  history_count: number;
  market_trend?: number;
  market_trend_label?: string;
}

export interface OutageInfo {
  is_down: boolean;
  since: number | null;
  duration: number;
  failures: number;
  recovered: boolean;
  last_outage_duration: number;
}

export interface LiveTradingInfo {
  mode: string;
  dry_run: boolean;
  wallet_balance: number;
  kill_switch_active: boolean;
  max_order_size_usd: number;
  max_session_loss_usd: number;
  shadow_paper_pnl: number;
  execution_cost: number;
}

export interface TradeEntry {
  timestamp: string;
  cycle: number;
  action: string;
  token_side: string;
  size: number;
  fill_price: number | null;
  confidence: number;
  reasoning: string;
  market_view: string;
  candle_slug: string;
  polymarket_url: string;
  time_remaining_at_trade: number;
  risk_blocked: boolean;
  risk_block_reason: string;
  cash: number;
  portfolio_value: number;
  fee: number;
  realized_pnl: number;
  unrealized_pnl: number;
  ai_cost: number;
  screen_passed?: boolean;
  screen_input?: string;
  live_order?: Record<string, unknown>;
}

export interface ResolutionEntry {
  timestamp: string;
  slug: string;
  winner: string;
  btc_open: number;
  btc_close: number;
  btc_move: number;
  pnl: number;
}

export interface IterationTradeAnalysis {
  total_buys: number;
  total_sells: number;
  total_holds: number;
  avg_fill_price: number;
  cheap_entries: number;
  mid_entries: number;
  expensive_entries: number;
  avg_confidence: number;
  hold_rate: number;
}

export interface IterationResolutionAnalysis {
  total: number;
  avg_btc_move: number;
  max_btc_move: number;
  avg_win_pnl: number;
  avg_loss_pnl: number;
  biggest_win: number;
  biggest_loss: number;
  cumulative_pnl: number[];
}

export interface IterationResolutionDetail {
  slug: string;
  pnl: number;
  btc_move: number;
  resolution: string;
}

export interface IterationCalibration {
  total_records: number;
  shadow_accuracy: number | null;
  shadow_total: number;
  bins: Array<{
    range: string;
    wins: number;
    losses: number;
    win_rate: number;
    reliable: boolean;
  }>;
}

export interface IterationExitAnalysis {
  total_exits: number;
  good_exit_rate: number;
  good_exits: number;
  total_saved: number;
  total_missed: number;
}

export interface IterationLiveTrading {
  mode: string;
  dry_run: boolean;
  wallet_balance: number;
  shadow_paper_pnl: number;
  execution_cost: number;
}

export interface IterationSummary {
  // Core fields from summary.json
  label: string;
  version: string;
  trading_mode?: "paper" | "live" | "dry_run";
  archived_at?: string;
  date_range?: { start: string; end: string };
  total_candles: number;
  total_trades: number;
  total_cycles?: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  total_fees?: number;
  ai_cost?: number;
  net_result?: number;
  final_cash?: number;
  final_portfolio_value?: number;
  reflections_count?: number;
  enabled_indicators?: string[];

  // Enriched analysis (added by _enrich_iteration_summary)
  trade_analysis?: IterationTradeAnalysis;
  resolution_analysis?: IterationResolutionAnalysis;
  resolutions_detail?: IterationResolutionDetail[];
  calibration?: IterationCalibration;
  exit_analysis?: IterationExitAnalysis;
  ml_model?: { training_samples: number; model_trained: boolean };
  observations?: Array<{ category: string; text: string; timestamp: string }>;
  session_history?: string;
  live_trading?: IterationLiveTrading;
}

export interface EnsembleStats {
  screen_calls: number;
  screen_passes: number;
  screen_pass_rate: number;
  sonnet_trades: number;
  ml_sonnet_agree: number;
  ml_sonnet_total: number;
  ml_sonnet_agree_rate: number;
}

export interface SnapshotData {
  bot_version: string;
  updated_at: string;
  session: SessionStats;
  all_time: AllTimeStats;
  current_market: CurrentMarket;
  btc: BtcInfo;
  positions: Positions;
  position_pnl: Record<string, number>;
  dynamic_sl: Record<string, number>;
  dynamic_tp: Record<string, number>;
  trades: TradeEntry[];
  resolutions: ResolutionEntry[];
  risk: RiskState;
  monitor: MonitorState;
  adaptive_entry: AdaptiveEntry;
  ensemble: EnsembleStats;
  outage: OutageInfo;
  iterations: IterationSummary[];
  live_trading?: LiveTradingInfo;
  ws_clients?: number;
}

// --- Lightweight update messages ---

export interface MarketUpdate {
  timestamp: number;
  time_remaining?: number;
  up_mid?: number | null;
  down_mid?: number | null;
  slug?: string;
  btc_price?: number;
  chainlink_price?: number | null;
  price_source?: string;
}

export interface PositionUpdate {
  timestamp: number;
  up_shares: number;
  up_avg_entry: number;
  down_shares: number;
  down_avg_entry: number;
  cash: number;
  position_pnl: Record<string, number>;
  dynamic_sl: Record<string, number>;
  dynamic_tp: Record<string, number>;
}

export interface StatusUpdate {
  timestamp: number;
  monitor: MonitorState;
  risk: RiskState;
  api_latencies: Record<string, number>;
  ws_clients: number;
  sqlite_queue_depth: number;
  prefilter: {
    skip_rate: number;
    skipped: number;
    checked: number;
  };
  ensemble: {
    screen_calls: number;
    screen_passes: number;
  };
}

// --- Event messages ---

export interface TradeEvent {
  timestamp: string;
  action: string;
  token_side: string;
  size: number;
  fill_price: number | null;
  confidence: number;
  reasoning: string;
  candle_slug: string;
  risk_blocked: boolean;
  cash: number;
  portfolio_value: number;
  fee: number;
  ai_cost: number;
  live_order?: Record<string, unknown>;
}

export interface ResolutionEvent {
  slug: string;
  winner: string;
  btc_open: number;
  btc_close: number;
  btc_move: number;
  pnl: number;
}
