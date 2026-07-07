"use client";
import { useEffect, useState } from "react";
import { api, auth } from "@/lib/api";
import type { AuthUser } from "@/types";

/* eslint-disable @typescript-eslint/no-explicit-any */

function Field({
  label, value, onChange, type = "text", placeholder, hint,
}: {
  label: string;
  value: string | number;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-gray-500 font-medium mb-1">{label}</label>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  );
}

function Section({
  title, subtitle, children, onSave, saving, badge,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  onSave: () => void;
  saving: boolean;
  badge?: string;
}) {
  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 inline-flex items-center gap-2">
            {title}
            {badge && (
              <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                {badge}
              </span>
            )}
          </h2>
          {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
        </div>
        <button
          onClick={onSave}
          disabled={saving}
          className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
      {children}
    </section>
  );
}

function MyAccountSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function change() {
    setMsg(null);
    if (next !== confirm) {
      setMsg({ ok: false, text: "New passwords do not match" });
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setMsg({ ok: true, text: "Password changed." });
      setCurrent(""); setNext(""); setConfirm("");
    } catch (e) {
      setMsg({ ok: false, text: String(e).replace(/^Error:\s*API error \d+:\s*/, "") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-700">My Account</h2>
          <p className="text-xs text-gray-400 mt-0.5">Change your password</p>
        </div>
        <button
          onClick={change}
          disabled={busy || !current || !next}
          className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50"
        >
          {busy ? "Saving..." : "Change password"}
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Field label="Current password" value={current} type="password" onChange={setCurrent} />
        <Field label="New password" value={next} type="password" onChange={setNext} hint="At least 8 characters" />
        <Field label="Confirm new password" value={confirm} type="password" onChange={setConfirm} />
      </div>
      {msg && (
        <p className={`text-sm mt-3 ${msg.ok ? "text-green-600" : "text-red-600"}`}>{msg.text}</p>
      )}
    </section>
  );
}

function UsersSection() {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [temp, setTemp] = useState<{ username: string; email: string | null; emailed: boolean; temp_password: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const me = auth.user();

  function load() {
    api.listUsers().then(setUsers).catch((e) => setError(String(e)));
  }
  useEffect(load, []);

  async function reset(u: AuthUser) {
    if (!window.confirm(`Reset password for "${u.username}"? Their current password stops working immediately.`)) return;
    try {
      setTemp(await api.resetUserPassword(u.id));
    } catch (e) {
      setError(String(e));
    }
  }

  async function toggle(u: AuthUser) {
    try {
      await api.toggleUserActive(u.id);
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-700">Users</h2>
        <p className="text-xs text-gray-400 mt-0.5">
          Password recovery: reset a user&apos;s password here. If email is configured it&apos;s sent to them; otherwise it&apos;s shown once below to hand over securely.
        </p>
      </div>

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      {temp && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-800">
          {temp.emailed ? (
            <>A temporary password was <span className="font-semibold">emailed to {temp.email}</span> for {temp.username}. They should change it after signing in.</>
          ) : (
            <>
              Temporary password for <span className="font-semibold">{temp.username}</span>:{" "}
              <code className="font-mono bg-white px-2 py-0.5 rounded border border-amber-200">{temp.temp_password}</code>
              <span className="block text-xs text-amber-600 mt-1">
                {temp.email ? "Email isn't configured, so " : "No email on file, so "}
                shown once — copy it now and share it securely.
              </span>
            </>
          )}
        </div>
      )}

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
            <th className="py-2 pr-4 font-medium">User</th>
            <th className="py-2 pr-4 font-medium">Role</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Last login</th>
            <th className="py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b border-gray-50">
              <td className="py-2.5 pr-4">
                <span className="font-medium text-gray-800">{u.username}</span>
                {u.full_name && <span className="text-gray-400 ml-2 text-xs">{u.full_name}</span>}
              </td>
              <td className="py-2.5 pr-4 capitalize text-gray-600">{u.role}</td>
              <td className="py-2.5 pr-4">
                <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${u.is_active ? "bg-green-50 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                  {u.is_active ? "active" : "disabled"}
                </span>
              </td>
              <td className="py-2.5 pr-4 text-gray-500 text-xs">
                {u.last_login_at ? new Date(u.last_login_at + "Z").toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" }) : "—"}
              </td>
              <td className="py-2.5 text-right space-x-3 whitespace-nowrap">
                <button onClick={() => reset(u)} className="text-xs font-medium text-blue-600 hover:text-blue-800">
                  Reset password
                </button>
                {u.id !== me?.id && (
                  <button onClick={() => toggle(u)} className="text-xs font-medium text-gray-500 hover:text-gray-700">
                    {u.is_active ? "Disable" : "Enable"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ComingSoon({ title, blurb, planned }: { title: string; blurb: string; planned: string[] }) {
  return (
    <section className="bg-white rounded-lg border border-gray-200 p-8 text-center">
      <div className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500 mb-3">
        Planned
      </div>
      <h2 className="text-base font-semibold text-gray-700">{title}</h2>
      <p className="text-sm text-gray-500 mt-1 max-w-md mx-auto">{blurb}</p>
      <ul className="mt-4 inline-block text-left text-sm text-gray-600 space-y-1">
        {planned.map((p) => (
          <li key={p} className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-gray-300 inline-block" />{p}
          </li>
        ))}
      </ul>
    </section>
  );
}

type AdminTab = "system" | "account" | "users" | "roles" | "permissions" | "integrations";

const TABS: { key: AdminTab; label: string; adminOnly?: boolean; planned?: boolean }[] = [
  { key: "system", label: "System Settings" },
  { key: "account", label: "My Account" },
  { key: "users", label: "Users", adminOnly: true },
  { key: "roles", label: "Roles", adminOnly: true, planned: true },
  { key: "permissions", label: "Permissions", adminOnly: true, planned: true },
  { key: "integrations", label: "API Integrations", adminOnly: true, planned: true },
];

export default function SettingsPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tab, setTab] = useState<AdminTab>("system");
  const isAdmin = auth.user()?.role === "admin";

  useEffect(() => {
    api.getSettings().then(setData).catch((e) => setError(String(e)));
  }, []);

  async function save(section: string, payload: Record<string, unknown>) {
    setSaving(section);
    setNotice(null);
    setError(null);
    try {
      const res = await api.updateSettings(payload);
      setNotice(
        res.restart_required
          ? "Saved. Restart the backend to apply database/table changes."
          : "Saved — changes applied."
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(null);
    }
  }

  const set = (path: string[], value: unknown) => {
    setData((prev: any) => {
      const next = structuredClone(prev);
      let node = next;
      for (const key of path.slice(0, -1)) node = node[key];
      node[path[path.length - 1]] = value;
      return next;
    });
  };

  if (error && !data) {
    return <div className="p-6 text-sm text-red-600">{error}</div>;
  }
  if (!data) {
    return <div className="p-6 flex items-center justify-center h-64 text-gray-400 text-sm">Loading settings...</div>;
  }

  const db = data.database;
  const mon = data.monitoring;
  const inst = data.institution;
  const alerts = data.alerts;
  const llm = data.llm;
  const tables = data.tables ?? {};
  const fields: string[] = data.mappable_fields ?? [];

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Administration</h1>
        <p className="text-sm text-gray-500 mt-1">Manage system configuration, users, and access.</p>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 border-b border-gray-200">
        {TABS.filter((t) => !t.adminOnly || isAdmin).map((t) => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setNotice(null); setError(null); }}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.key ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
            {t.planned && <span className="ml-1 text-[10px] text-gray-400">soon</span>}
          </button>
        ))}
      </div>

      {notice && (
        <div className="text-sm px-4 py-3 rounded-lg bg-green-50 text-green-700 border border-green-200">{notice}</div>
      )}
      {error && (
        <div className="text-sm px-4 py-3 rounded-lg bg-red-50 text-red-700 border border-red-200">{error}</div>
      )}

      {tab === "system" && (<>
      {/* Bank database */}
      <Section
        title="Bank Database"
        subtitle="Read-only connection to your core/transaction database"
        badge="restart required"
        saving={saving === "database"}
        onSave={() =>
          save("database", {
            database: {
              type: db.type,
              host: db.host,
              port: Number(db.port) || 0,
              user: db.user,
              password: db.password || "",
              database: db.database,
              trusted_connection: db.trusted_connection,
            },
          })
        }
      >
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs text-gray-500 font-medium mb-1">Type</label>
            <select
              value={db.type}
              onChange={(e) => set(["database", "type"], e.target.value)}
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="mysql">MySQL</option>
              <option value="mssql">SQL Server (MSSQL)</option>
            </select>
          </div>
          <Field label="Host" value={db.host} onChange={(v) => set(["database", "host"], v)} placeholder=". or hostname" />
          <Field label="Port" value={db.port} type="number" onChange={(v) => set(["database", "port"], v)} />
          <Field label="Database" value={db.database} onChange={(v) => set(["database", "database"], v)} />
          <Field label="User" value={db.user} onChange={(v) => set(["database", "user"], v)} hint="Use a read-only DB user" />
          <Field
            label={`Password ${db.password_set ? "(set)" : "(not set)"}`}
            value={db.password ?? ""}
            type="password"
            placeholder="Leave blank to keep current"
            onChange={(v) => set(["database", "password"], v)}
          />
        </div>
        <label className="flex items-center gap-2 mt-4 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={!!db.trusted_connection}
            onChange={(e) => set(["database", "trusted_connection"], e.target.checked)}
            className="rounded border-gray-300"
          />
          Windows Authentication (trusted connection — MSSQL only)
        </label>
      </Section>

      {/* Table mappings */}
      <Section
        title="Table Mappings"
        subtitle="Map your table columns onto the fields FMS understands"
        badge="restart required"
        saving={saving === "tables"}
        onSave={() => save("tables", { tables })}
      >
        <div className="space-y-6">
          {Object.entries(tables).map(([key, cfg]: [string, any]) => (
            <div key={key} className="border border-gray-100 rounded-lg p-4">
              <p className="text-xs font-bold text-gray-600 uppercase tracking-wide mb-3">
                {key} transactions
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <Field
                  label="Table name"
                  value={cfg.table_name ?? ""}
                  onChange={(v) => set(["tables", key, "table_name"], v)}
                />
                {fields.map((f) => (
                  <Field
                    key={f}
                    label={f}
                    value={cfg.columns?.[f] ?? ""}
                    placeholder="(unmapped)"
                    onChange={(v) => {
                      setData((prev: any) => {
                        const next = structuredClone(prev);
                        next.tables[key].columns = next.tables[key].columns ?? {};
                        if (v) next.tables[key].columns[f] = v;
                        else delete next.tables[key].columns[f];
                        return next;
                      });
                    }}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* Monitoring */}
      <Section
        title="Monitoring"
        subtitle="Applied live — no restart needed"
        saving={saving === "monitoring"}
        onSave={() =>
          save("monitoring", {
            monitoring: {
              poll_interval_seconds: Number(mon.poll_interval_seconds) || 30,
              history_days: Number(mon.history_days) || 90,
            },
          })
        }
      >
        <div className="grid grid-cols-2 gap-4">
          <Field
            label="Poll interval (seconds)"
            value={mon.poll_interval_seconds}
            type="number"
            onChange={(v) => set(["monitoring", "poll_interval_seconds"], v)}
            hint="How often FMS checks for new transactions (min 5s)"
          />
          <Field
            label="History window (days)"
            value={mon.history_days}
            type="number"
            onChange={(v) => set(["monitoring", "history_days"], v)}
            hint="Days of account history used as the behavioural baseline"
          />
        </div>
      </Section>

      {/* Institution */}
      <Section
        title="Institution"
        subtitle="Pre-fills the filing-institution section of FinCEN CTR/SAR worksheets — applied live"
        saving={saving === "institution"}
        onSave={() => save("institution", { institution: inst })}
      >
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <Field label="Institution name" value={inst.name} onChange={(v) => set(["institution", "name"], v)} />
          <Field label="EIN" value={inst.ein} onChange={(v) => set(["institution", "ein"], v)} />
          <Field label="Primary regulator" value={inst.primary_regulator} onChange={(v) => set(["institution", "primary_regulator"], v)} placeholder="FDIC / OCC / NCUA / FRB" />
          <Field label="Address" value={inst.address} onChange={(v) => set(["institution", "address"], v)} />
          <Field label="City" value={inst.city} onChange={(v) => set(["institution", "city"], v)} />
          <Field label="State" value={inst.state} onChange={(v) => set(["institution", "state"], v)} />
          <Field label="ZIP" value={inst.zip} onChange={(v) => set(["institution", "zip"], v)} />
        </div>
      </Section>

      {/* Alerts */}
      <Section
        title="Email Alerts"
        subtitle="Fraud alert emails via Gmail — applied live"
        saving={saving === "alerts"}
        onSave={() =>
          save("alerts", {
            alerts: {
              gmail_user: alerts.gmail_user,
              gmail_app_password: alerts.gmail_app_password || "",
              alert_email: alerts.alert_email,
            },
          })
        }
      >
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          <Field label="Gmail address" value={alerts.gmail_user} onChange={(v) => set(["alerts", "gmail_user"], v)} />
          <Field
            label={`App password ${alerts.gmail_app_password_set ? "(set)" : "(not set)"}`}
            value={alerts.gmail_app_password ?? ""}
            type="password"
            placeholder="Leave blank to keep current"
            onChange={(v) => set(["alerts", "gmail_app_password"], v)}
          />
          <Field label="Send alerts to" value={alerts.alert_email} onChange={(v) => set(["alerts", "alert_email"], v)} />
        </div>
      </Section>

      {/* LLM */}
      <Section
        title="AI Summaries (LLM)"
        subtitle="Optional — writes the prose case summary only; all detection decisions are deterministic. Applied live"
        saving={saving === "llm"}
        onSave={() =>
          save("llm", {
            llm: {
              groq_api_key: llm.groq_api_key || "",
              base_url: llm.base_url,
              model: llm.model,
              api_key: llm.api_key || "",
            },
          })
        }
      >
        <div className="grid grid-cols-2 gap-4">
          <Field
            label={`Groq API key ${llm.groq_api_key_set ? "(set)" : "(not set)"}`}
            value={llm.groq_api_key ?? ""}
            type="password"
            placeholder="Leave blank to keep current"
            onChange={(v) => set(["llm", "groq_api_key"], v)}
          />
          <Field label="Model" value={llm.model} onChange={(v) => set(["llm", "model"], v)} />
          <Field
            label="Self-hosted endpoint (optional)"
            value={llm.base_url}
            onChange={(v) => set(["llm", "base_url"], v)}
            placeholder="http://localhost:11434/v1"
            hint="Any OpenAI-compatible endpoint (e.g. Ollama). When set, transaction data never leaves your infrastructure."
          />
          <Field
            label={`Endpoint API key ${llm.api_key_set ? "(set)" : "(not set)"}`}
            value={llm.api_key ?? ""}
            type="password"
            placeholder="Only if your endpoint needs one"
            onChange={(v) => set(["llm", "api_key"], v)}
          />
        </div>
      </Section>

      {/* Security */}
      <Section
        title="Security"
        subtitle="API key protecting cases, reports, and this settings page"
        saving={saving === "security"}
        onSave={() => save("security", { security: { fms_api_key: data.security.fms_api_key ?? "" } })}
      >
        <div className="grid grid-cols-2 gap-4">
          <Field
            label={`FMS API key ${data.security.api_key_set ? "(set)" : "(not set — API is open)"}`}
            value={data.security.fms_api_key ?? ""}
            type="password"
            placeholder="Set to require X-API-Key on all requests"
            onChange={(v) => set(["security", "fms_api_key"], v)}
            hint="Takes effect immediately. The frontend must send the same key (NEXT_PUBLIC_FMS_API_KEY) — configure both together."
          />
        </div>
      </Section>
      </>)}

      {tab === "account" && <MyAccountSection />}

      {tab === "users" && isAdmin && <UsersSection />}

      {tab === "roles" && (
        <ComingSoon
          title="Roles"
          blurb="FMS currently uses two built-in roles — admin and analyst — which gate access today. A UI to define and assign custom roles is planned."
          planned={["Built-in: admin, analyst (active now)", "Create custom roles", "Assign roles per user"]}
        />
      )}

      {tab === "permissions" && (
        <ComingSoon
          title="Permissions"
          blurb="Access is role-based today (admin vs. analyst). Granular, per-capability permissions are planned."
          planned={["Per-action permissions (view / action / configure)", "Permission sets attached to roles", "Least-privilege presets"]}
        />
      )}

      {tab === "integrations" && (
        <ComingSoon
          title="API Integrations"
          blurb="Manage how external systems feed and receive data. The ingestion API key lives under System Settings → Security today; richer integration management is planned."
          planned={["Ingestion API keys & rotation", "Outbound webhooks (new case / sanctions hit)", "Connectors for core banking / payment processors"]}
        />
      )}
    </div>
  );
}
