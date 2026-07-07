"use client";
import { useState } from "react";
import { api, auth } from "@/lib/api";

type Mode = "login" | "signup" | "forgot";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
    setNotice(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "forgot") {
        const res = await api.forgotPassword(email.trim());
        setNotice(
          res.email_configured
            ? res.message
            : `${res.message} (Note: email delivery isn't configured on this server, so no message will actually be sent — an admin can reset your password directly.)`
        );
        return;
      }
      const res =
        mode === "login"
          ? await api.login(email.trim(), password)
          : await api.signup(email.trim(), password, fullName || undefined);
      auth.set(res.token, res.user);
      // Full navigation so the auth gate re-reads the fresh session on a clean mount.
      window.location.assign("/dashboard");
      return;
    } catch (err) {
      const msg = String(err).replace(/^Error:\s*API error \d+:\s*/, "");
      setError(msg.includes("Not authenticated") ? "Invalid email or password" : msg);
    } finally {
      setBusy(false);
    }
  }

  const title = mode === "forgot" ? "Reset password" : mode === "signup" ? "Create account" : "Sign in";

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-slate-900 p-6">
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <p className="text-white font-bold text-2xl tracking-tight">FMS</p>
          <p className="text-slate-400 text-sm mt-1">Fraud Monitoring System</p>
        </div>

        <form onSubmit={submit} className="bg-white rounded-xl p-6 space-y-4 shadow-xl">
          {mode !== "forgot" && (
            <div className="flex rounded-lg bg-gray-100 p-1 text-sm font-medium">
              {(["login", "signup"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => switchMode(m)}
                  className={`flex-1 py-1.5 rounded-md transition-colors ${
                    mode === m ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"
                  }`}
                >
                  {m === "login" ? "Sign in" : "Create account"}
                </button>
              ))}
            </div>
          )}

          {mode === "forgot" && (
            <div>
              <h2 className="text-sm font-semibold text-gray-700">Reset your password</h2>
              <p className="text-xs text-gray-400 mt-1">
                Enter your email and we&apos;ll send a temporary password if an account exists.
              </p>
            </div>
          )}

          {mode === "signup" && (
            <div>
              <label className="block text-xs text-gray-500 font-medium mb-1">Full name</label>
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-gray-500 font-medium mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {mode !== "forgot" && (
            <div>
              <label className="block text-xs text-gray-500 font-medium mb-1">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  required
                  className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 pr-10 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute inset-y-0 right-0 px-3 flex items-center text-gray-400 hover:text-gray-600"
                >
                  {showPassword ? (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
              {mode === "signup" && (
                <p className="text-xs text-gray-400 mt-1">At least 8 characters. The first account created becomes the admin.</p>
              )}
              {mode === "login" && (
                <div className="text-right mt-2">
                  <button
                    type="button"
                    onClick={() => switchMode("forgot")}
                    className="text-xs text-blue-600 hover:text-blue-800"
                  >
                    Forgot password?
                  </button>
                </div>
              )}
            </div>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}
          {notice && <p className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">{notice}</p>}

          <button
            type="submit"
            disabled={busy}
            className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            {busy ? "Please wait..." : title}
          </button>

          {mode === "forgot" && (
            <button
              type="button"
              onClick={() => switchMode("login")}
              className="w-full text-center text-xs text-gray-500 hover:text-gray-700"
            >
              ← Back to sign in
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
