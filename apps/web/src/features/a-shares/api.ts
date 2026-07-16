import type { AShareDiagnosis, CandidateBoard } from "./types";


async function request<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail?.message ?? body.detail ?? `A 股研究请求失败 (${response.status})`);
  }
  return response.json();
}

export function loadAShareCandidates(asOf?: string, limit = 20): Promise<CandidateBoard> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (asOf) query.set("as_of", asOf);
  return request(`/api/v1/a-shares/candidates?${query}`);
}

export function loadAShareDiagnosis(symbol: string, asOf?: string): Promise<AShareDiagnosis> {
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  return request(`/api/v1/a-shares/${symbol}/diagnosis${query}`);
}

