export interface CaseAction {
  id: number;
  case_id: string;
  action: string;
  actor: string;
  note: string | null;
  created_at: string;
}

export interface FraudCase {
  id: string;
  source_table: string;
  source_txn_id: string;
  account_id: string;
  amount: number;
  direction: "INWARD" | "OUTWARD";
  timestamp: string;
  counterparty_account: string | null;
  counterparty_name: string | null;
  channel: string | null;
  currency: string;
  reference: string | null;
  risk_score: number | null;
  ctr_required: boolean;
  ctr_reason: string | null;
  sar_recommended: boolean;
  sar_reason: string | null;
  sanctions_hit: boolean;
  sanctions_detail: string | null;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  fraud_type: string | null;
  reasons: string[];
  ai_summary: string | null;
  status: "CLEAN" | "OPEN" | "UNDER_REVIEW" | "CONFIRMED_FRAUD" | "DISMISSED" | "ESCALATED";
  created_at: string;
  updated_at: string;
  actions: CaseAction[];
}

export interface FraudCaseListItem {
  id: string;
  source_table: string;
  account_id: string;
  amount: number;
  direction: "INWARD" | "OUTWARD";
  timestamp: string;
  counterparty_name: string | null;
  channel: string | null;
  currency: string;
  reference: string | null;
  risk_score: number | null;
  ctr_required: boolean;
  sar_recommended: boolean;
  sanctions_hit: boolean;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  fraud_type: string | null;
  status: string;
  created_at: string;
}

export interface CasesPage {
  items: FraudCaseListItem[];
  total: number;
  page: number;
  limit: number;
}

export interface AuthUser {
  id: string;
  username: string;
  email: string | null;
  full_name: string | null;
  role: "admin" | "analyst" | "viewer";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuditEntry {
  id: number;
  username: string;
  action: string;
  target: string | null;
  detail: string | null;
  ip: string | null;
  created_at: string;
}

export interface Dashboard {
  totals: {
    total_cases: number;
    open_cases: number;
    flagged_today: number;
    confirmed_fraud: number;
    sanctions_hits: number;
    ctr_required: number;
    sar_open: number;
    sar_soonest_deadline_days: number | null;
  };
  activity: { date: string; flagged: number; clean: number }[];
  fraud_types: { type: string; count: number }[];
  risk_levels: { level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"; count: number }[];
  amounts_open: { currency: string; total: number }[];
  attention: {
    id: string;
    account_id: string;
    amount: number;
    currency: string;
    direction: string;
    fraud_type: string | null;
    risk_score: number | null;
    sanctions_hit: boolean;
    sar_recommended: boolean;
    created_at: string;
  }[];
}

export interface AnalyticsKpis {
  transactions_processed: number;
  alerts_today: number;
  open_cases: number;
  value_flagged: { currency: string; amount: number }[];
  resolved: { confirmed: number; dismissed: number; total: number };
  false_positive_rate: number | null;
  top_fraud_types: { type: string; count: number }[];
  flagged_total: number;
}

export interface Customer {
  account_id: string;
  transactions: number;
  flagged: number;
  open: number;
  sanctions_hits: number;
  sar_count: number;
  max_risk: number | null;
  total_amount: number;
  currency: string | null;
  last_activity: string | null;
}

export interface RulesConfig {
  regulatory_thresholds: {
    ctr_by_currency: Record<string, number>;
    sar_ratio_of_ctr: number;
    note: string;
  };
  detection_parameters: {
    structuring_band_ratio: number;
    rolling_window_days: number;
    smurfing_window_hours: number;
  };
  scoring_components: { name: string; points: string; detail: string }[];
  risk_levels: { level: string; range: string }[];
  sanctions: { list: string; match_threshold: string; note: string };
  national_priorities: {
    note: string;
    items: { priority: string; coverage: "direct" | "partial" | "screening"; how: string }[];
  };
}

export interface RuleChangeEntry {
  id: number;
  changed_by: string;
  changed_at: string;
  old_values: Record<string, unknown>;
  new_values: Record<string, unknown>;
  rationale: string | null;
  backtest: Record<string, unknown> | null;
}

export interface BacktestSummary {
  flagged: number;
  sar_recommended: number;
  ctr_required: number;
}

export interface BacktestResult {
  replayed: number;
  window_days: number;
  note: string;
  current: BacktestSummary;
  proposed: BacktestSummary;
  changed_count: number;
  changed_examples: {
    external_id: string;
    account_id: string;
    amount: number;
    currency: string;
    timestamp: string;
    current: { flagged: boolean; level: string; sar: boolean; ctr: boolean };
    proposed: { flagged: boolean; level: string; sar: boolean; ctr: boolean };
  }[];
  error?: string;
}

export interface Scan314aMatch {
  subject: string;
  matched_party: string | null;
  score: number;
  seen_as: string[];
  occurrences: number;
  account_ids: string[];
}

export interface Scan314aResult {
  subjects_screened: number;
  parties_checked: number;
  matches: Scan314aMatch[];
  note: string;
  error?: string;
}

export type RiskRating = "" | "LOW" | "MODERATE" | "HIGH";

export interface RiskCategoryRow {
  area: string;
  item: string;
  inherent: RiskRating;
  controls: string;
  residual: RiskRating;
  notes: string;
}

export interface RiskPriorityRow {
  priority: string;
  fms_coverage: string;
  fms_how: string;
  applicable: boolean | null;
  notes: string;
}

export interface RiskAssessmentMeta {
  id: string;
  version: number;
  status: "DRAFT" | "FINAL";
  title: string;
  overall_rating: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  finalized_by: string | null;
  finalized_at: string | null;
}

export interface RiskAssessment extends RiskAssessmentMeta {
  categories: RiskCategoryRow[];
  priorities: RiskPriorityRow[];
  activity_snapshot: Record<string, unknown>;
  summary: string | null;
}

export interface RiskAssessmentList {
  count: number;
  latest: RiskAssessment | null;
  versions: RiskAssessmentMeta[];
}

export interface Stats {
  flagged_today: number;
  high_confidence: number;
  pending_review: number;
  confirmed_fraud: number;
  dismissed_today: number;
}

export interface WsNewCase {
  event: "new_case";
  case: {
    id: string;
    account_id: string;
    amount: number;
    currency: string;
    direction: string;
    confidence: "HIGH" | "MEDIUM" | "LOW";
    fraud_type: string | null;
    created_at: string;
  };
}
