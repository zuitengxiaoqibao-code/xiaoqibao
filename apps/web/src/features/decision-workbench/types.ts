export type DecisionPhase = "premarket" | "intraday" | "postclose";
export type Evidence = { evidence_id: string; source: string; snapshot_id: string; summary: string; observed_at: string };
export type Advice = {
  advice_id: string; snapshot_id: string; symbol: string; horizon: "intraday" | "swing";
  action: "observe" | "wait" | "avoid" | "invalidated" | "simulated_plan";
  conclusion: string; confidence: string; supporting_evidence: Evidence[]; contrary_evidence: Evidence[];
  risks: string[]; invalidation_conditions: string[]; plain_language_explanation?: string | null;
  strategy_version: string; created_at: string; simulation_plan_id?: string | null; risk_decision_id?: string | null;
};
export type SimulationPlan = {
  plan_id: string; advice_id: string; risk_decision_id: string; compliance_snapshot_id: string;
  watch_price_low: string; watch_price_high: string; stop_loss: string; take_profit: string[];
  tranches: string[]; max_position: string; invalidation_conditions: string[];
  strategy_version: string; risk_version: string; compliance_version: string;
};
export type PlanReadiness = {
  ready: boolean; reasons: string[]; quote_state: "ready" | "blocked";
  compliance_state: "ready" | "blocked"; evidence_state: "ready" | "blocked";
  risk_state: "approve" | "reject";
};
export type PhaseSlot = {
  phase_status: "empty" | "ready" | "partial" | "blocked"; quality: "empty" | "ready" | "partial" | "blocked";
  aggregate_version: string | null; strategy_versions?: string[]; ai_status: "ready" | "unavailable" | "not_requested";
  generated_at?: string; advice: Advice[]; evidence: Evidence[]; plans: SimulationPlan[];
  plan_readiness: Record<string, PlanReadiness>;
  delta_version?: string; delta_advice?: Advice[]; delta_plans?: SimulationPlan[];
  change_stream?: Array<{ snapshot_id: string; sequence: number; generated_at: string; delta_advice: Advice[]; delta_plans: SimulationPlan[] }>;
};
export type DecisionResponse = {
  server_time: string; trading_date: string; current_phase: DecisionPhase; market_session: "open" | "closed";
  phases: Record<DecisionPhase, PhaseSlot>;
  polling: { status?: "uninitialized" | "normal" | "degraded"; focus_interval_seconds: number | null; universe_interval_seconds: number | null; stale_after_seconds: number; next_check_seconds: number | null; consecutive_focus_failures?: number; consecutive_universe_failures?: number; last_focus_success_at?: string | null; last_universe_success_at?: string | null };
};
