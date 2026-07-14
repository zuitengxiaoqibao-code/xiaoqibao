import type { BondCandidates, BondDashboard, BondDiagnosis } from "./types";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `请求失败 (${response.status})`);
  }
  return response.json();
}

export const loadBondDashboard = () => request<BondDashboard>("/api/v1/convertible-bonds/dashboard");
export const loadBondDiagnosis = (code: string) => request<BondDiagnosis>(`/api/v1/convertible-bonds/${code}/diagnosis`);
export const loadBondCandidates = () => request<BondCandidates>("/api/v1/convertible-bonds/candidates");
