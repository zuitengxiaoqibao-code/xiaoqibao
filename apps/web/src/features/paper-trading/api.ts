import type { OrderResult, PaperAccount, Portfolio } from "./types";

const accountId = "default";

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `${fallback} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export async function loadPaperPortfolio(): Promise<Portfolio> {
  const [account, positions, ledger, orders] = await Promise.all([
    fetch(`/api/v1/paper/accounts/${accountId}`),
    fetch(`/api/v1/paper/accounts/${accountId}/positions`),
    fetch(`/api/v1/paper/accounts/${accountId}/ledger`),
    fetch(`/api/v1/paper/accounts/${accountId}/orders`),
  ]);
  return {
    account: await readJson(account, "账户读取失败"),
    positions: await readJson(positions, "持仓读取失败"),
    ledger: await readJson(ledger, "流水读取失败"),
    orders: await readJson(orders, "委托读取失败"),
  };
}

export async function createPaperAccount(): Promise<PaperAccount> {
  const response = await fetch("/api/v1/paper/accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: accountId, initial_cash: "100000" }),
  });
  return readJson(response, "开户失败");
}

export async function submitPaperOrder(
  symbol: string,
  side: "buy" | "sell",
  shares: number,
): Promise<OrderResult> {
  const response = await fetch(`/api/v1/paper/accounts/${accountId}/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_order_id: `web-${Date.now()}`,
      symbol,
      side,
      shares,
    }),
  });
  return readJson(response, "行情源暂不可用");
}
