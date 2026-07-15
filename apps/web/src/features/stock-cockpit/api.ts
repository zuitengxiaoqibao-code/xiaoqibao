import type { InstrumentSearchResponse, StockCockpitSnapshot } from "./types";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail?.message ?? body.detail ?? `A 股请求失败 (${response.status})`);
  }
  return response.json();
}

export function searchAShareInstruments(query: string): Promise<InstrumentSearchResponse> {
  return request(`/api/v1/a-shares/search?q=${encodeURIComponent(query)}&limit=10`);
}

export function loadStockCockpit(symbol: string, asOf?: string, signal?: AbortSignal): Promise<StockCockpitSnapshot> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return fetch(`/api/v1/a-shares/${symbol}/cockpit${query}`, { signal }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail?.message ?? body.detail ?? `A 股请求失败 (${response.status})`);
    }
    return response.json();
  });
}
