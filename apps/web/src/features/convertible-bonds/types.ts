export type BondDiagnosis = {
  status: "ready" | "stale_quote" | "source_conflict";
  bond: { code: string; name: string; price: string | null; suspended: boolean };
  linked_stock: { code: string; name: string; price: string; source: string; observed_at: string };
  quote: { source: string; observed_at: string; quality: string };
  clause_snapshot: { source: string; fetched_at: string; conversion_price: string; maturity: string; remaining_size: string };
  metrics: { conversion_value: string | null; conversion_premium: string | null; pure_bond_premium: string | null; remaining_term: { days: number } };
  risk: { outcome: string; unknowns: string[]; explanations: string[] };
  strong_redemption: { state: string; clause_text: string | null; source: string; observed_at: string; evidence_fields?: Record<string, string> };
};

export type BondDashboard = { status: "ready" | "empty"; bond_count: number; bond_codes: string[] };
export type BondCandidates = { status: "ready" | "empty"; items: Array<{ bond_code: string; conversion_premium: string | null; risk: { outcome: string } }> };
