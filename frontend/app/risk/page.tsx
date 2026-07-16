"use client";
import { useEffect, useMemo, useState } from "react";
import { api, auth } from "@/lib/api";
import type { RiskAssessment, RiskAssessmentMeta, RiskCategoryRow, RiskPriorityRow, RiskRating } from "@/types";

const RATINGS: RiskRating[] = ["", "LOW", "MODERATE", "HIGH"];
const RATING_STYLE: Record<string, string> = {
  LOW: "bg-green-50 text-green-700",
  MODERATE: "bg-amber-50 text-amber-700",
  HIGH: "bg-red-50 text-red-700",
};
const COVERAGE_STYLE: Record<string, string> = {
  direct: "bg-green-50 text-green-700",
  partial: "bg-amber-50 text-amber-700",
  screening: "bg-blue-50 text-blue-700",
};

function RatingBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-xs text-gray-400">—</span>;
  return <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${RATING_STYLE[value] ?? "bg-gray-100 text-gray-600"}`}>{value}</span>;
}

export default function RiskPage() {
  const [assessment, setAssessment] = useState<RiskAssessment | null>(null);
  const [versions, setVersions] = useState<RiskAssessmentMeta[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const isAdmin = auth.user()?.role === "admin";
  const editable = isAdmin && assessment?.status === "DRAFT";

  function load() {
    api.getRiskAssessments()
      .then((r) => { setAssessment(r.latest); setVersions(r.versions); })
      .catch((e) => setNotice(String(e)))
      .finally(() => setLoaded(true));
  }
  useEffect(load, []);

  const areas = useMemo(() => {
    const grouped: Record<string, { row: RiskCategoryRow; index: number }[]> = {};
    (assessment?.categories ?? []).forEach((row, index) => {
      (grouped[row.area] ??= []).push({ row, index });
    });
    return grouped;
  }, [assessment?.categories]);

  function patchCategory(index: number, patch: Partial<RiskCategoryRow>) {
    if (!assessment) return;
    const categories = assessment.categories.map((r, i) => (i === index ? { ...r, ...patch } : r));
    setAssessment({ ...assessment, categories });
  }

  function patchPriority(index: number, patch: Partial<RiskPriorityRow>) {
    if (!assessment) return;
    const priorities = assessment.priorities.map((r, i) => (i === index ? { ...r, ...patch } : r));
    setAssessment({ ...assessment, priorities });
  }

  async function act(fn: () => Promise<RiskAssessment>, message: string) {
    setBusy(true);
    setNotice(null);
    try {
      const updated = await fn();
      setAssessment(updated);
      setNotice(message);
      api.getRiskAssessments().then((r) => setVersions(r.versions)).catch(() => {});
    } catch (e) {
      setNotice(String(e));
    } finally {
      setBusy(false);
    }
  }

  const saveDraft = () => assessment && act(
    () => api.updateRiskAssessment(assessment.id, {
      title: assessment.title,
      categories: assessment.categories,
      priorities: assessment.priorities,
      overall_rating: assessment.overall_rating ?? "",
      summary: assessment.summary ?? "",
    }),
    "Draft saved.",
  );

  const finalize = () => assessment && act(
    () => api.finalizeRiskAssessment(assessment.id),
    "Finalized — this version is now the assessment of record.",
  );

  const newDraft = () => act(() => api.createRiskDraft(), "New draft started from the previous version.");
  const refreshSnapshot = () => assessment && act(() => api.refreshRiskSnapshot(assessment.id), "Activity snapshot refreshed.");

  if (!loaded) return <div className="p-6 flex items-center justify-center h-64 text-gray-400 text-sm">Loading…</div>;

  if (!assessment) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-900">Risk Assessment</h1>
        <div className="mt-6 bg-white rounded-lg border border-gray-200 p-8 text-center">
          <p className="text-sm text-gray-600 max-w-xl mx-auto">
            A documented institutional ML/TF risk assessment — covering your products, customers, geographies,
            channels, the FinCEN National AML/CFT Priorities, and the reports you file — is the foundation of a
            risk-based BSA/AML program, and FinCEN&apos;s 2026 Program rule proposal would make it an explicit requirement.
          </p>
          <p className="text-xs text-gray-400 mt-3">
            FMS structures the assessment and pre-fills your activity data. The ratings and judgments are your institution&apos;s — the tool never auto-rates.
          </p>
          {isAdmin ? (
            <button onClick={newDraft} disabled={busy}
              className="mt-6 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50">
              {busy ? "Creating..." : "Start the first assessment"}
            </button>
          ) : (
            <p className="text-sm text-gray-500 mt-6">An administrator starts the first assessment.</p>
          )}
          {notice && <p className="text-sm mt-4 text-amber-700">{notice}</p>}
        </div>
      </div>
    );
  }

  const snap = assessment.activity_snapshot as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {editable ? (
            <input value={assessment.title}
              onChange={(e) => setAssessment({ ...assessment, title: e.target.value })}
              className="text-2xl font-bold text-gray-900 border-b border-transparent hover:border-gray-200 focus:border-blue-400 focus:outline-none bg-transparent w-full max-w-xl" />
          ) : (
            <h1 className="text-2xl font-bold text-gray-900">{assessment.title}</h1>
          )}
          <p className="text-sm text-gray-500 mt-1">
            Version {assessment.version} ·{" "}
            <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${assessment.status === "FINAL" ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
              {assessment.status}
            </span>
            {assessment.status === "FINAL" && assessment.finalized_by && (
              <span className="text-xs text-gray-400"> — finalized by {assessment.finalized_by} on {new Date(assessment.finalized_at + "Z").toLocaleDateString()}</span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {editable && (
            <>
              <button onClick={refreshSnapshot} disabled={busy}
                className="px-3 py-1.5 rounded-lg text-sm font-medium border border-gray-200 text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50">
                Refresh snapshot
              </button>
              <button onClick={saveDraft} disabled={busy}
                className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50">
                {busy ? "Working..." : "Save draft"}
              </button>
              <button onClick={finalize} disabled={busy}
                className="px-4 py-1.5 rounded-lg text-sm font-medium border border-green-200 text-green-700 bg-green-50 hover:bg-green-100 disabled:opacity-50">
                Finalize
              </button>
            </>
          )}
          {isAdmin && assessment.status === "FINAL" && (
            <button onClick={newDraft} disabled={busy}
              className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50">
              Start new version
            </button>
          )}
        </div>
      </div>
      {notice && <p className="text-sm text-green-700">{notice}</p>}

      {/* Activity snapshot */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Activity snapshot (from FMS data)</h2>
        <p className="text-xs text-gray-400 mb-4">
          The &quot;reports filed&quot; consideration — generated {snap.generated_at ? new Date(snap.generated_at + "Z").toLocaleString() : "—"}.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-center">
          {([
            ["Cases", snap.cases_total], ["Flagged", snap.cases_flagged], ["SARs recommended", snap.sar_recommended],
            ["CTRs required", snap.ctr_required], ["Sanctions hits", snap.sanctions_hits], ["Accounts seen", snap.distinct_accounts_seen],
          ] as const).map(([label, value]) => (
            <div key={label} className="border border-gray-100 rounded-lg p-3">
              <p className="text-2xl font-bold text-gray-900">{Number(value ?? 0).toLocaleString()}</p>
              <p className="text-xs text-gray-400 mt-1">{label}</p>
            </div>
          ))}
        </div>
        {Array.isArray(snap.top_typologies) && snap.top_typologies.length > 0 && (
          <p className="text-xs text-gray-500 mt-3">
            Top typologies: {snap.top_typologies.map((t: { type: string; count: number }) => `${t.type} (${t.count})`).join(" · ")}
          </p>
        )}
      </section>

      {/* Category grid */}
      {Object.entries(areas).map(([area, rows]) => (
        <section key={area} className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">{area}</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100">
                  <th className="px-2 py-2 font-medium w-56">Risk factor</th>
                  <th className="px-2 py-2 font-medium w-28">Inherent</th>
                  <th className="px-2 py-2 font-medium">Controls in place</th>
                  <th className="px-2 py-2 font-medium w-28">Residual</th>
                  <th className="px-2 py-2 font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ row, index }) => {
                  const ratingCell = (key: "inherent" | "residual") =>
                    editable ? (
                      <select value={row[key]}
                        onChange={(e) => patchCategory(index, { [key]: e.target.value as RiskRating })}
                        className="text-sm border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500">
                        {RATINGS.map((r) => <option key={r} value={r}>{r || "—"}</option>)}
                      </select>
                    ) : (
                      <RatingBadge value={row[key]} />
                    );
                  const textCell = (key: "controls" | "notes", placeholder?: string) =>
                    editable ? (
                      <input value={row[key]} onChange={(e) => patchCategory(index, { [key]: e.target.value })}
                        placeholder={placeholder}
                        className="w-full text-sm border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    ) : (
                      <span className="text-gray-600 text-xs">{row[key] || "—"}</span>
                    );
                  return (
                    <tr key={index} className="border-b border-gray-50 align-top">
                      <td className="px-2 py-2 text-gray-800">{row.item}</td>
                      <td className="px-2 py-2">{ratingCell("inherent")}</td>
                      <td className="px-2 py-2">{textCell("controls", "e.g. FMS velocity + structuring rules; dual review")}</td>
                      <td className="px-2 py-2">{ratingCell("residual")}</td>
                      <td className="px-2 py-2">{textCell("notes")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      {/* National priorities */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">FinCEN National AML/CFT Priorities</h2>
        <p className="text-xs text-gray-400 mb-4">
          Mark which priorities are relevant to your institution&apos;s risk profile. FMS&apos;s detection coverage for each is shown honestly — &quot;partial&quot; means FMS surfaces the money-movement mechanics and your officer attributes them.
        </p>
        <div className="space-y-3">
          {assessment.priorities.map((p, index) => (
            <div key={p.priority} className="border border-gray-100 rounded-lg p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-gray-800">{p.priority}</p>
                <div className="flex items-center gap-2">
                  <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded uppercase ${COVERAGE_STYLE[p.fms_coverage] ?? "bg-gray-100 text-gray-600"}`}>
                    FMS: {p.fms_coverage}
                  </span>
                  {editable ? (
                    <select value={p.applicable === null ? "" : p.applicable ? "yes" : "no"}
                      onChange={(e) => patchPriority(index, { applicable: e.target.value === "" ? null : e.target.value === "yes" })}
                      className="text-sm border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500">
                      <option value="">Not assessed</option>
                      <option value="yes">Applicable</option>
                      <option value="no">Not applicable</option>
                    </select>
                  ) : (
                    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${p.applicable === null ? "bg-gray-100 text-gray-500" : p.applicable ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-500"}`}>
                      {p.applicable === null ? "Not assessed" : p.applicable ? "Applicable" : "Not applicable"}
                    </span>
                  )}
                </div>
              </div>
              <p className="text-xs text-gray-500 mt-1">{p.fms_how}</p>
              {editable ? (
                <input value={p.notes} onChange={(e) => patchPriority(index, { notes: e.target.value })}
                  placeholder="Relevance to your institution (customers, products, geography)…"
                  className="mt-2 w-full text-sm border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              ) : (
                p.notes && <p className="text-xs text-gray-600 mt-1 italic">{p.notes}</p>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Conclusion */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Overall assessment</h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Overall residual risk:</span>
            {editable ? (
              <select value={assessment.overall_rating ?? ""}
                onChange={(e) => setAssessment({ ...assessment, overall_rating: e.target.value || null })}
                className="text-sm border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500">
                {RATINGS.map((r) => <option key={r} value={r}>{r || "—"}</option>)}
              </select>
            ) : (
              <RatingBadge value={assessment.overall_rating} />
            )}
          </div>
        </div>
        {editable ? (
          <textarea value={assessment.summary ?? ""} rows={4}
            onChange={(e) => setAssessment({ ...assessment, summary: e.target.value })}
            placeholder="The officer's conclusion: overall risk posture, key drivers, planned control changes, and the basis for the overall rating."
            className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
        ) : (
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{assessment.summary || "No conclusion recorded."}</p>
        )}
        <p className="text-[11px] text-gray-400 mt-2">
          The ratings and conclusion are the institution&apos;s judgment. FMS structures the assessment and supplies the activity data; it never auto-rates.
        </p>
      </section>

      {/* Versions */}
      {versions.length > 1 && (
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Version history</h2>
          {versions.map((v) => (
            <div key={v.id} className="flex flex-wrap justify-between gap-2 text-sm py-1.5 border-b border-gray-50 last:border-0">
              <span className="text-gray-700">v{v.version} — {v.title}</span>
              <span className="text-xs text-gray-400">
                {v.status === "FINAL" ? `finalized by ${v.finalized_by} · ${v.finalized_at ? new Date(v.finalized_at + "Z").toLocaleDateString() : ""}` : `draft · started by ${v.created_by}`}
              </span>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
