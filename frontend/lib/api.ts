import type {
  CasesPage, FraudCase, Stats, AuthUser, AuditEntry, Dashboard, Customer, RulesConfig, AnalyticsKpis,
  BacktestResult, RuleChangeEntry, Scan314aResult, RiskAssessment, RiskAssessmentList,
} from "@/types";

const BASE = "/api";

const TOKEN_KEY = "fms.token";
const USER_KEY = "fms.user";

export const auth = {
  token: (): string | null => (typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null),
  user: (): AuthUser | null => {
    if (typeof window === "undefined") return null;
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as AuthUser;
    } catch {
      // Corrupt stored session — clear it so the app doesn't get wedged.
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      return null;
    }
  },
  set: (token: string, user: AuthUser) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers = { ...extra };
  const token = auth.token();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: authHeaders(options.headers as Record<string, string>),
  });
  if (res.status === 401) {
    // Session expired or missing — drop creds and bounce to login.
    auth.clear();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new Error("Not authenticated");
  }
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json();
}

function reportUrl(kind: "ctr" | "sar", params: Record<string, string | undefined> = {}, format = "csv"): string {
  const qs = new URLSearchParams({ format });
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  return `${BASE}/reports/${kind}?${qs}`;
}

export const api = {
  getCases: (params: Record<string, string | number | undefined> = {}): Promise<CasesPage> => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    }
    return req<CasesPage>(`/cases?${qs}`);
  },

  getCase: (id: string): Promise<FraudCase> =>
    req<FraudCase>(`/cases/${id}`),

  addAction: (id: string, action: string, note?: string, actor?: string): Promise<FraudCase> =>
    req<FraudCase>(`/cases/${id}/actions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, note, actor }),
    }),

  getStats: (): Promise<Stats> => req<Stats>("/stats"),

  getDashboard: (): Promise<Dashboard> => req<Dashboard>("/stats/dashboard"),

  getCustomers: (limit = 100): Promise<{ count: number; items: Customer[] }> =>
    req(`/customers?limit=${limit}`),

  getRules: (): Promise<RulesConfig> => req<RulesConfig>("/rules"),

  getAnalyticsKpis: (): Promise<AnalyticsKpis> => req<AnalyticsKpis>("/analytics"),

  getSettings: (): Promise<Record<string, unknown>> => req("/settings"),

  updateSettings: (payload: Record<string, unknown>): Promise<MaybePending<{ saved: boolean; restart_required: boolean }>> =>
    req("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  testConnection: (): Promise<{ connected: boolean; message: string; db_type?: string }> =>
    req("/settings/test-connection", { method: "POST" }),

  testDirectory: (): Promise<{ connected: boolean; message: string; enabled: boolean }> =>
    req("/settings/test-directory", { method: "POST" }),

  getSystemInfo: (): Promise<Record<string, any>> => req("/settings/system-info"),  // eslint-disable-line @typescript-eslint/no-explicit-any

  getHealth: (): Promise<{ status: string; bank_db_connected: boolean; poller_running: boolean; last_poll_at: string | null; last_error: string | null }> =>
    req("/health"),

  // Regulatory filing exports (CSV + draft batch XML download links).
  ctrReportUrl: (params?: Record<string, string | undefined>) => reportUrl("ctr", params),
  sarReportUrl: (params?: Record<string, string | undefined>) => reportUrl("sar", params),
  ctrXmlDraftUrl: (params?: Record<string, string | undefined>) => reportUrl("ctr", params, "xml"),
  sarXmlDraftUrl: (params?: Record<string, string | undefined>) => reportUrl("sar", params, "xml"),
  getCtrReport: (): Promise<{ count: number; items: Record<string, unknown>[] }> => req("/reports/ctr"),
  getSarReport: (): Promise<{ count: number; items: Record<string, unknown>[] }> => req("/reports/sar"),

  // Rule tuning: backtest + change history
  backtestRules: (proposed: Record<string, unknown>, days = 90): Promise<BacktestResult> =>
    req("/rules/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposed, days }),
    }),
  getRuleChanges: (limit = 50): Promise<{ count: number; items: RuleChangeEntry[] }> =>
    req(`/rules/changes?limit=${limit}`),

  // FinCEN 314(a) batch scan (admin)
  scan314a: (payload: { csv_text?: string; names?: string[] }): Promise<Scan314aResult> =>
    req("/screening/314a", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  // Institutional risk assessment
  getRiskAssessments: (): Promise<RiskAssessmentList> => req("/risk-assessment"),
  getRiskAssessment: (id: string): Promise<RiskAssessment> => req(`/risk-assessment/${id}`),
  createRiskDraft: (): Promise<RiskAssessment> => req("/risk-assessment", { method: "POST" }),
  updateRiskAssessment: (id: string, payload: Record<string, unknown>): Promise<RiskAssessment> =>
    req(`/risk-assessment/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  refreshRiskSnapshot: (id: string): Promise<RiskAssessment> =>
    req(`/risk-assessment/${id}/refresh-snapshot`, { method: "POST" }),
  finalizeRiskAssessment: (id: string): Promise<RiskAssessment> =>
    req(`/risk-assessment/${id}/finalize`, { method: "POST" }),

  // Auth
  signup: (email: string, password: string, full_name?: string): Promise<{ token: string; user: AuthUser }> =>
    req("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, full_name }),
    }),
  login: (email: string, password: string): Promise<{ token: string; user: AuthUser }> =>
    req("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }),
  forgotPassword: (email: string): Promise<{ message: string; email_configured: boolean }> =>
    req("/auth/forgot-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }),

  // Activity log
  getAudit: (limit = 50, username?: string): Promise<AuditEntry[]> =>
    req(`/audit?limit=${limit}${username ? `&username=${encodeURIComponent(username)}` : ""}`),
  getAuditUsers: (): Promise<{ username: string; actions: number; failed_logins: number; case_actions: number; last_activity: string | null }[]> =>
    req("/audit/users"),
  getSecurityEvents: (limit = 100): Promise<SecurityEventsResponse> =>
    req(`/audit/security?limit=${limit}`),

  // Account + user management
  changePassword: (current_password: string, new_password: string): Promise<{ changed: boolean }> =>
    req("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password, new_password }),
    }),
  listUsers: (): Promise<AuthUser[]> => req("/auth/users"),
  createUser: (email: string, full_name: string, role: string): Promise<MaybePending<{ username: string; email: string | null; role: string; emailed: boolean; temp_password: string | null }>> =>
    req("/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, full_name, role }),
    }),
  resetUserPassword: (userId: string): Promise<MaybePending<{ username: string; email: string | null; emailed: boolean; temp_password: string | null }>> =>
    req(`/auth/users/${userId}/reset-password`, { method: "POST" }),
  toggleUserActive: (userId: string): Promise<MaybePending<{ username: string; is_active: boolean }>> =>
    req(`/auth/users/${userId}/toggle-active`, { method: "POST" }),
  setUserRole: (userId: string, role: string): Promise<MaybePending<{ username: string; role: string }>> =>
    req(`/auth/users/${userId}/role`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    }),

  // Dual control (maker-checker) approvals
  listApprovals: (): Promise<ApprovalsPage> => req("/approvals"),
  approveChange: (id: string): Promise<{ approved: boolean; summary: string; result: Record<string, unknown> }> =>
    req(`/approvals/${id}/approve`, { method: "POST" }),
  rejectChange: (id: string, note?: string): Promise<{ rejected: boolean }> =>
    req(`/approvals/${id}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: note ?? null }),
    }),
  cancelChange: (id: string): Promise<{ cancelled: boolean }> =>
    req(`/approvals/${id}/cancel`, { method: "POST" }),
};

// Dual control: sensitive admin actions may return a queued approval instead of
// the direct result when a second admin's sign-off is required.
export type MaybePending<T> = (T & { pending?: false }) | {
  pending: true;
  approval_id: string;
  summary: string;
  message: string;
};

export interface Approval {
  id: string;
  action: string;
  target: string | null;
  summary: string;
  requested_by: string;
  requested_at: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

export interface ApprovalsPage {
  dual_control_active: boolean;
  active_admins: number;
  me: string;
  pending: Approval[];
  recent: Approval[];
}

export type SecuritySeverity = "critical" | "warning" | "notice" | "info";

export interface SecurityEvent {
  id: number;
  username: string;
  action: string;
  severity: SecuritySeverity;
  target: string | null;
  detail: string | null;
  ip: string | null;
  created_at: string;
}

export interface SecurityEventsResponse {
  counts: { failed_logins: number; rejected_keys: number; sanctions_hits: number };
  events: SecurityEvent[];
}
