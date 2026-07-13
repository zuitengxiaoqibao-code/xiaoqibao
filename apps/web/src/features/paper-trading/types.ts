export type PaperAccount = {
  account_id: string;
  initial_cash: string;
  cash: string;
  total_equity: string;
  exposure: string;
};

export type Position = {
  symbol: string;
  shares: number;
  average_cost: string;
  market_value: string;
};

export type LedgerEntry = {
  entry_id: string;
  amount: string;
  balance_after: string;
  reason: string;
  created_at: string;
};

export type PaperOrder = {
  order_id: string;
  symbol: string;
  side: "buy" | "sell";
  shares: number;
  status: "pending" | "filled" | "rejected";
  rejection_reason: string | null;
};

export type Portfolio = {
  account: PaperAccount;
  positions: Position[];
  ledger: LedgerEntry[];
  orders: PaperOrder[];
};

export type OrderResult = {
  order_id: string;
  status: "filled" | "rejected";
  reason: string | null;
};
