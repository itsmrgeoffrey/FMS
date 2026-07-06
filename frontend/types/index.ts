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
  full_name: string | null;
  role: "admin" | "analyst";
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
