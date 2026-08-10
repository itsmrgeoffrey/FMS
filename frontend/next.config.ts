import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8002";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8002/ws";
const isDev = process.env.NODE_ENV !== "production";

// The browser opens the live-feed WebSocket directly to the backend, so its
// origin must be allowed in connect-src. REST goes through the same-origin
// /api proxy ('self'), so the backend's HTTPS origin is not needed here.
let wsOrigin = "";
try {
  const u = new URL(WS_URL);
  wsOrigin = `${u.protocol}//${u.host}`;
} catch {
  // leave empty if unset/invalid
}

const csp = [
  "default-src 'self'",
  // Next.js injects inline bootstrap/hydration scripts, so 'unsafe-inline' is
  // required; 'unsafe-eval' is only needed by the dev server (HMR/Turbopack).
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${wsOrigin ? " " + wsOrigin : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  // Hide the Next.js dev-tools overlay (the "N" route/bundler indicator).
  // Dev-only anyway — it never appears in the production build.
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
