"use client";
import { useEffect, useState } from "react";
import { api, auth } from "@/lib/api";
import type { RulesConfig } from "@/types";

export default function RulesPage() {
  const [cfg, setCfg] = useState<RulesConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const isAdmin = auth.user()?.role === "admin";

  function load() {
    api.getRules().then((c) => {
      setCfg(c);
      setEdit({
        structuring_band_ratio: String(c.detection_parameters.structuring_band_ratio),
        rolling_window_days: String(c.detection_parameters.rolling_window_days),
        smurfing_window_hours: String(c.detection_parameters.smurfing_window_hours),
        sar_ratio: String(c.regulatory_thresholds.sar_ratio_of_ctr),
        usd_ctr: String(c.regulatory_thresholds.ctr_by_currency["USD"] ?? 10000),
      });
    }).catch((e) => setError(String(e)));
  }
  useEffect(load, []);

  async function saveRules() {
    setSaving(true);
    setNotice(null);
    try {
      await api.updateSettings({
        rules: {
          structuring_band_ratio: Number(edit.structuring_band_ratio),
          rolling_window_days: Number(edit.rolling_window_days),
          smurfing_window_hours: Number(edit.smurfing_window_hours),
          sar_ratio: Number(edit.sar_ratio),
          ctr_thresholds: { USD: Number(edit.usd_ctr) },
        },
      });
      setNotice("Saved — applied live to the engine and recorded in the Audit Trail.");
      load();
    } catch (e) {
      setNotice(String(e));
    } finally {
      setSaving(false);
    }
  }

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>;
  if (!cfg) return <div className="p-6 flex items-center justify-center h-64 text-gray-400 text-sm">Loading…</div>;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Rule Engine</h1>
        <p className="text-sm text-gray-500 mt-1">
          The detection engine is fully deterministic and explainable — every flag traces to these rules. No black box.
        </p>
      </div>

      {/* Regulatory thresholds */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Regulatory thresholds</h2>
        <p className="text-xs text-gray-400 mb-4">{cfg.regulatory_thresholds.note}</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(cfg.regulatory_thresholds.ctr_by_currency).map(([cur, val]) => (
            <div key={cur} className="border border-gray-100 rounded-lg p-3">
              <p className="text-xs text-gray-400">{cur} CTR</p>
              <p className="text-sm font-semibold text-gray-900">{val.toLocaleString()}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-500 mt-3">
          SAR threshold = CTR × <span className="font-semibold">{cfg.regulatory_thresholds.sar_ratio_of_ctr}</span>
        </p>
      </section>

      {/* Detection parameters */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Detection windows</h2>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-bold text-gray-900">{Math.round(cfg.detection_parameters.structuring_band_ratio * 100)}%</p>
            <p className="text-xs text-gray-400 mt-1">structuring band (of threshold)</p>
          </div>
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-bold text-gray-900">{cfg.detection_parameters.rolling_window_days}d</p>
            <p className="text-xs text-gray-400 mt-1">velocity window</p>
          </div>
          <div className="border border-gray-100 rounded-lg p-3">
            <p className="text-2xl font-bold text-gray-900">{cfg.detection_parameters.smurfing_window_hours}h</p>
            <p className="text-xs text-gray-400 mt-1">smurfing window</p>
          </div>
        </div>
      </section>

      {/* Scoring components */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Scoring components</h2>
        <div className="space-y-2">
          {cfg.scoring_components.map((c) => (
            <div key={c.name} className="flex items-start gap-3 py-2 border-b border-gray-50 last:border-0">
              <span className={`text-xs font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${c.points.startsWith("-") ? "bg-green-50 text-green-700" : "bg-blue-50 text-blue-700"}`}>
                {c.points}
              </span>
              <div>
                <p className="text-sm font-medium text-gray-800">{c.name}</p>
                <p className="text-xs text-gray-500">{c.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Risk levels + sanctions */}
      <div className="grid md:grid-cols-2 gap-6">
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Risk levels</h2>
          {cfg.risk_levels.map((r) => (
            <div key={r.level} className="flex justify-between text-sm py-1.5 border-b border-gray-50 last:border-0">
              <span className="text-gray-700">{r.level}</span>
              <span className="text-gray-400">{r.range}</span>
            </div>
          ))}
        </section>
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Sanctions screening</h2>
          <p className="text-sm text-gray-700">{cfg.sanctions.list}</p>
          <p className="text-xs text-gray-500 mt-1">Match threshold: {cfg.sanctions.match_threshold}</p>
          <p className="text-xs text-gray-400 mt-2">{cfg.sanctions.note}</p>
        </section>
      </div>

      {/* Admin tuning */}
      {isAdmin && (
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Tune rules</h2>
              <p className="text-xs text-gray-400 mt-0.5">Applied live; every change is audited. Document your rationale per MODEL.md.</p>
            </div>
            <button onClick={saveRules} disabled={saving}
              className="px-4 py-1.5 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50">
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {([
              ["usd_ctr", "USD CTR threshold"],
              ["sar_ratio", "SAR ratio (× CTR)"],
              ["structuring_band_ratio", "Structuring band ratio"],
              ["rolling_window_days", "Velocity window (days)"],
              ["smurfing_window_hours", "Smurfing window (hours)"],
            ] as const).map(([key, label]) => (
              <div key={key}>
                <label className="block text-xs text-gray-500 font-medium mb-1">{label}</label>
                <input type="number" step="any" value={edit[key] ?? ""}
                  onChange={(e) => setEdit((p) => ({ ...p, [key]: e.target.value }))}
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            ))}
          </div>
          {notice && <p className="text-sm mt-3 text-green-700">{notice}</p>}
        </section>
      )}

      <p className="text-xs text-gray-400">
        Parameters are documented with their rationale in MODEL.md. {isAdmin ? "Changes above apply immediately and are recorded in the Audit Trail." : "Ask an administrator to tune thresholds."}
      </p>
    </div>
  );
}
