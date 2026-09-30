import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // multiple lockfiles exist in this repo's history; pin the root so Next
  // doesn't infer the wrong workspace
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    // API + SSE live on the FastAPI service in dev and behind the same
    // origin in prod deployments — no CORS in the browser's path.
    const api = process.env.MERIDIAN_API_URL ?? "http://127.0.0.1:8393";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
