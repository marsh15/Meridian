import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // real pnpm workspace now: the contracts package is TS source, so Next
  // transpiles it, and file tracing roots at the repo (workspace) root.
  // standalone bundles a self-contained server for the deploy image.
  output: "standalone",
  transpilePackages: ["@meridian/contracts"],
  outputFileTracingRoot: path.join(__dirname, "../../"),
  async rewrites() {
    // API + SSE live on the FastAPI service in dev and behind the same
    // origin in prod deployments — no CORS in the browser's path.
    // Evaluated at server start (rewrites is async), which is why the
    // deploy entrypoint exports MERIDIAN_API_URL before node boots.
    const api = process.env.MERIDIAN_API_URL ?? "http://127.0.0.1:8393";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
  async headers() {
    // Next's dev server (HMR, react-refresh) needs eval; production keeps
    // the strict script policy
    const dev = process.env.NODE_ENV === "development";
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          {
            // self for everything; fonts from Google's CDN (layout.tsx);
            // script 'unsafe-inline' because Next hydration injects inline
            // scripts without a nonce in standalone mode
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
              "font-src 'self' https://fonts.gstatic.com",
              "img-src 'self' data:",
              "connect-src 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

export default nextConfig;
