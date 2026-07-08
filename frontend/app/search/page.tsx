"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/api";

interface Hit {
  id: string; account_id: string; amount: number; currency: string; direction: string;
  counterparty_name: string | null; fraud_type: string | null; risk_score: number | null;
  status: string; created_at: string;
}

function money(a: number, c: string) {
  const s = c === "USD" ? "$" : c === "NGN" ? "₦" : c + " ";
  return `${s}${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function SearchResults() {
  const q = useSearchParams().get("q") ?? "";
  const [items, setItems] = useState<Hit[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (q.length < 2) { setLoading(false); return; }
    setLoading(true);
    fetch(`/api/search?q=${encodeURIComponent(q)}`, {
      headers: { Authorization: `Bearer ${auth.token()}` },
    })
      .then((r) => r.json())
      .then((d) => setItems(d.items ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [q]);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Search</h1>
        <p className="text-sm text-gray-500 mt-1">
          {q ? <>Results for <span className="font-medium text-gray-700">&ldquo;{q}&rdquo;</span></> : "Type in the sidebar search box and press Enter."}
        </p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <tbody className={loading ? "opacity-50" : ""}>
            {!loading && items.length === 0 && (
              <tr><td className="text-center py-12 text-gray-400">No matches.</td></tr>
            )}
            {items.map((c) => (
              <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-gray-800">{c.account_id}</td>
                <td className="px-4 py-3 font-semibold whitespace-nowrap">{money(c.amount, c.currency)}</td>
                <td className="px-4 py-3 text-gray-600">{c.counterparty_name ?? "—"}</td>
                <td className="px-4 py-3 text-gray-600">{c.fraud_type ?? "—"}</td>
                <td className="px-4 py-3 text-gray-500">{c.status.replace("_", " ")}</td>
                <td className="px-4 py-3 text-right">
                  <Link href={`/cases/${c.id}`} className="text-blue-600 hover:text-blue-800 text-xs font-medium">View →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-gray-400">Loading…</div>}>
      <SearchResults />
    </Suspense>
  );
}
