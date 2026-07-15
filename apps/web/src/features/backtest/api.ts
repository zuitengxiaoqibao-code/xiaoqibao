import type { BacktestResult } from "./types";

export async function runBacktest(symbol: string, signal?: AbortSignal): Promise<BacktestResult> {
  const response = await fetch(`/api/v1/a-shares/${symbol}/backtests`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fast_window: 5, slow_window: 20 }),
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `回测请求失败 (${response.status})`);
  }
  return response.json() as Promise<BacktestResult>;
}
