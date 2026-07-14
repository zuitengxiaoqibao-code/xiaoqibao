import type { ResearchCard } from "./types";

export async function loadSnapshot(symbol: string): Promise<ResearchCard> {
  const response = await fetch(`/api/v1/a-shares/${symbol}/snapshot`);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string | { message?: string };
    } | null;
    const detail = typeof body?.detail === "string" ? body.detail : body?.detail?.message;
    throw new Error(detail ?? `行情请求失败 (${response.status})`);
  }
  return response.json() as Promise<ResearchCard>;
}
