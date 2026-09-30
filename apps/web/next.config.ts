import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // pin the tracing root to this app so Next doesn't infer a workspace
  // parent (the pre-monorepo layout had stray lockfiles at the repo root)
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    // API + SSE live on the FastAPI service in dev and behind the same
    // origin in prod deployments — no CORS in the browser's path.
    const api = process.env.MERIDIAN_API_URL ?? "http://127.0.0.1:8393";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
