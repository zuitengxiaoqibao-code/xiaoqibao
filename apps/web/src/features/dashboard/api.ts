import type { ResearchCard } from "./types";

export async function loadSnapshot(symbol: string): Promise<ResearchCard> {
  const response = await fetch(`/api/v1/a-shares/${symbol}/snapshot`);
  if (!response.ok) throw new Error(`行情请求失败 (${response.status})`);
  return response.json() as Promise<ResearchCard>;
}

