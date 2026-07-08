"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/api";
import type { AuthUser } from "@/types";

const ICONS = {
  dashboard: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
  alerts: "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9",
  transactions: "M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4",
  customers: "M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-3.13a4 4 0 10-4-4 4 4 0 004 4zm6 0a4 4 0 00-3-3.87",
  cases: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  rules: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z",
  analytics: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
  reports: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
  audit: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4",
  admin: "M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z",
  demo: "M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z",
};

const NAV_GROUPS: { section: string; requires?: string; items: { href: string; label: string; d: string }[] }[] = [
  { section: "Overview", items: [
    { href: "/dashboard", label: "Dashboard", d: ICONS.dashboard },
    { href: "/analytics", label: "Analytics", d: ICONS.analytics },
  ] },
  { section: "Operations", items: [
    { href: "/alerts", label: "Alerts", d: ICONS.alerts },
    { href: "/transactions", label: "Transactions", d: ICONS.transactions },
    { href: "/customers", label: "Customers", d: ICONS.customers },
    { href: "/cases", label: "Cases", d: ICONS.cases },
  ] },
  { section: "Detection", items: [
    { href: "/rules", label: "Rule Engine", d: ICONS.rules },
  ] },
  { section: "Compliance", items: [
    { href: "/reports", label: "Reports (SAR/STR)", d: ICONS.reports },
    { href: "/audit", label: "Audit Trail", d: ICONS.audit },
  ] },
  { section: "System", requires: "admin", items: [
    { href: "/settings", label: "Administration", d: ICONS.admin },
  ] },
  { section: "Tools", requires: "act", items: [
    { href: "/demo", label: "Simulate (Demo)", d: ICONS.demo },
  ] },
];

const ROLE_CAPS: Record<string, string[]> = {
  admin: ["view", "act", "admin"],
  analyst: ["view", "act"],
  viewer: ["view"],
};
function can(role: string | undefined, cap: string): boolean {
  return (ROLE_CAPS[role ?? ""] ?? []).includes(cap);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const isLogin = pathname === "/login";

  useEffect(() => {
    const u = auth.user();
    setUser(u);
    setReady(true);
    if (!u && !isLogin) router.replace("/login");
  }, [pathname, isLogin, router]);

  // The login page renders standalone (no shell).
  if (isLogin) return <>{children}</>;

  // Avoid flashing the app before the auth check resolves.
  if (!ready || !user) {
    return <div className="min-h-screen flex items-center justify-center text-gray-400 text-sm">Loading…</div>;
  }

  function logout() {
    auth.clear();
    router.replace("/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 bg-slate-900 flex flex-col">
        <div className="px-5 py-5 border-b border-slate-700">
          <p className="text-white font-bold text-lg tracking-tight">FMS</p>
          <p className="text-slate-400 text-xs mt-0.5">Fraud Monitoring System</p>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-3">
          {NAV_GROUPS.filter((g) => !g.requires || can(user.role, g.requires)).map((group) => {
            const isCollapsed = collapsed[group.section];
            return (
              <div key={group.section}>
                <button
                  onClick={() => setCollapsed((c) => ({ ...c, [group.section]: !c[group.section] }))}
                  className="w-full flex items-center justify-between px-3 mb-1 text-[11px] font-bold uppercase tracking-wider text-slate-400 hover:text-slate-200 transition-colors"
                >
                  {group.section}
                  <svg
                    className={`w-3 h-3 transition-transform ${isCollapsed ? "-rotate-90" : ""}`}
                    fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {!isCollapsed && (
                  <div className="space-y-1">
                    {group.items.map((n) => {
                      const active = pathname === n.href || pathname.startsWith(n.href + "/");
                      return (
                        <Link
                          key={n.href}
                          href={n.href}
                          className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                            active ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800 hover:text-white"
                          }`}
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={n.d} />
                          </svg>
                          {n.label}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
        <div className="px-4 py-4 border-t border-slate-700">
          <p className="text-white text-sm font-medium truncate">{user.full_name || user.username}</p>
          <p className="text-slate-400 text-xs capitalize">{user.role}</p>
          {user.role !== "admin" && (
            <Link href="/settings" className="mt-3 block text-xs text-slate-300 hover:text-white transition-colors">
              Account
            </Link>
          )}
          <button
            onClick={logout}
            className="mt-2 w-full text-left text-xs text-slate-300 hover:text-white transition-colors"
          >
            Sign out
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
