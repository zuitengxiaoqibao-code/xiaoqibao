export type ResearchCard = {
  symbol: string;
  asset: "a_share";
  action: "observe" | "blocked";
  change_percent: string;
  quality: "fresh" | "stale" | "conflicted" | "unavailable";
  evidence: Array<{ label: string; value: string; source: string; observed_at: string }>;
  invalid_reasons: string[];
};

