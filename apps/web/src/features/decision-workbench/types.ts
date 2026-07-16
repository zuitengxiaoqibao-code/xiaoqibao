export type DecisionPhase = "premarket" | "intraday" | "postclose";
export type Evidence = { evidence_id: string; source: string; snapshot_id: string; summary: string; observed_at: string };
export type Advice = {
  advice_id: string; snapshot_id: string; asset: "a_share" | "convertible_bond"; symbol: string; horizon: "intraday" | "swing";
  observation_state: string;
  action: "observe" | "wait" | "avoid" | "invalidated";
  conclusion: string; confidence: string; supporting_evidence: Evidence[]; contrary_evidence: Evidence[];
  risks: string[]; invalidation_conditions: string[]; plain_language_explanation: string | null;
  quantitative_result: Record<string, string | null>; ai_interpretation_id: string | null;
  strategy_version: string; created_at: string; risk_decision_id: string | null;
  previous_advice_id: string | null; changed_fields: string[];
};
export type PhaseSlot = {
  phase_status: "empty" | "ready" | "partial" | "blocked"; quality: "empty" | "ready" | "partial" | "blocked";
  aggregate_version: string | null; strategy_versions?: string[]; ai_status: "ready" | "unavailable" | "not_requested";
  generated_at?: string; advice: Advice[]; evidence: Evidence[];
  delta_version?: string; delta_advice?: Advice[];
  change_stream?: Array<{ snapshot_id: string; sequence: number; generated_at: string; delta_advice: Advice[] }>;
};
export type DecisionResponse = {
  server_time: string; trading_date: string; current_phase: DecisionPhase; market_session: "open" | "closed";
  phases: Record<DecisionPhase, PhaseSlot>;
  polling: { status?: "uninitialized" | "normal" | "degraded"; focus_interval_seconds: number | null; universe_interval_seconds: number | null; stale_after_seconds: number; next_check_seconds: number | null; consecutive_focus_failures?: number; consecutive_universe_failures?: number; last_focus_success_at?: string | null; last_universe_success_at?: string | null };
};
