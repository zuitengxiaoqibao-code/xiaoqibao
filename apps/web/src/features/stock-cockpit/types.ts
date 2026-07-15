import type { CandidateBoard } from "../a-shares/types";
import type { Advice, DecisionPhase } from "../decision-workbench/types";

export type AShareInstrument = {
  asset: "a_share";
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

export type StockCockpitSnapshot = {
  symbol: string;
  as_of: string;
  cutoff: string;
  overall_quality: "ready" | "partial" | "blocked";
  instrument: AShareInstrument;
  candidate_membership: Array<"short_term" | "swing">;
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
};

export type CandidateLoader = () => Promise<CandidateBoard>;
