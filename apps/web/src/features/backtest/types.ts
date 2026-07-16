export type BacktestResult = {
  symbol: string;
  strategy: string;
  initial_cash: string;
  ending_equity: string;
  total_return: string;
  max_drawdown: string;
  total_cost: string;
  metrics: { annualized_volatility: string; win_rate: string; profit_loss_ratio: string | null; turnover_rate: string; closed_trade_count: number };
  segments: Array<{ name: "train" | "validation" | "out_of_sample"; start_date: string; end_date: string; bar_count: number; starting_equity: string; ending_equity: string; total_return: string; max_drawdown: string }>;
  market_regimes: Array<{ name: "bull" | "bear" | "sideways"; bar_count: number; total_return: string }>;
  trades: unknown[];
  equity_curve: unknown[];
  warnings: string[];
};
