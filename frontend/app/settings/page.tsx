"use client";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Plus, Trash2, X } from "lucide-react";
import { LoadError, RefreshButton } from "@/components/ReviewUI";
import { useRouter, useSearchParams } from "next/navigation";
import RuleEngineSettings from "@/components/RuleEngineSettings";
import InstallationSettings from "@/components/InstallationSettings";
import { api, auth } from "@/lib/api";
import type { Approval, ApprovalsPage } from "@/lib/api";
import type { AuthUser, AuditEntry } from "@/types";

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

function DatabaseConnectionFields({ db, onSet }: { db: any; onSet: (field: string, value: unknown) => void }) {
  return <div className="space-y-4">
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
      <div>
        <label className="block text-xs text-gray-500 font-medium mb-1">Type</label>
        <select value={db.type ?? "mysql"} onChange={(e) => onSet("type", e.target.value)} className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
          <option value="mysql">MySQL</option><option value="mssql">SQL Server (MSSQL)</option><option value="postgres">PostgreSQL</option><option value="oracle">Oracle</option>
        </select>
      </div>
      <Field label="Host" value={db.host ?? ""} onChange={(v) => onSet("host", v)} placeholder="Hostname or IP address" />
      <Field label="Port" value={db.port ?? ""} type="number" onChange={(v) => onSet("port", Number(v) || 0)} />
      <Field label="Database" value={db.database ?? ""} onChange={(v) => onSet("database", v)} />
      <Field label="User" value={db.user ?? ""} onChange={(v) => onSet("user", v)} hint="Use a read-only DB user" />
      <Field label="Password" value={db.password ?? ""} type="password" placeholder={db.password_set ? "Stored securely" : "Not set"} onChange={(v) => onSet("password", v)} hint={db.password_set ? "Leave blank to keep the stored password." : "Enter the read-only user's password."} />
    </div>
    <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-gray-700">
      <label className="flex items-center gap-2"><input type="checkbox" checked={!!db.trusted_connection} onChange={(e) => onSet("trusted_connection", e.target.checked)} className="rounded border-gray-300" />Windows Authentication</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={!!db.encrypt} onChange={(e) => onSet("encrypt", e.target.checked)} className="rounded border-gray-300" />Encrypt connection (TLS)</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={!!db.trust_server_certificate} onChange={(e) => onSet("trust_server_certificate", e.target.checked)} className="rounded border-gray-300" />Trust server certificate</label>
    </div>
  </div>;
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
    <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-5">
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
      const session = await api.changePassword(current, next);
      auth.set(session.token, session.user);
      setMsg({ ok: true, text: "Password changed." });
      setCurrent(""); setNext(""); setConfirm("");
    } catch (e) {
      setMsg({ ok: false, text: String(e).replace(/^Error:\s*API error \d+:\s*/, "") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-5">
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

function UsersSection({ onChanged }: { onChanged: () => void }) {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [temp, setTemp] = useState<{ username: string; email: string | null; emailed: boolean; temp_password: string | null } | null>(null);
  const [pendingMsg, setPendingMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Create-user form
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newRole, setNewRole] = useState("analyst");
  const [creating, setCreating] = useState(false);
  const me = auth.user();

  const load = useCallback(() => {
    api.listUsers().then(setUsers).catch((e) => setError(String(e)));
    onChanged();
  }, [onChanged]);
  useEffect(load, [load]);

  /** Dual control: sensitive actions may come back queued instead of applied. */
  function handled<T extends object>(res: T | { pending: true; message: string }): res is { pending: true; message: string } {
    if ("pending" in res && res.pending) {
      setPendingMsg(res.message);
      load();
      return true;
    }
    return false;
  }

  async function createUser() {
    setError(null);
    setPendingMsg(null);
    setTemp(null);
    setCreating(true);
    try {
      const res = await api.createUser(newEmail.trim(), newName.trim(), newRole);
      if (!handled(res)) {
        setTemp(res as { username: string; email: string | null; emailed: boolean; temp_password: string | null });
        setNewEmail(""); setNewName(""); setNewRole("analyst");
      }
      load();
    } catch (e) {
      setError(String(e).replace(/^Error:\s*API error \d+:\s*/, ""));
    } finally {
      setCreating(false);
    }
  }

  async function reset(u: AuthUser) {
    if (!window.confirm(`Reset password for "${u.username}"? Their current password stops working immediately.`)) return;
    setPendingMsg(null);
    try {
      const res = await api.resetUserPassword(u.id);
      if (!handled(res)) setTemp(res as { username: string; email: string | null; emailed: boolean; temp_password: string | null });
    } catch (e) {
      setError(String(e));
    }
  }

  async function toggle(u: AuthUser) {
    setPendingMsg(null);
    try {
      handled(await api.toggleUserActive(u.id));
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function changeRole(u: AuthUser, role: string) {
    setPendingMsg(null);
    try {
      handled(await api.setUserRole(u.id, role));
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <>
    <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-700">Users</h2>
        <p className="text-xs text-gray-400 mt-0.5">
          Create accounts, assign roles, reset passwords, and enable/disable users.
        </p>
        <p className="text-xs text-gray-400 mt-1">
          <span className="font-medium text-gray-500">Admin</span> — full access ·{" "}
          <span className="font-medium text-gray-500">Analyst</span> — view + act on cases ·{" "}
          <span className="font-medium text-gray-500">Viewer</span> — read-only
        </p>
      </div>

      {/* Create user */}
      <div className="mb-5 p-4 rounded-lg bg-gray-50 border border-gray-100">
        <p className="text-xs font-semibold text-gray-600 mb-3">Add a user</p>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <Field label="Email" value={newEmail} onChange={setNewEmail} placeholder="name@yourbank.com" />
          <Field label="Full name (optional)" value={newName} onChange={setNewName} />
          <div>
            <label className="block text-xs text-gray-500 font-medium mb-1">Role</label>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 capitalize"
            >
              <option value="admin">Admin</option>
              <option value="analyst">Analyst</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>
          <button
            onClick={createUser}
            disabled={creating || !newEmail.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white transition-colors disabled:opacity-50"
          >
            {creating ? "Creating..." : "Create user"}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          A temporary password is emailed to the user (or shown once here if email isn&apos;t configured).
        </p>
      </div>

      {pendingMsg && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-blue-50 border border-blue-200 text-sm text-blue-800">
          {pendingMsg} <Link href="/settings?tab=approvals" className="font-medium underline">View approvals</Link>
        </div>
      )}
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      {temp && <TemporaryPasswordNotice temp={temp} onDismiss={() => setTemp(null)} />}

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
              <td className="py-2.5 pr-4">
                {u.id === me?.id ? (
                  <span className="capitalize text-gray-600">{u.role}</span>
                ) : (
                  <select
                    value={u.role}
                    onChange={(e) => changeRole(u, e.target.value)}
                    className="text-sm border border-gray-200 rounded px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 capitalize"
                  >
                    <option value="admin">Admin</option>
                    <option value="analyst">Analyst</option>
                    <option value="viewer">Viewer</option>
                  </select>
                )}
              </td>
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
    </>
  );
}

type TemporaryPassword = { username: string; email: string | null; emailed: boolean; temp_password: string | null };

function TemporaryPasswordNotice({ temp, onDismiss }: { temp: TemporaryPassword; onDismiss: () => void }) {
  return (
        <div className="mb-4 px-4 py-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-800">
          <button type="button" onClick={onDismiss} title="Dismiss credential notice" aria-label="Dismiss credential notice" className="float-right ml-3 p-1"><X size={16} /></button>
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
  );
}

function ApprovalsSection({
  approvals, onChanged, onTemp,
}: {
  approvals: ApprovalsPage;
  onChanged: () => void;
  onTemp: (t: { username: string; email: string | null; emailed: boolean; temp_password: string | null }) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function decide(a: Approval, action: "approve" | "reject" | "cancel") {
    if (action === "approve" && a.configuration_proposal && !window.confirm(
      "Apply this detection configuration? Your approval and the requester's identity will be recorded. Review the proposed values and reason before confirming.")) return;
    setError(null);
    setBusy(a.id);
    try {
      if (action === "approve") {
        const res = await api.approveChange(a.id);
        // A user-create/password-reset approval may surface a one-time temp password.
        const r = res.result as { username?: string; email?: string | null; emailed?: boolean; temp_password?: string | null };
        if (r && (r.temp_password || r.emailed)) {
          onTemp({ username: r.username ?? "", email: r.email ?? null, emailed: !!r.emailed, temp_password: r.temp_password ?? null });
        }
      } else if (action === "reject") {
        const note = window.prompt("Reason for rejecting (optional):");
        if (note === null) return;
        await api.rejectChange(a.id, note);
      } else {
        await api.cancelChange(a.id);
      }
      onChanged();
    } catch (e) {
      setError(String(e).replace(/^Error:\s*API error \d+:\s*/, ""));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="space-y-4">
      <div className="mb-3 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-gray-700">Pending approvals</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Sensitive changes need a second admin&apos;s sign-off — the requester can never approve their own change.
          </p>
        </div>
        {approvals.dual_control_active ? (
          <span className="text-xs font-medium px-2 py-1 rounded bg-green-50 text-green-700 border border-green-200">
            ✓ Dual control active ({approvals.active_admins} admins)
          </span>
        ) : (
          <span className="text-xs font-medium px-2 py-1 rounded bg-amber-50 text-amber-700 border border-amber-200">
            Rule and profile changes require a different administrator
          </span>
        )}
      </div>

      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      {approvals.active_admins < 2 && <div role="status" className="border-l-4 border-amber-500 bg-amber-50 p-3 text-sm text-amber-900">
        Only {approvals.active_admins} active administrator account(s). Rule and profile changes remain pending until a different active administrator approves.
        <Link href="/settings?tab=users" className="ml-1 font-medium underline">Manage administrators</Link>
      </div>}
      {approvals.pending.length === 0 ? (
        <p className="text-sm text-gray-400">No changes waiting for approval.</p>
      ) : (
        <ul className="divide-y divide-gray-50">
          {approvals.pending.map((a) => {
            const mine = a.requested_by === approvals.me;
            return (
              <li key={a.id} className="py-3 flex items-center justify-between gap-4 flex-wrap">
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-gray-800">{a.summary}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    requested by <span className="font-medium">{mine ? "you" : a.requested_by}</span>{" "}
                    · {new Date(a.requested_at + "Z").toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })}
                  </p>
                  {a.configuration_proposal && <div className="mt-3 space-y-2 border-l-2 border-blue-300 pl-3 text-xs text-gray-700">
                    <p className="break-words"><span className="font-semibold">Reason:</span> {a.configuration_proposal.rationale}</p>
                    {Object.entries(a.configuration_proposal.proposed).flatMap(([key, value]) =>
                      key === "ctr_thresholds" ? Object.entries(value as Record<string, number>).map(([currency, amount]) => ({
                        label: `${currency} benchmark`, before: (a.configuration_proposal!.before.ctr_thresholds as Record<string, number> | undefined)?.[currency], after: amount,
                      })) : [{ label: key.replaceAll("_", " "), before: a.configuration_proposal!.before[key], after: value }]
                    ).filter(change => JSON.stringify(change.before) !== JSON.stringify(change.after))
                      .map(change => <p key={change.label} className="break-words"><span className="font-medium">{change.label}:</span> {JSON.stringify(change.before) ?? "Not recorded"} to {JSON.stringify(change.after)}</p>)}
                    {a.configuration_proposal.initial_configuration_allowed && <p className="text-amber-800">Initial configuration without replay history is permitted by this proposal.</p>}
                    {a.configuration_proposal.stale && <p className="font-medium text-red-700">Outdated proposal. Cancel or reject it and request a new proposal.</p>}
                  </div>}
                </div>
                <div className="space-x-2 whitespace-nowrap">
                  {mine ? (
                    <button
                      onClick={() => decide(a, "cancel")}
                      disabled={busy !== null}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                    >
                      Cancel my request
                    </button>
                  ) : (
                    <>
                      <button
                        onClick={() => decide(a, "approve")}
                        disabled={busy !== null || !!a.configuration_proposal?.stale}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => decide(a, "reject")}
                        disabled={busy !== null}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 disabled:opacity-50"
                      >
                        Reject
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {approvals.recent.length > 0 && (
        <details className="mt-4">
          <summary className="text-xs font-medium text-gray-500 cursor-pointer hover:text-gray-700">
            Recent decisions ({approvals.recent.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {approvals.recent.map((a) => (
              <li key={a.id} className="text-xs text-gray-500">
                <span className={
                  a.status === "approved" ? "text-green-600 font-medium" :
                  a.status === "rejected" ? "text-red-600 font-medium" : "text-gray-400 font-medium"
                }>
                  {a.status}
                </span>{" "}
                — {a.summary} <span className="text-gray-400">(by {a.decided_by})</span>
                {a.decision_note && <span className="text-gray-400 italic"> — “{a.decision_note}”</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/**
 * The role → capability matrix, read from the API so it always reflects what the
 * server actually enforces rather than a hand-maintained copy that can drift.
 */
function RolesPermissions() {
  const [data, setData] = useState<{
    capabilities: { key: string; label: string; description: string }[];
    roles: { role: string; capabilities: string[] }[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getRoles().then(setData).catch(() => setError("Could not load roles."));
  }, []);

  if (error) {
    return (
      <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-6 text-sm text-red-600">
        {error}
      </section>
    );
  }
  if (!data) {
    return (
      <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-6 text-sm text-gray-400">
        Loading roles…
      </section>
    );
  }

  return (
    <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100">
        <h2 className="text-base font-semibold text-gray-900">Roles &amp; Permissions</h2>
        <p className="text-sm text-gray-500 mt-1">
          Enforced by the API on every request. This table is read from the same definition the
          server checks, so it cannot drift from what is actually applied. Assign a role to a
          person under <span className="font-medium text-gray-700">Users</span>.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
              <th className="px-5 py-3 font-medium">Role</th>
              {data.capabilities.map((c) => (
                <th key={c.key} className="px-5 py-3 font-medium text-center">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.roles.map((r) => (
              <tr key={r.role} className="border-b border-gray-50 last:border-0">
                <td className="px-5 py-3 font-medium text-gray-900 capitalize">{r.role}</td>
                {data.capabilities.map((c) => (
                  <td key={c.key} className="px-5 py-3 text-center">
                    {r.capabilities.includes(c.key) ? (
                      <span className="text-green-600 font-semibold" title={`${r.role} can ${c.label.toLowerCase()}`}>&#10003;</span>
                    ) : (
                      <span className="text-gray-300" title="Not permitted">&mdash;</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="px-5 py-4 border-t border-gray-100 space-y-2">
        {data.capabilities.map((c) => (
          <div key={c.key} className="flex gap-2 text-sm">
            <dt className="font-medium text-gray-700 shrink-0">{c.label}</dt>
            <dd className="text-gray-500">— {c.description}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

type AdminTab = "system" | "rules" | "approvals" | "installation" | "account" | "users" | "roles" | "directory" | "integrations";

const TABS: { key: AdminTab; label: string; adminOnly?: boolean }[] = [
  { key: "system", label: "System", adminOnly: true },
  { key: "rules", label: "Rule Engine", adminOnly: true },
  { key: "approvals", label: "Approvals", adminOnly: true },
  { key: "installation", label: "Installation", adminOnly: true },
  { key: "account", label: "My Account" },
  { key: "users", label: "Users", adminOnly: true },
  { key: "roles", label: "Roles & Permissions", adminOnly: true },
  { key: "directory", label: "Directory (SSO)", adminOnly: true },
  { key: "integrations", label: "API Integrations", adminOnly: true },
];

export default function SettingsPage() {
  return <Suspense fallback={<p role="status" className="p-6 text-sm text-gray-500">Loading settings...</p>}><SettingsContent /></Suspense>;
}

function SettingsContent() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab = TABS.find(t => t.key === searchParams.get("tab"))?.key ?? "system";
  function selectTab(key: AdminTab) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", key);
    router.push(`/settings?${params}`, { scroll: false });
    setNotice(null);
    setError(null);
  }
  const [sysInfo, setSysInfo] = useState<Record<string, any> | null>(null);
  const [health, setHealth] = useState<{ bank_db_connected: boolean; last_poll_at: string | null } | null>(null);
  const [testResult, setTestResult] = useState<{ connected: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [dirTest, setDirTest] = useState<{ connected: boolean; message: string } | null>(null);
  const [dirTesting, setDirTesting] = useState(false);
  const [activity, setActivity] = useState<AuditEntry[]>([]);
  const pristine = useRef<string>("");
  const isAdmin = auth.user()?.role === "admin";
  const [approvals, setApprovals] = useState<ApprovalsPage | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [approvalRevision, setApprovalRevision] = useState(0);
  const [approvalTemp, setApprovalTemp] = useState<TemporaryPassword | null>(null);
  const refreshApprovals = useCallback(() => { setApprovalRevision(value => value + 1); }, []);

  useEffect(() => {
    if (!isAdmin) return;
    let active = true;
    let inFlight = false;
    async function refresh() {
      if (inFlight) return;
      inFlight = true;
      setApprovalLoading(true);
      try {
        const result = await api.listApprovals();
        if (active) { setApprovals(result); setApprovalError(null); }
      } catch (e) {
        if (active) setApprovalError(String(e));
      } finally {
        inFlight = false;
        if (active) setApprovalLoading(false);
      }
    }
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 30000);
    window.addEventListener("focus", refresh);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [isAdmin, approvalRevision, tab]);

  useEffect(() => {
    if (!isAdmin) return;
    api.getSettings().then((d) => { setData(d); pristine.current = JSON.stringify(d); }).catch((e) => setError(String(e)));
    api.getSystemInfo().then(setSysInfo).catch(() => {});
    api.getHealth().then(setHealth).catch(() => {});
    api.getAudit(50).then((a) => setActivity(a.filter((e) => e.action === "SETTINGS_UPDATED"))).catch(() => {});
  }, [isAdmin]);

  const dirty = !!data && !!pristine.current && JSON.stringify(data) !== pristine.current;

  async function testConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await api.testConnection();
      setTestResult(r);
    } catch (e) {
      setTestResult({ connected: false, message: String(e) });
    } finally {
      setTesting(false);
    }
  }

  async function save(section: string, payload: Record<string, unknown>) {
    setSaving(section);
    setNotice(null);
    setError(null);
    try {
      const res = await api.updateSettings(payload);
      if ("pending" in res && res.pending) {
        setNotice(`⏳ ${res.message}`);
        setSaving(null);
        return;
      }
      setNotice(
        res.restart_required
          ? "Saved. Restart the backend to apply database/table changes."
          : "Saved — changes applied."
      );
      setData((d: any) => { pristine.current = JSON.stringify(d); return d; });
      api.getAudit(50).then((a) => setActivity(a.filter((e) => e.action === "SETTINGS_UPDATED"))).catch(() => {});
    } catch (e) {
      const msg = String(e).replace(/^Error:\s*API error \d+:\s*/, "");
      setError(msg.includes("401") || /invalid/i.test(msg) ? "Invalid credentials or unauthorized." : msg);
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

  const toggleSeparateDatabase = (tableKey: string, enabled: boolean) => {
    setData((prev: any) => {
      const next = structuredClone(prev);
      if (enabled) {
        const shared = structuredClone(next.database);
        delete shared.password;
        delete shared.password_set;
        next.tables[tableKey].database = { ...shared, password: "", password_set: false };
      } else {
        delete next.tables[tableKey].database;
      }
      return next;
    });
  };

  function addTransactionFeed(direction: "inward" | "outward") {
    setData((prev: any) => ({
      ...prev,
      tables: {
        ...prev.tables,
        [direction]: prev.tables?.[direction] ?? { table_name: "", columns: {} },
      },
    }));
  }

  function removeTransactionFeed(key: string) {
    if (!window.confirm(`Remove the ${key} feed from these settings? Saving and restarting will stop polling this feed.`)) return;
    setData((prev: any) => {
      const next = structuredClone(prev);
      delete next.tables[key];
      return next;
    });
  }

  function saveTransactionFeeds() {
    for (const [key, cfg] of Object.entries(data.tables ?? {}) as [string, any][]) {
      if (!cfg.table_name?.trim()) {
        setError(`Enter a table name for the ${key} feed.`);
        return;
      }
      const missing = ["id", "account_id", "amount", "timestamp"].filter(field => !cfg.columns?.[field]?.trim());
      if (missing.length) {
        setError(`Map the required ${key} fields: ${missing.join(", ")}.`);
        return;
      }
    }
    void save("tables", { tables: data.tables ?? {} });
  }

  // Non-admins have no Administration access — just their own account.
  if (!isAdmin) {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-900">My Account</h1>
          <p className="text-sm text-gray-500 mt-1">Manage your password.</p>
        </div>
        <MyAccountSection />
      </div>
    );
  }

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
    <div className="p-4 sm:p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-1">Manage system configuration, users, and access.</p>
      </div>

      {/* Tabs */}
      <div role="tablist" aria-label="Settings" className="flex flex-wrap gap-1 border-b border-gray-200">
        {TABS.filter((t) => !t.adminOnly || isAdmin).map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`settings-tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls="settings-panel"
            tabIndex={tab === t.key ? 0 : -1}
            onClick={() => selectTab(t.key)}
            onKeyDown={event => {
              const tabs = TABS.filter(item => !item.adminOnly || isAdmin);
              const index = tabs.findIndex(item => item.key === t.key);
              const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
                : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
                : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
              if (next < 0) return;
              event.preventDefault();
              document.getElementById(`settings-tab-${tabs[next].key}`)?.focus();
              selectTab(tabs[next].key);
            }}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.key ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
            {t.key === "approvals" && <span aria-label={approvalError ? "Pending count unavailable" : approvals ? `${approvals.pending.length} pending` : "Loading pending count"} className="ml-1.5 inline-flex h-5 min-w-6 items-center justify-center rounded bg-blue-50 px-1 text-xs tabular-nums text-blue-700">
              {approvalError ? "?" : approvals ? approvals.pending.length : "..."}
            </span>}
          </button>
        ))}
      </div>

      {notice && (
        <div className="text-sm px-4 py-3 rounded-lg bg-green-50 text-green-700 border border-green-200">{notice}</div>
      )}
      {error && (
        <div className="text-sm px-4 py-3 rounded-lg bg-red-50 text-red-700 border border-red-200">{error}</div>
      )}
      {dirty && (
        <div className="text-sm px-4 py-2 rounded-lg bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-amber-400" /> You have unsaved changes — remember to Save.
        </div>
      )}

      {approvalTemp && <TemporaryPasswordNotice temp={approvalTemp} onDismiss={() => setApprovalTemp(null)} />}
      <div id="settings-panel" role="tabpanel" aria-labelledby={`settings-tab-${tab}`} tabIndex={0} className="space-y-6">
      {tab === "rules" && isAdmin && <RuleEngineSettings onSubmitted={refreshApprovals} />}
      {tab === "installation" && isAdmin && <InstallationSettings onSubmitted={refreshApprovals} />}
      {tab === "approvals" && isAdmin && <div className="space-y-4">
        <div className="flex justify-end"><RefreshButton loading={approvalLoading} onClick={refreshApprovals} /></div>
        {approvalError && <LoadError message={approvalError} retry={refreshApprovals} />}
        {!approvals && !approvalError && <p role="status" className="text-sm text-gray-500">Loading approvals...</p>}
        {approvals && !approvalError && <ApprovalsSection approvals={approvals} onChanged={refreshApprovals} onTemp={setApprovalTemp} />}
      </div>}
      {tab === "system" && isAdmin && (<>
      {/* Bank database */}
      <Section
        title="Shared Bank Database"
        subtitle="Default read-only connection used by any feed without its own database override"
        badge="Pending Restart"
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
              encrypt: db.encrypt,
              trust_server_certificate: db.trust_server_certificate,
            },
          })
        }
      >
        {/* Connection status */}
        <div className="flex flex-wrap items-center gap-4 mb-4 px-3 py-2 rounded-lg bg-gray-50 border border-gray-100">
          <span className="inline-flex items-center gap-2 text-sm">
            <span className={`w-2.5 h-2.5 rounded-full ${health?.bank_db_connected ? "bg-green-500" : "bg-red-500"}`} />
            <span className="font-medium text-gray-700">{health?.bank_db_connected ? "Connected" : "Disconnected"}</span>
          </span>
          <span className="text-xs text-gray-400">
            Last checked: {health?.last_poll_at ? new Date(health.last_poll_at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" }) : "—"}
          </span>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">Read-only</span>
        </div>

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
              <option value="postgres">PostgreSQL</option>
              <option value="oracle">Oracle</option>
            </select>
          </div>
          <Field label="Host" value={db.host} onChange={(v) => set(["database", "host"], v)} placeholder=". or hostname" />
          <Field label="Port" value={db.port} type="number" onChange={(v) => set(["database", "port"], v)} />
          <Field label="Database" value={db.database} onChange={(v) => set(["database", "database"], v)} />
          <Field label="User" value={db.user} onChange={(v) => set(["database", "user"], v)} hint="Use a read-only DB user" />
          <Field
            label="Password"
            value={db.password ?? ""}
            type="password"
            placeholder={db.password_set ? "•••••••• — stored securely" : "Not set"}
            onChange={(v) => set(["database", "password"], v)}
            hint={db.password_set ? "Stored securely. Leave blank to keep current, or type to change." : "Leave blank if using Windows Authentication."}
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

        {/* Secure connection options */}
        <div className="mt-5 pt-4 border-t border-gray-100">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Secure connection</p>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={!!db.encrypt} onChange={(e) => set(["database", "encrypt"], e.target.checked)} className="rounded border-gray-300" />
              Encrypt connection (TLS)
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={!!db.trust_server_certificate} onChange={(e) => set(["database", "trust_server_certificate"], e.target.checked)} className="rounded border-gray-300" />
              Trust server certificate
            </label>
          </div>
        </div>

        {/* Read-only user banner */}
        <div className="mt-4 px-4 py-3 rounded-lg bg-blue-50 border border-blue-200 text-xs text-blue-800">
          <span className="font-semibold">Use a read-only database user.</span> FMS never writes to your banking
          database — it only reads transactions. A least-privilege (read-only) account limits exposure if credentials
          are ever compromised.
        </div>

        {/* Test connection */}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={testConnection}
            disabled={testing}
            className="text-sm font-medium px-3 py-1.5 rounded-xl border border-gray-200/80 shadow-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {testing ? "Testing…" : "Test Connection"}
          </button>
          {testResult && (
            <span className={`text-sm ${testResult.connected ? "text-green-600" : "text-red-600"}`}>
              {testResult.connected ? "✓ " : "✗ "}{testResult.message}
            </span>
          )}
          <span className="text-xs text-gray-400">Tests the currently saved connection.</span>
        </div>
      </Section>

      {/* Table mappings */}
      <Section
        title="Table Mappings"
        subtitle="Map each feed and optionally connect it to a separate read-only database"
        badge="Pending Restart"
        saving={saving === "tables"}
        onSave={saveTransactionFeeds}
      >
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            {(["inward", "outward"] as const).filter(direction => !tables[direction]).map(direction => (
              <button key={direction} type="button" onClick={() => addTransactionFeed(direction)} className="inline-flex items-center gap-2 rounded-lg border border-blue-200 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50">
                <Plus size={16} />Add {direction} feed
              </button>
            ))}
          </div>
          {Object.keys(tables).length === 0 && <p role="status" className="text-sm text-gray-500">No transaction feeds configured.</p>}
          {Object.entries(tables).map(([key, cfg]: [string, any]) => (
            <div key={key} className="border border-gray-100 rounded-lg p-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div><p className="text-xs font-bold text-gray-600 uppercase tracking-wide">{key} transactions</p>
                  <p className="mt-1 text-xs text-gray-400">Every row from this feed enters the same FMS review engine.</p></div>
                <div className="flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm text-gray-700">
                  <input type="checkbox" checked={!!cfg.database} onChange={(e) => toggleSeparateDatabase(key, e.target.checked)} className="rounded border-gray-300" />
                  Use separate database
                </label>
                <button type="button" onClick={() => removeTransactionFeed(key)} title={`Remove ${key} feed`} aria-label={`Remove ${key} feed`} className="review-icon text-gray-500 hover:text-red-600"><Trash2 size={16} /></button></div>
              </div>
              {cfg.database && <div className="mb-5 border-l-2 border-blue-200 pl-4">
                <p className="mb-3 text-xs font-semibold text-blue-800">{key === "inward" ? "Inward" : "Outward"} feed connection</p>
                <DatabaseConnectionFields db={cfg.database} onSet={(field, value) => set(["tables", key, "database", field], value)} />
              </div>}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <Field
                  label="Table name"
                  value={cfg.table_name ?? ""}
                  onChange={(v) => set(["tables", key, "table_name"], v)}
                />
                {fields.map((f) => (
                  <Field
                    key={f}
                    label={f === "counterparty_account" ? (key === "inward" ? "Sender account" : "Beneficiary account") : f === "counterparty_name" ? (key === "inward" ? "Sender name" : "Beneficiary name") : ["id", "account_id", "amount", "timestamp"].includes(f) ? `${f} (required)` : f}
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
              mode: mon.mode || "poll",
            },
          })
        }
      >
        <div className="mb-4">
          <label className="block text-xs text-gray-500 font-medium mb-1">Ingestion mode</label>
          <select
            value={mon.mode || "poll"}
            onChange={(e) => set(["monitoring", "mode"], e.target.value)}
            className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="api">API push — institutions send transactions to FMS (no DB access)</option>
            <option value="poll">Database poll — FMS reads your core banking DB (in-house / on-prem)</option>
          </select>
          <p className="text-xs text-gray-400 mt-1">
            Both are first-class. <strong>API push</strong> suits partners who won&apos;t share database access (they POST to <code className="font-mono">/ingest/transactions</code>).
            {" "}<strong>Database poll</strong> suits in-house deployments where FMS reads your own core (read-only). Outbound webhooks/callbacks work in either mode.
          </p>
        </div>
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
        subtitle="Machine authentication. Administrator sign-in is required for configuration changes."
        saving={saving === "security"}
        onSave={() => save("security", { security: { fms_api_key: data.security.fms_api_key ?? "" } })}
      >
        <div className="grid grid-cols-2 gap-4">
          <Field
            label={`FMS machine API key ${data.security.api_key_set ? "(set)" : "(not set)"}`}
            value={data.security.fms_api_key ?? ""}
            type="password"
            onChange={(v) => set(["security", "fms_api_key"], v)}
            hint="Takes effect immediately. Machine API keys must stay server-side; do not expose this value in NEXT_PUBLIC_* variables."
          />
        </div>
      </Section>

      {/* System information */}
      <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">System Information</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          <div><p className="text-xs text-gray-400">Application version</p><p className="text-gray-800 font-medium">{sysInfo?.app_version ?? "—"}</p></div>
          <div><p className="text-xs text-gray-400">Environment</p><p className="text-gray-800 font-medium capitalize">{sysInfo?.environment ?? "—"}</p></div>
          <div>
            <p className="text-xs text-gray-400">Database status</p>
            <p className="font-medium inline-flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${sysInfo?.database_connected ? "bg-green-500" : "bg-red-500"}`} />
              <span className="text-gray-800">{sysInfo?.database_connected ? "Connected" : "Disconnected"}</span>
            </p>
          </div>
          <div><p className="text-xs text-gray-400">Audit logging</p><p className="text-gray-800 font-medium">{sysInfo?.audit_logging ? "Enabled" : "Disabled"}</p></div>
          <div><p className="text-xs text-gray-400">Encryption</p><p className="text-gray-800 font-medium">Tokens signed{sysInfo?.encryption?.db_tls ? " · DB TLS on" : " · DB TLS off"}</p></div>
          <div><p className="text-xs text-gray-400">Server time (UTC)</p><p className="text-gray-800 font-medium">{sysInfo?.server_time ? new Date(sysInfo.server_time).toLocaleString("en-GB") : "—"}</p></div>
        </div>
        {sysInfo?.source_connections && Object.keys(sysInfo.source_connections).length > 0 && <div className="mt-4 border-t border-gray-100 pt-4">
          <p className="mb-2 text-xs font-semibold uppercase text-gray-500">Transaction sources</p>
          <div className="flex flex-wrap gap-3">
            {Object.entries(sysInfo.source_connections).map(([source, value]: [string, any]) => <span key={source} className="inline-flex items-center gap-2 text-sm text-gray-700">
              <span className={`h-2 w-2 rounded-full ${value.connected ? "bg-green-500" : "bg-red-500"}`} />
              <span className="capitalize">{source}</span> {value.connected ? "connected" : "disconnected"}
            </span>)}
          </div>
        </div>}
      </section>

      {/* Security best practices */}
      <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Security</h2>
        <ul className="space-y-1.5 text-sm text-gray-600">
          {[
            "User passwords are stored hashed (PBKDF2), never in plain text",
            "The bank database is accessed read-only — FMS never writes to it",
            "Database passwords are never displayed, only stored",
            "Every configuration change is recorded in the Audit Trail",
            "System changes require administrator privileges",
          ].map((t) => (
            <li key={t} className="flex items-start gap-2">
              <svg className="w-4 h-4 text-green-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
              {t}
            </li>
          ))}
        </ul>
      </section>

      {/* Configuration activity log */}
      <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Recent configuration changes</h2>
        <p className="text-xs text-gray-400 mb-4">Who changed what, and when — from the Audit Trail.</p>
        {activity.length === 0 ? (
          <p className="text-sm text-gray-400">No configuration changes recorded yet.</p>
        ) : (
          <ol className="space-y-3">
            {activity.slice(0, 10).map((a) => (
              <li key={a.id} className="text-sm border-b border-gray-50 pb-2 last:border-0">
                <div className="flex justify-between">
                  <span className="font-medium text-gray-800">{a.username}</span>
                  <span className="text-xs text-gray-400">{new Date(a.created_at + "Z").toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })}</span>
                </div>
                {a.detail && <p className="text-xs text-gray-500 mt-0.5 font-mono break-words">{a.detail}</p>}
              </li>
            ))}
          </ol>
        )}
      </section>
      </>)}

      {tab === "account" && <MyAccountSection />}

      {tab === "users" && isAdmin && <UsersSection onChanged={refreshApprovals} />}

      {tab === "directory" && (() => {
        const dir = data.directory ?? {};
        const gmap: Record<string, string> = dir.group_role_map ?? {};
        return (
          <Section
            title="Directory (LDAP / Active Directory)"
            subtitle="Optional single sign-on. When enabled, users authenticate against your directory and are auto-provisioned on first login. Built-in accounts keep working. Applied live"
            saving={saving === "directory"}
            onSave={() => save("directory", { directory: {
              enabled: !!dir.enabled, server_uri: dir.server_uri ?? "", start_tls: !!dir.start_tls,
              bind_user_template: dir.bind_user_template ?? "", base_dn: dir.base_dn ?? "",
              user_search: dir.user_search ?? "(sAMAccountName={username})",
              email_domain: dir.email_domain ?? "", default_role: dir.default_role ?? "viewer",
              group_role_map: gmap,
            } })}
          >
            <label className="flex items-center gap-2 mb-4 text-sm text-gray-700">
              <input type="checkbox" checked={!!dir.enabled} onChange={(e) => set(["directory", "enabled"], e.target.checked)} className="rounded border-gray-300" />
              Enable directory sign-in
            </label>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Server URI" value={dir.server_uri ?? ""} onChange={(v) => set(["directory", "server_uri"], v)} placeholder="ldaps://dc.example.com:636" />
              <Field label="Bind template" value={dir.bind_user_template ?? ""} onChange={(v) => set(["directory", "bind_user_template"], v)} placeholder="{username}@example.com" hint="How a username maps to a bind DN. {username} is substituted." />
              <Field label="Base DN (for group lookup)" value={dir.base_dn ?? ""} onChange={(v) => set(["directory", "base_dn"], v)} placeholder="DC=example,DC=com" />
              <Field label="User search filter" value={dir.user_search ?? ""} onChange={(v) => set(["directory", "user_search"], v)} placeholder="(sAMAccountName={username})" />
              <Field label="Email domain (fallback)" value={dir.email_domain ?? ""} onChange={(v) => set(["directory", "email_domain"], v)} placeholder="example.com" />
              <div>
                <label className="block text-xs text-gray-500 font-medium mb-1">Default role (no group match)</label>
                <select value={dir.default_role ?? "viewer"} onChange={(e) => set(["directory", "default_role"], e.target.value)}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                  {["viewer", "analyst", "admin"].map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>
            <label className="flex items-center gap-2 mt-4 text-sm text-gray-700">
              <input type="checkbox" checked={!!dir.start_tls} onChange={(e) => set(["directory", "start_tls"], e.target.checked)} className="rounded border-gray-300" />
              Use StartTLS (for ldap:// connections)
            </label>

            {/* Group -> role mapping */}
            <div className="mt-5 pt-4 border-t border-gray-100">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Group → role mapping</p>
              <div className="space-y-2">
                {Object.entries(gmap).map(([group, role], i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input value={group} placeholder="AD group name (CN)"
                      onChange={(e) => setData((p: any) => { const n = structuredClone(p); const m = n.directory.group_role_map ?? {}; const v = m[group]; delete m[group]; m[e.target.value] = v; n.directory.group_role_map = m; return n; })}
                      className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    <select value={role}
                      onChange={(e) => setData((p: any) => { const n = structuredClone(p); n.directory.group_role_map = { ...(n.directory.group_role_map ?? {}), [group]: e.target.value }; return n; })}
                      className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white">
                      {["viewer", "analyst", "admin"].map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <button type="button" onClick={() => setData((p: any) => { const n = structuredClone(p); delete n.directory.group_role_map[group]; return n; })}
                      className="text-xs text-gray-400 hover:text-red-600 px-2">Remove</button>
                  </div>
                ))}
                <button type="button" onClick={() => setData((p: any) => { const n = structuredClone(p); n.directory = n.directory ?? {}; n.directory.group_role_map = { ...(n.directory.group_role_map ?? {}), "": "analyst" }; return n; })}
                  className="text-xs text-blue-600 hover:text-blue-800">+ Add mapping</button>
              </div>
            </div>

            <div className="mt-4 flex items-center gap-3">
              <button type="button" disabled={dirTesting}
                onClick={async () => { setDirTesting(true); setDirTest(null); try { setDirTest(await api.testDirectory()); } catch (e) { setDirTest({ connected: false, message: String(e) }); } finally { setDirTesting(false); } }}
                className="text-sm font-medium px-3 py-1.5 rounded-xl border border-gray-200/80 shadow-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">
                {dirTesting ? "Testing…" : "Test Directory Connection"}
              </button>
              {dirTest && <span className={`text-sm ${dirTest.connected ? "text-green-600" : "text-red-600"}`}>{dirTest.connected ? "✓ " : "✗ "}{dirTest.message}</span>}
              <span className="text-xs text-gray-400">Save first, then test the saved settings.</span>
            </div>
          </Section>
        );
      })()}

      {tab === "roles" && <RolesPermissions />}

      {tab === "integrations" && (<>
        <Section
          title="Result Callback"
          subtitle="FMS POSTs verdicts back to your system — case.flagged on detection, case.disposition when an analyst confirms or dismisses. Applied live"
          saving={saving === "integrations"}
          onSave={() =>
            save("integrations", {
              integrations: {
                callback_url: data.integrations?.callback_url ?? "",
                callback_secret: data.integrations?.callback_secret || "",
              },
            })
          }
        >
          <div className="grid grid-cols-2 gap-4">
            <Field
              label="Callback URL"
              value={data.integrations?.callback_url ?? ""}
              placeholder="https://your-system.example.com/fms/events"
              onChange={(v) => set(["integrations", "callback_url"], v)}
              hint="Leave blank to disable outbound delivery."
            />
            <Field
              label={`Signing secret ${data.integrations?.callback_secret_set ? "(set)" : "(not set)"}`}
              value={data.integrations?.callback_secret ?? ""}
              type="password"
              placeholder="Leave blank to keep current"
              onChange={(v) => set(["integrations", "callback_secret"], v)}
              hint="Deliveries are HMAC-SHA256 signed (X-FMS-Signature header) so your system can verify they came from FMS."
            />
          </div>
        </Section>

        <section className="bg-white rounded-xl border border-gray-200/80 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Inbound ingestion</h2>
          <p className="text-sm text-gray-600">
            Your system POSTs each transaction to <code className="font-mono text-xs bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">/ingest/transactions</code> with
            an <code className="font-mono text-xs bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">X-API-Key</code> header and receives the risk verdict in the same response.
          </p>
          <p className="text-xs text-gray-400 mt-2">
            The ingestion key is set on the server as <code className="font-mono">FMS_INGEST_API_KEY</code>. No bank database access is required in API mode (see System → Monitoring).
          </p>
        </section>
      </>)}
      </div>
    </div>
  );
}
