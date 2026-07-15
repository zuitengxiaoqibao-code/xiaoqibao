import type { DecisionPhase, DecisionResponse } from "./types";

async function read(url: string, init?: RequestInit): Promise<DecisionResponse> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail?.message ?? body.detail?.code ?? `决策请求失败 (${response.status})`);
  }
  return response.json();
}

export const loadCurrentDecision = () => read("/api/v1/decisions/current");
export const loadDecisionDate = (tradingDate: string) => read(`/api/v1/decisions/${tradingDate}`);
export const runDecisionPhase = (phase: DecisionPhase, tradingDate: string) =>
  read(`/api/v1/decisions/${phase}/${tradingDate}/run`, { method: "POST" });
