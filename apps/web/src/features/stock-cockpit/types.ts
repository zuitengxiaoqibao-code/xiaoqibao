import type { CandidateBoard } from "../a-shares/types";
import type { Advice, DecisionPhase, PhaseExecution } from "../decision-workbench/types";

export type AShareInstrument = {
  symbol: string;
  name: string;
  exchange: "sh" | "sz" | "bj";
  observed_at: string;
  quote_quality: "ready" | "stale" | "unavailable";
};

export type InstrumentSearchResponse = {
  query: string;
  items: AShareInstrument[];
  server_time: string;
  source_status: "ready" | "unavailable";
};

export type CockpitSection = {
  status: "ready" | "partial" | "stale" | "unavailable" | "blocked";
  source: string;
  observed_at: string | null;
  snapshot_id: string | null;
  reason: string | null;
  payload: Record<string, unknown>;
};

export type AssessmentEvidence = {
  evidence_id: string;
  source: string;
  snapshot_id: string;
  summary: string;
  observed_at: string;
};

export type StockAssessment = {
  assessment_id: string;
  symbol: string;
  action: "observe" | "wait" | "avoid";
  conclusion: string;
  confidence: string;
  supporting_evidence: AssessmentEvidence[];
  contrary_evidence: AssessmentEvidence[];
  risks: string[];
  invalidation_conditions: string[];
  generated_at: string;
};

export type AssessmentAIStatus = "ready" | "unconfigured" | "timeout" | "http_error" | "invalid";

export type AssessmentAIExplanation = {
  plain_language: string;
  news_impact: string;
  hotspot_attribution: string;
  uncertainty: string;
  contrary_view: string;
  evidence_ids: string[];
};

export type PreparationSource = {
  name: "quote" | "history" | "finance" | "news" | "classification" | "fund_flow";
  status: "ready" | "partial";
  observed_at: string | null;
  reason: string | null;
};

export type StockPreparation = {
  symbol: string;
  status: "ready" | "partial";
  sources: PreparationSource[];
  refreshed: boolean;
  started_at: string;
  completed_at: string;
};

export type StockCockpitSnapshot = {
  symbol: string;
  as_of: string;
  cutoff: string;
  overall_quality: "ready" | "partial" | "blocked";
  instrument: AShareInstrument;
  preparation?: StockPreparation;
  candidate_membership: Array<"short_term" | "swing">;
  assessment: StockAssessment;
  ai_status: AssessmentAIStatus;
  ai_explanation: AssessmentAIExplanation | null;
  current_advice: Advice[];
  sections: Record<string, CockpitSection>;
  phases: Record<DecisionPhase, StockPhaseHistory>;
};

export type DecisionVersion = {
  snapshot_id: string;
  sequence: number;
  generated_at: string;
  status: "ready" | "partial" | "blocked";
};

export type StockPhaseHistory = {
  advice: Advice[];
  change_stream: DecisionVersion[];
  execution?: PhaseExecution | null;
};

export type CandidateLoader = () => Promise<CandidateBoard>;
