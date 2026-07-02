"use client";
import { useState, useEffect } from "react";
import Link from "next/link";

type Direction = "OUTWARD" | "INWARD";
type Stage = "home" | "transfer" | "confirm" | "processing" | "success" | "error";

const CHANNELS = ["MOBILE", "WEB", "USSD", "ATM", "POS"];

interface RecentTxn {
  id: string;
  amount: number;
  currency: string;
  direction: string;
  counterparty_name: string | null;
  created_at: string;
  status: string;
}

function fmtAmt(amount: number, currency = "USD") {
  const symbol = currency === "USD" ? "$" : currency === "NGN" ? "₦" : currency + " ";
  return `${symbol}${amount.toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
}

function fmtDate(ts: string) {
  const d = new Date(ts);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) return `Today, ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function DemoPage() {
  const [stage, setStage] = useState<Stage>("home");
  const [direction, setDirection] = useState<Direction>("OUTWARD");
  const [showBalance, setShowBalance] = useState(true);
  const [error, setError] = useState("");
  const [dots, setDots] = useState(".");
  const [acctError, setAcctError] = useState("");
  const [recentTxns, setRecentTxns] = useState<RecentTxn[]>([]);

  const [form, setForm] = useState({
    account_id: "0123456789",
    amount: "",
    currency: "USD",
    beneficiary_account: "",
    beneficiary_name: "",
    sender_account: "",
    sender_name: "",
    channel: "MOBILE",
    narration: "",
  });

  useEffect(() => {
    if (stage !== "processing") return;
    const id = setInterval(() => setDots(d => d.length >= 3 ? "." : d + "."), 500);
    return () => clearInterval(id);
  }, [stage]);

  // Fetch real recent transactions
  useEffect(() => {
    fetch("/api/cases?limit=5")
      .then(r => r.json())
      .then(d => setRecentTxns(d.items || []))
      .catch(() => {});
  }, [stage]); // re-fetch after a new transaction is submitted

  function set(field: string, value: string) {
    setForm(f => ({ ...f, [field]: value }));
  }

  function handleAcctChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value.replace(/\D/g, "").slice(0, 10);
    set("beneficiary_account", val);
    if (acctError && val.length === 10) setAcctError("");
  }

  function handleAcctBlur() {
    const val = form.beneficiary_account;
    if (!val) return;
    if (val.length !== 10) {
      setAcctError("Must be exactly 10 digits");
      set("beneficiary_name", "");
    } else {
      setAcctError("");
      // Test validation — auto-populate name
      set("beneficiary_name", "Larry Bird");
    }
  }

  async function submit() {
    setStage("processing");
    setError("");
    try {
      const payload = {
        direction,
        account_id: form.account_id,
        amount: parseFloat(form.amount),
        currency: form.currency,
        channel: form.channel,
        narration: form.narration || null,
        reference: `TRF/${Date.now()}`,
        ...(direction === "OUTWARD"
          ? { beneficiary_account: form.beneficiary_account, beneficiary_name: form.beneficiary_name }
          : { sender_account: form.sender_account, sender_name: form.sender_name }),
      };
      const res = await fetch("/api/transactions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      await new Promise(r => setTimeout(r, 2000));
      setStage("success");
    } catch (e) {
      setError(String(e));
      setStage("error");
    }
  }

  function reset() {
    setStage("home");
    setForm(f => ({ ...f, amount: "", beneficiary_account: "", beneficiary_name: "", sender_account: "", sender_name: "", narration: "" }));
    setAcctError("");
  }

  return (
    <div className="h-screen bg-gray-100 flex items-center justify-center overflow-hidden p-2">
      <div
        className="bg-white rounded-[48px] shadow-2xl overflow-hidden relative flex flex-col border-[8px] border-gray-900"
        style={{
          height: "min(844px, calc(100vh - 16px))",
          width: "min(390px, calc((100vh - 16px) * 390 / 844))",
        }}
      >
        {/* Notch */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-28 h-7 bg-gray-900 rounded-b-2xl z-50" />

        {/* ─── HOME ─── */}
        {stage === "home" && (
          <div className="flex flex-col h-full bg-gray-50">
            <div className="bg-[#0A1628] pt-10 pb-6 px-6 rounded-b-[32px]">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white font-bold text-sm">TI</div>
                  <div>
                    <p className="text-gray-400 text-xs">Good day,</p>
                    <p className="text-white font-semibold text-sm">Tochukwu Iloani</p>
                  </div>
                </div>
                <button className="w-9 h-9 rounded-full bg-white/10 flex items-center justify-center">
                  <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                  </svg>
                </button>
              </div>
              <div className="bg-gradient-to-r from-blue-600 to-blue-800 rounded-2xl p-5">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-blue-200 text-xs font-medium">Available Balance</p>
                  <button onClick={() => setShowBalance(b => !b)}>
                    <svg className="w-4 h-4 text-blue-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      {showBalance
                        ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                      }
                    </svg>
                  </button>
                </div>
                <p className="text-white text-2xl font-bold tracking-tight">
                  {showBalance ? "$24,500.00" : "$••••••••"}
                </p>
                <p className="text-blue-200 text-xs mt-1">Acc: 0123456789</p>
              </div>
            </div>

            <div className="px-6 pt-6 flex-1 overflow-y-auto pb-20">
              <p className="text-gray-500 text-xs font-semibold uppercase tracking-wide mb-4">Quick Actions</p>
              <div className="grid grid-cols-4 gap-3 mb-6">
                {[
                  { icon: "↑", label: "Send", action: () => { setDirection("OUTWARD"); setStage("transfer"); } },
                  { icon: "↓", label: "Receive", action: () => { setDirection("INWARD"); setStage("transfer"); } },
                  { icon: "⟳", label: "History", action: () => {} },
                  { icon: "⋯", label: "More", action: () => {} },
                ].map(({ icon, label, action }) => (
                  <button key={label} onClick={action} className="flex flex-col items-center gap-2">
                    <div className="w-14 h-14 rounded-2xl bg-blue-50 flex items-center justify-center text-blue-600 text-xl font-bold shadow-sm hover:bg-blue-100 transition-colors">
                      {icon}
                    </div>
                    <span className="text-gray-600 text-xs font-medium">{label}</span>
                  </button>
                ))}
              </div>

              <p className="text-gray-500 text-xs font-semibold uppercase tracking-wide mb-3">Recent Transactions</p>
              {recentTxns.length === 0 ? (
                <p className="text-gray-400 text-xs text-center py-6">No transactions yet</p>
              ) : (
                recentTxns.map((t) => (
                  <div key={t.id} className="flex items-center gap-3 py-3 border-b border-gray-100">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold ${t.direction === "INWARD" ? "bg-green-100 text-green-600" : "bg-gray-100 text-gray-600"}`}>
                      {(t.counterparty_name || "?")[0].toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-gray-800 text-sm font-medium truncate">{t.counterparty_name || "Unknown"}</p>
                      <p className="text-gray-400 text-xs">{fmtDate(t.created_at)}</p>
                    </div>
                    <p className={`text-sm font-bold shrink-0 ${t.direction === "INWARD" ? "text-green-600" : "text-gray-800"}`}>
                      {t.direction === "INWARD" ? "+" : "-"}{fmtAmt(t.amount, t.currency)}
                    </p>
                  </div>
                ))
              )}
            </div>

            <div className="absolute bottom-0 left-0 right-0 bg-white border-t border-gray-100 flex justify-around px-6 py-3 rounded-b-[40px]">
              {[
                { icon: "⌂", label: "Home", active: true },
                { icon: "↕", label: "Transfer", active: false },
                { icon: "◎", label: "Cards", active: false },
                { icon: "⚙", label: "Settings", active: false },
              ].map(({ icon, label, active }) => (
                <button key={label} className={`flex flex-col items-center gap-1 ${active ? "text-blue-600" : "text-gray-400"}`}>
                  <span className="text-lg">{icon}</span>
                  <span className="text-xs font-medium">{label}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ─── TRANSFER FORM ─── */}
        {stage === "transfer" && (
          <div className="flex flex-col h-full">
            <div className="bg-[#0A1628] pt-10 pb-5 px-6">
              <div className="flex items-center gap-3">
                <button onClick={() => setStage("home")} className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center">
                  <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <h2 className="text-white font-bold text-lg">{direction === "OUTWARD" ? "Send Money" : "Receive Money"}</h2>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto bg-gray-50 px-6 pt-6 pb-8 space-y-5">
              <div className="bg-white rounded-2xl p-5 shadow-sm">
                <p className="text-gray-400 text-xs font-medium mb-3 uppercase tracking-wide">Amount</p>
                <div className="flex items-center gap-2">
                  <span className="text-2xl font-bold text-gray-300">$</span>
                  <input
                    type="number"
                    placeholder="0.00"
                    value={form.amount}
                    onChange={e => set("amount", e.target.value)}
                    className="flex-1 text-2xl font-bold text-gray-900 bg-transparent focus:outline-none placeholder-gray-200"
                  />
                </div>
                <div className="h-px bg-gray-100 mt-3" />
                <p className="text-gray-400 text-xs mt-2">Balance: $24,500.00</p>
              </div>

              <div className="bg-white rounded-2xl p-5 shadow-sm space-y-4">
                <p className="text-gray-400 text-xs font-medium uppercase tracking-wide">
                  {direction === "OUTWARD" ? "Beneficiary Details" : "Sender Details"}
                </p>
                {direction === "OUTWARD" ? (
                  <>
                    <div>
                      <label className="text-xs text-gray-400 mb-1 block">Account Number</label>
                      <input
                        type="text"
                        inputMode="numeric"
                        placeholder="10-digit account number"
                        value={form.beneficiary_account}
                        onChange={handleAcctChange}
                        onBlur={handleAcctBlur}
                        maxLength={10}
                        className={`w-full border rounded-xl px-4 py-3 text-sm text-gray-800 focus:outline-none font-mono ${acctError ? "border-red-400 focus:border-red-500" : "border-gray-200 focus:border-blue-500"}`}
                      />
                      {acctError && <p className="text-red-500 text-xs mt-1">{acctError}</p>}
                      {form.beneficiary_account.length > 0 && !acctError && (
                        <p className="text-gray-400 text-xs mt-1">{form.beneficiary_account.length}/10 digits</p>
                      )}
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 mb-1 block">Account Name</label>
                      <input
                        type="text"
                        placeholder="Enter account number first"
                        value={form.beneficiary_name}
                        onChange={e => set("beneficiary_name", e.target.value)}
                        className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-800 focus:outline-none focus:border-blue-500"
                      />
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="text-xs text-gray-400 mb-1 block">Sender Account</label>
                      <input
                        type="text"
                        inputMode="numeric"
                        placeholder="10-digit account number"
                        value={form.sender_account}
                        onChange={e => set("sender_account", e.target.value.replace(/\D/g, "").slice(0, 10))}
                        maxLength={10}
                        className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-800 focus:outline-none focus:border-blue-500 font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-gray-400 mb-1 block">Sender Name</label>
                      <input type="text" placeholder="Jane Doe" value={form.sender_name}
                        onChange={e => set("sender_name", e.target.value)}
                        className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-800 focus:outline-none focus:border-blue-500" />
                    </div>
                  </>
                )}
              </div>

              <div className="bg-white rounded-2xl p-5 shadow-sm space-y-4">
                <p className="text-gray-400 text-xs font-medium uppercase tracking-wide">Transaction Details</p>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Channel</label>
                  <select value={form.channel} onChange={e => set("channel", e.target.value)}
                    className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-800 focus:outline-none focus:border-blue-500 bg-white">
                    {CHANNELS.map(c => <option key={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-400 mb-1 block">Narration (optional)</label>
                  <input type="text" placeholder="Payment for services" value={form.narration}
                    onChange={e => set("narration", e.target.value)}
                    className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-800 focus:outline-none focus:border-blue-500" />
                </div>
              </div>
            </div>

            <div className="px-6 py-4 bg-white border-t border-gray-100">
              <button
                onClick={() => setStage("confirm")}
                disabled={!form.amount || parseFloat(form.amount) <= 0 || !!acctError}
                className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-gray-200 disabled:text-gray-400 text-white font-bold py-4 rounded-2xl transition-colors text-sm"
              >
                Continue
              </button>
            </div>
          </div>
        )}

        {/* ─── CONFIRM ─── */}
        {stage === "confirm" && (
          <div className="flex flex-col h-full">
            <div className="bg-[#0A1628] pt-10 pb-5 px-6">
              <div className="flex items-center gap-3">
                <button onClick={() => setStage("transfer")} className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center">
                  <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <h2 className="text-white font-bold text-lg">Confirm Transfer</h2>
              </div>
            </div>

            <div className="flex-1 px-6 pt-6 space-y-4 bg-gray-50 overflow-y-auto">
              <div className="bg-white rounded-2xl p-6 shadow-sm text-center">
                <p className="text-gray-400 text-sm mb-1">You are {direction === "OUTWARD" ? "sending" : "receiving"}</p>
                <p className="text-4xl font-bold text-gray-900">{fmtAmt(parseFloat(form.amount) || 0)}</p>
              </div>

              <div className="bg-white rounded-2xl p-5 shadow-sm space-y-3">
                {[
                  { label: "From", value: `Tochukwu Iloani · ${form.account_id}` },
                  { label: direction === "OUTWARD" ? "To" : "From", value: `${direction === "OUTWARD" ? form.beneficiary_name : form.sender_name} · ${direction === "OUTWARD" ? form.beneficiary_account : form.sender_account}` },
                  { label: "Channel", value: form.channel },
                  { label: "Narration", value: form.narration || "—" },
                  { label: "Fee", value: "$0.52" },
                ].map(({ label, value }) => (
                  <div key={label} className="flex justify-between items-start">
                    <span className="text-gray-400 text-sm">{label}</span>
                    <span className="text-gray-800 text-sm font-medium text-right max-w-[200px]">{value}</span>
                  </div>
                ))}
                <div className="h-px bg-gray-100 my-1" />
                <div className="flex justify-between items-center">
                  <span className="text-gray-600 font-semibold text-sm">Total</span>
                  <span className="text-blue-600 font-bold text-sm">{fmtAmt((parseFloat(form.amount) || 0) + 0.52)}</span>
                </div>
              </div>
            </div>

            <div className="px-6 py-4 bg-white border-t border-gray-100 flex gap-3">
              <button onClick={() => setStage("transfer")} className="flex-1 py-4 rounded-2xl border-2 border-gray-200 text-gray-600 font-bold text-sm hover:bg-gray-50">
                Cancel
              </button>
              <button onClick={submit} className="flex-1 py-4 rounded-2xl bg-blue-600 hover:bg-blue-700 text-white font-bold text-sm">
                Send Now
              </button>
            </div>
          </div>
        )}

        {/* ─── PROCESSING ─── */}
        {stage === "processing" && (
          <div className="flex flex-col h-full items-center justify-center bg-white px-8 gap-6">
            <div className="relative w-24 h-24">
              <div className="absolute inset-0 rounded-full border-4 border-blue-100" />
              <div className="absolute inset-0 rounded-full border-4 border-blue-600 border-t-transparent animate-spin" />
              <div className="absolute inset-0 flex items-center justify-center">
                <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              </div>
            </div>
            <div className="text-center">
              <p className="text-gray-900 font-bold text-xl">Processing{dots}</p>
              <p className="text-gray-400 text-sm mt-2">Securely transferring your funds</p>
            </div>
          </div>
        )}

        {/* ─── SUCCESS ─── */}
        {stage === "success" && (
          <div className="flex flex-col h-full bg-white">
            <div className="flex-1 flex flex-col items-center justify-center px-8 gap-5">
              <div className="w-24 h-24 rounded-full bg-green-100 flex items-center justify-center">
                <svg className="w-12 h-12 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <div className="text-center">
                <p className="text-gray-900 font-bold text-2xl">Transfer Successful!</p>
                <p className="text-gray-400 text-sm mt-1">{fmtAmt(parseFloat(form.amount) || 0)} {direction === "OUTWARD" ? "sent" : "received"}</p>
              </div>

              <div className="w-full bg-gray-50 rounded-2xl p-5 space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Reference</span>
                  <span className="text-gray-700 font-mono text-xs">TRF/{Date.now().toString().slice(-8)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">{direction === "OUTWARD" ? "Beneficiary" : "Sender"}</span>
                  <span className="text-gray-700 font-medium">{direction === "OUTWARD" ? form.beneficiary_name : form.sender_name}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Amount</span>
                  <span className="text-gray-900 font-bold">{fmtAmt(parseFloat(form.amount) || 0)}</span>
                </div>
              </div>
            </div>

            <div className="px-6 py-4 border-t border-gray-100">
              <button onClick={reset} className="w-full bg-[#0A1628] hover:bg-[#0d1f38] text-white font-bold py-4 rounded-2xl text-sm">
                New Transaction
              </button>
            </div>
          </div>
        )}

        {/* ─── ERROR ─── */}
        {stage === "error" && (
          <div className="flex flex-col h-full items-center justify-center bg-white px-8 gap-5">
            <div className="w-24 h-24 rounded-full bg-red-100 flex items-center justify-center">
              <svg className="w-12 h-12 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <div className="text-center">
              <p className="text-gray-900 font-bold text-xl">Transaction Failed</p>
              <p className="text-red-400 text-sm mt-2">{error}</p>
            </div>
            <button onClick={() => setStage("confirm")} className="w-full bg-blue-600 text-white font-bold py-4 rounded-2xl text-sm">
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
