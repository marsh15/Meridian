// k6 load profile for the order path (phase 5).
//
//   docker run --rm -v "$PWD/load:/load" \
//     -e BASE=http://host.docker.internal:8393 -e USERS=40 -e DURATION=45s \
//     grafana/k6:1.0.0 run /load/order-path.js      (or: make load)
//
// Shape: 40 traders each pace one order every ~3s (fits the real
// 30-orders/min/user limit — the limiter itself is covered by pytest), and
// 8 readers hammer the hot GETs so the Redis markets cache has to earn its
// keep. Run against a plain dev stack; signup rate limits only matter for
// the bulk setup, which needs AUTH_REQUESTS_PER_MINUTE raised on the API
// under test (40 signups from one IP):
//   AUTH_REQUESTS_PER_MINUTE=600 uv run uvicorn app.main:app --port 8394

import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE || "http://localhost:8393";
const USERS = Number(__ENV.USERS || 40);
const DURATION = __ENV.DURATION || "45s";

export const options = {
  scenarios: {
    traders: {
      executor: "constant-vus",
      exec: "trade",
      vus: USERS,
      duration: DURATION,
    },
    readers: {
      executor: "constant-vus",
      exec: "read",
      vus: 8,
      duration: DURATION,
      startTime: "0s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.02"],
    // per-market orders serialize on the market row lock (LMSR correctness);
    // p95 here is dominated by queue depth, not engine time — matching
    // p50/p95 (lock→commit) live on the Grafana order-pipeline dashboard
    "http_req_duration{name:order}": ["p(95)<3000"],
    "http_req_duration{name:markets-list}": ["p(95)<250"],
  },
};

export function setup() {
  const users = [];
  for (let i = 0; i < USERS; i++) {
    const res = http.post(
      `${BASE}/api/auth/signup`,
      JSON.stringify({
        email: `k6-${__ENV.RUN || "run"}-${i}@load.test`,
        password: "loadtest1",
        displayName: `K6 Trader ${i}`,
      }),
      { headers: { "Content-Type": "application/json" } },
    );
    check(res, { "signup ok": (r) => r.status === 200 });
    const jar = res.cookies["meridian_session"];
    if (!jar || !jar.length) throw new Error(`signup ${i} returned no session`);
    users.push(jar[0].value);
  }
  const markets = http
    .get(`${BASE}/api/markets`)
    .json()
    .markets.filter((m) => m.status === "open")
    .map((m) => m.slug);
  if (!markets.length) throw new Error("no open markets to trade");
  return { users, markets };
}

export function trade(data) {
  const cookie = data.users[(__VU - 1) % data.users.length];
  const slug = data.markets[Math.floor(Math.random() * data.markets.length)];
  const side = Math.random() < 0.5 ? "yes" : "no";
  const amount = 200 + Math.floor(Math.random() * 600);

  const res = http.post(
    `${BASE}/api/markets/${slug}/orders`,
    JSON.stringify({ side, action: "buy", dollarsCents: amount }),
    {
      headers: {
        "Content-Type": "application/json",
        Cookie: `meridian_session=${cookie}`,
        "Idempotency-Key": `k6-${__VU}-${__ITER}-${__ENV.RUN || "r"}`,
      },
      tags: { name: "order" },
    },
  );
  check(res, { "order filled": (r) => r.status === 200 });

  sleep(2.5 + Math.random() * 1.5);
}

export function read(data) {
  http.get(`${BASE}/api/markets`, { tags: { name: "markets-list" } });
  const slug = data.markets[Math.floor(Math.random() * data.markets.length)];
  http.get(`${BASE}/api/markets/${slug}`, { tags: { name: "market-detail" } });
  http.get(`${BASE}/api/markets/${slug}/candles?range=1d`, {
    tags: { name: "candles" },
  });
  sleep(0.1);
}
