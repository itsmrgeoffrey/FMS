import type { CasesPage, FraudCase, Stats, AuthUser, AuditEntry, Dashboard } from "@/types";

const BASE = "/api";
// Optional — only needed if the backend has FMS_API_KEY set (machine auth).
const API_KEY = process.env.NEXT_PUBLIC_FMS_API_KEY;

const TOKEN_KEY = "fms.token";
const USER_KEY = "fms.user";

export const auth = {
  token: (): string | null => (typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null),
  user: (): AuthUser | null => {
    if (typeof window === "undefined") return null;
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
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
  if (API_KEY) headers["X-API-Key"] = API_KEY;
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

function reportUrl(kind: "ctr" | "sar", params: Record<string, string | undefined> = {}): string {
  const qs = new URLSearchParams({ format: "csv" });
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

  getSettings: (): Promise<Record<string, unknown>> => req("/settings"),

  updateSettings: (payload: Record<string, unknown>): Promise<{ saved: boolean; restart_required: boolean }> =>
    req("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  // Regulatory filing exports (CSV download links).
  ctrReportUrl: (params?: Record<string, string | undefined>) => reportUrl("ctr", params),
  sarReportUrl: (params?: Record<string, string | undefined>) => reportUrl("sar", params),

  // Auth
  signup: (username: string, password: string, full_name?: string): Promise<{ token: string; user: AuthUser }> =>
    req("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, full_name }),
    }),
  login: (username: string, password: string): Promise<{ token: string; user: AuthUser }> =>
    req("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),

  // Activity log
  getAudit: (limit = 50): Promise<AuditEntry[]> => req(`/audit?limit=${limit}`),

  // Account + user management
  changePassword: (current_password: string, new_password: string): Promise<{ changed: boolean }> =>
    req("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password, new_password }),
    }),
  listUsers: (): Promise<AuthUser[]> => req("/auth/users"),
  resetUserPassword: (userId: string): Promise<{ username: string; temp_password: string }> =>
    req(`/auth/users/${userId}/reset-password`, { method: "POST" }),
  toggleUserActive: (userId: string): Promise<{ username: string; is_active: boolean }> =>
    req(`/auth/users/${userId}/toggle-active`, { method: "POST" }),
};
