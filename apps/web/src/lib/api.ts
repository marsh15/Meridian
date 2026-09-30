import {
  MarketCardSchema,
  MarketDetailSchema,
  UserSchema,
  type User,
} from "./schemas";

async function req<T>(path: string, parse: (raw: unknown) => T, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((data as { error?: string }).error || "Request failed");
  return parse(data);
}

const me = (raw: unknown): { user: User | null } => {
  const parsed = UserSchema.nullable().safeParse((raw as { user: unknown }).user);
  return { user: parsed.success ? parsed.data : null };
};

export const api = {
  me: () => req("/api/auth/me", me),
  signup: (body: object) =>
    req("/api/auth/signup", (raw) => me(raw), { method: "POST", body: JSON.stringify(body) }),
  login: (body: object) =>
    req("/api/auth/login", (raw) => me(raw), { method: "POST", body: JSON.stringify(body) }),
  logout: () => req("/api/auth/logout", () => ({ ok: true }), { method: "POST" }),
  resetAccount: () =>
    req("/api/account/reset", (raw) => me(raw), { method: "POST" }),

  markets: () =>
    req("/api/markets", (raw) => ({
      markets: MarketCardSchema.array().parse((raw as { markets: unknown[] }).markets),
    })),
  market: (slug: string) =>
    req(`/api/markets/${slug}`, (raw) => ({
      market: MarketDetailSchema.parse((raw as { market: unknown }).market),
    })),
  createMarket: (body: object) =>
    req("/api/markets", (raw) => raw as { market: { slug: string } }, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  order: (slug: string, body: object) =>
    req(`/api/markets/${slug}/orders`, (raw) => raw, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  resolve: (slug: string, outcome: string) =>
    req(`/api/markets/${slug}/resolve`, (raw) => raw, {
      method: "POST",
      body: JSON.stringify({ outcome }),
    }),
};
