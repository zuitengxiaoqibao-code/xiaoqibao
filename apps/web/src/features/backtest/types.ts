export type BacktestResult = {
  symbol: string;
  strategy: string;
  initial_cash: string;
  ending_equity: string;
  total_return: string;
  max_drawdown: string;
  total_cost: string;
  trades: unknown[];
  equity_curve: unknown[];
  warnings: string[];
};

