import type { CorrectionInput, NewsIntelligenceBundle } from "./types";

async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail?.message ?? body.detail ?? `请求失败 (${response.status})`);
  }
  return response.json();
}

export async function loadNewsIntelligence(): Promise<NewsIntelligenceBundle> {
  const [events, interpretations, quality, corrections, briefings] = await Promise.all([
    read<NewsIntelligenceBundle["events"]>("/api/v1/news/events"),
    read<NewsIntelligenceBundle["interpretations"]>("/api/v1/news/interpretations"),
    read<NewsIntelligenceBundle["quality"]>("/api/v1/news/quality"),
    read<NewsIntelligenceBundle["corrections"]>("/api/v1/news/corrections"),
    read<NewsIntelligenceBundle["briefings"]>("/api/v1/briefings"),
  ]);
  return { events, interpretations, quality, corrections, briefings };
}

export const syncNews = () => read<Record<string, number>>("/api/v1/news/sync", { method: "POST" });
export const createNewsCorrection = (input: CorrectionInput) => read("/api/v1/news/corrections", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
});
