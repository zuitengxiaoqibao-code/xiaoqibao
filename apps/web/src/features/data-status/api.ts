import type { SyncReport } from "./types";

export async function syncHistory(symbol: string, limit = 250): Promise<SyncReport> {
  const response = await fetch(`/api/v1/a-shares/${symbol}/history/sync?limit=${limit}`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`历史数据同步失败 (${response.status})`);
  return response.json() as Promise<SyncReport>;
}

