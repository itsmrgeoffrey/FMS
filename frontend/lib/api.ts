import type { CasesPage, FraudCase, Stats } from "@/types";

const BASE = "/api";
// Optional — only needed if the backend has FMS_API_KEY set.
const API_KEY = process.env.NEXT_PUBLIC_FMS_API_KEY;

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return API_KEY ? { ...extra, "X-API-Key": API_KEY } : extra;
}

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: authHeaders(options.headers as Record<string, string>),
  });
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

  // Regulatory filing exports (CSV download links).
  ctrReportUrl: (params?: Record<string, string | undefined>) => reportUrl("ctr", params),
  sarReportUrl: (params?: Record<string, string | undefined>) => reportUrl("sar", params),
};
