export type FactorSnapshot = {
  symbol: string; as_of: string; close: string; return_5d: string; return_20d: string;
  distance_ma20: string; volume_ratio_5_20: string; volatility_20d: string;
  drawdown_60d: string; liquidity_amount_20d: string; factor_version: string;
  source: string;
};

export type CandidateEntry = {
  symbol: string; horizon: "short_term" | "swing"; score: string;
  score_breakdown: Record<string, string>; factor_snapshot: FactorSnapshot;
};

export type CandidateBoard = {
  asset: "a_share"; snapshot_id: string | null; input_snapshot_hash: string | null;
  universe_status: "ready" | "empty"; as_of: string; factor_version: string; short_term: CandidateEntry[];
  swing: CandidateEntry[];
  exclusions: Array<{
    symbol: string; reason_code: "insufficient_liquidity" | "invalid_history";
    observed_value: string | null; threshold: string | null; detail: string | null;
  }>;
};

export type DiagnosisSection = {
  status: "ready" | "unavailable"; observed_at: string | null; source: string;
  metrics: Record<string, string | number | null>; evidence_ids: string[];
  explanation: string;
};

export type AShareDiagnosis = {
  asset: "a_share"; snapshot_id: string | null; input_snapshot_hash: string | null;
  symbol: string; as_of: string; action: "observe" | "blocked";
  overall_status: "ready" | "partial"; sections: Record<string, DiagnosisSection>;
  missing_data: string[]; factor_version: string;
};
