SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS paper_accounts (
    account_id TEXT PRIMARY KEY,
    initial_cash TEXT NOT NULL,
    cash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_orders (
    order_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    shares INTEGER NOT NULL,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, client_order_id)
);

CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES paper_orders(order_id),
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
    symbol TEXT NOT NULL,
    shares INTEGER NOT NULL,
    average_cost TEXT NOT NULL,
    market_value TEXT NOT NULL,
    PRIMARY KEY(account_id, symbol)
);

CREATE TABLE IF NOT EXISTS paper_ledger (
    entry_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES paper_accounts(account_id),
    amount TEXT NOT NULL,
    balance_after TEXT NOT NULL,
    reason TEXT NOT NULL,
    related_order_id TEXT,
    related_fill_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_journal (
    line_id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL REFERENCES paper_ledger(entry_id),
    account_code TEXT NOT NULL,
    debit TEXT NOT NULL,
    credit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_settings (
    account_id TEXT PRIMARY KEY REFERENCES paper_accounts(account_id),
    single_position_cap TEXT NOT NULL,
    total_exposure_cap TEXT NOT NULL
);
"""
