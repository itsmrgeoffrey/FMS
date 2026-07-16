"use client";
import { useCallback, useEffect, useState } from "react";
import { api, type SecurityEventsResponse, type SecuritySeverity } from "@/lib/api";
import type { AuditEntry } from "@/types";

interface UserRow {
  username: string;
  actions: number;
  failed_logins: number;
  case_actions: number;
  last_activity: string | null;
}

const ACTION_LABELS: Record<string, string> = {
  LOGIN: "Signed in",
  LOGIN_FAILED: "Failed sign-in",
  LOGIN_RATE_LIMITED: "Rate-limited (too many attempts)",
  SIGNUP: "Created account",
  PASSWORD_CHANGED: "Changed password",
  PASSWORD_RESET_REQUESTED: "Requested password reset",
  SETTINGS_UPDATED: "Updated settings",
  USER_CREATED: "Created a user",
  USER_PASSWORD_RESET: "Reset a user's password",
  USER_ROLE_CHANGED: "Changed a user's role",
  USER_ENABLED: "Enabled a user",
  USER_DISABLED: "Disabled a user",
  INGEST_KEY_REJECTED: "Rejected ingestion API key",
  SANCTIONS_HIT: "OFAC sanctions hit",
  CASE_REVIEW: "Marked case under review",
  CASE_CONFIRMED: "Confirmed fraud",
  CASE_DISMISSED: "Dismissed case",
  CASE_ESCALATED: "Escalated case",
  CASE_NOTE_ADDED: "Added note",
};

function label(a: string): string {
  return ACTION_LABELS[a] ?? a.toLowerCase().replace(/_/g, " ");
}
function fmtDate(ts: string): string {
  return new Date(ts + "Z").toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "medium" });
}
function ago(ts: string | null): string {
  if (!ts) return "—";
  const s = Math.max(0, (Date.now() - new Date(ts + "Z").getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function sevDot(sev: SecuritySeverity): string {
  return { critical: "bg-red-500", warning: "bg-amber-400", notice: "bg-blue-400", info: "bg-slate-300" }[sev];
}

export default function AuditPage() {
  const [tab, setTab] = useState<"users" | "security">("users");
  const [users, setUsers] = useState<UserRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [sec, setSec] = useState<SecurityEventsResponse | null>(null);
  const [secLoading, setSecLoading] = useState(false);

  useEffect(() => {
    api.getAuditUsers().then(setUsers).catch((e) => setError(String(e))).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (tab === "security" && !sec) {
      setSecLoading(true);
      api.getSecurityEvents(200).then(setSec).catch((e) => setError(String(e))).finally(() => setSecLoading(false));
    }
  }, [tab, sec]);

  const investigate = useCallback((username: string) => {
    setSelected(username);
    setHistory([]);
    api.getAudit(500, username).then(setHistory).catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>;

  // ── User investigation view (drill-down from the Users tab) ────────────────
  if (selected) {
    const summary = users.find((u) => u.username === selected);
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-6">
        <button onClick={() => setSelected(null)} className="text-sm text-blue-600 hover:text-blue-800 inline-flex items-center gap-1">
          ← All users
        </button>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{selected}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {summary ? `${summary.actions} recorded actions · ${summary.case_actions} case actions · ${summary.failed_logins} failed sign-ins` : "Activity history"}
          </p>
        </div>

        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Activity history</h2>
          {history.length === 0 ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : (
            <ol className="relative border-l border-gray-200 space-y-4 ml-2">
              {history.map((a) => (
                <li key={a.id} className="ml-5">
                  <span className={`absolute -left-1.5 w-3 h-3 rounded-full ${a.action === "LOGIN_FAILED" ? "bg-red-400" : a.action.startsWith("CASE_") ? "bg-amber-400" : "bg-slate-300"}`} />
                  <p className="text-sm font-medium text-gray-800">{label(a.action)}</p>
                  <p className="text-xs text-gray-400">
                    {fmtDate(a.created_at)}{a.ip ? ` · ${a.ip}` : ""}{a.target ? ` · ${a.target.slice(0, 8)}` : ""}
                  </p>
                  {a.detail && <p className="text-xs text-gray-500 mt-0.5 bg-gray-50 rounded px-2 py-1 font-mono break-words">{a.detail}</p>}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    );
  }

  // ── Main view: tabbed Users / Security events ──────────────────────────────
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Audit &amp; Security</h1>
        <p className="text-sm text-gray-500 mt-1">Who did what across the system, and the security-relevant events an examiner cares about.</p>
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        {(["users", "security"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t === "users" ? "Users" : "Security events"}
          </button>
        ))}
      </div>

      {tab === "users" ? (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Total actions</th>
                <th className="px-4 py-3 font-medium">Case actions</th>
                <th className="px-4 py-3 font-medium">Failed sign-ins</th>
                <th className="px-4 py-3 font-medium">Last active</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody className={loading ? "opacity-50" : ""}>
              {!loading && users.length === 0 && (
                <tr><td colSpan={6} className="text-center py-12 text-gray-400">No activity recorded yet.</td></tr>
              )}
              {users.map((u) => (
                <tr key={u.username} className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer" onClick={() => investigate(u.username)}>
                  <td className="px-4 py-3 font-medium text-gray-800">{u.username}</td>
                  <td className="px-4 py-3 text-gray-700">{u.actions}</td>
                  <td className="px-4 py-3 text-gray-700">{u.case_actions}</td>
                  <td className="px-4 py-3">
                    {u.failed_logins > 0
                      ? <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-red-50 text-red-700">{u.failed_logins}</span>
                      : <span className="text-gray-300">0</span>}
                  </td>
                  <td className="px-4 py-3 text-gray-500">{ago(u.last_activity)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="text-blue-600 text-xs font-medium">Investigate →</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: "Failed sign-ins", value: sec?.counts.failed_logins ?? 0, tone: "text-amber-600" },
              { label: "Rejected API keys", value: sec?.counts.rejected_keys ?? 0, tone: "text-amber-600" },
              { label: "Sanctions hits", value: sec?.counts.sanctions_hits ?? 0, tone: "text-red-600" },
            ].map((t) => (
              <div key={t.label} className="bg-white rounded-lg border border-gray-200 p-4">
                <p className="text-xs text-gray-500">{t.label}</p>
                <p className={`text-2xl font-bold mt-1 ${t.value > 0 ? t.tone : "text-gray-800"}`}>{t.value}</p>
              </div>
            ))}
          </div>

          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
                  <th className="px-4 py-3 font-medium">Time</th>
                  <th className="px-4 py-3 font-medium">Event</th>
                  <th className="px-4 py-3 font-medium">User</th>
                  <th className="px-4 py-3 font-medium">IP</th>
                  <th className="px-4 py-3 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody className={secLoading ? "opacity-50" : ""}>
                {secLoading && (
                  <tr><td colSpan={5} className="text-center py-12 text-gray-400">Loading…</td></tr>
                )}
                {!secLoading && sec && sec.events.length === 0 && (
                  <tr><td colSpan={5} className="text-center py-12 text-gray-400">No security events recorded yet.</td></tr>
                )}
                {sec?.events.map((e) => (
                  <tr key={e.id} className="border-b border-gray-50">
                    <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap">{fmtDate(e.created_at)}</td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full shrink-0 ${sevDot(e.severity)}`} />
                        <span className="font-medium text-gray-800">{label(e.action)}</span>
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-gray-700">{e.username}</td>
                    <td className="px-4 py-2.5 text-gray-500 font-mono text-xs">{e.ip ?? "—"}</td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs max-w-xs truncate" title={e.detail ?? ""}>{e.detail ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
