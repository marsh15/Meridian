import {
  BriefPageSchema,
  CandlesSchema,
  CreateMarketResponseSchema,
  ExplanationPageSchema,
  HistoryPageSchema,
  LeaderboardEntrySchema,
  MarketCardSchema,
  MarketDetailSchema,
  OrderResponseSchema,
  PortfolioSchema,
  ResolveResponseSchema,
  TradesPageSchema,
  UserProfilePageSchema,
  UserSchema,
  type Brief,
  type CreateMarketResponse,
  type Explanation,
  type OrderResponse,
  type ResolveResponse,
  type User,
} from "@meridian/contracts";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(
  path: string,
  parse: (raw: unknown) => T,
  opts: RequestInit = {},
): Promise<T> {
  const { headers, ...rest } = opts;
  const res = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: { "Content-Type": "application/json", ...headers },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (data as { error?: string }).error || "Request failed");
  }
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
  marketTrades: (slug: string, beforeId?: number) =>
    req(
      `/api/markets/${slug}/trades${beforeId != null ? `?before_id=${beforeId}` : ""}`,
      (raw) => TradesPageSchema.parse(raw),
    ),
  marketHistory: (slug: string, beforeId?: number) =>
    req(
      `/api/markets/${slug}/history${beforeId != null ? `?before_id=${beforeId}` : ""}`,
      (raw) => HistoryPageSchema.parse(raw),
    ),
  marketCandles: (slug: string, range: string) =>
    req(`/api/markets/${slug}/candles?range=${range}`, (raw) => CandlesSchema.parse(raw)),
  marketBrief: async (slug: string): Promise<Brief | null> => {
    // 404 just means "nothing generated yet" — not an error state
    try {
      return (await req(`/api/markets/${slug}/brief`, (raw) => BriefPageSchema.parse(raw)))
        .brief;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  },
  generateBrief: (slug: string) =>
    req(`/api/markets/${slug}/brief`, (raw) => BriefPageSchema.parse(raw), {
      method: "POST",
    }),
  explainMove: (slug: string, range: string) =>
    req(
      `/api/markets/${slug}/explain?range=${range}`,
      (raw) => ExplanationPageSchema.parse(raw),
    ),
  leaderboard: (limit = 20) =>
    req(`/api/leaderboard?limit=${limit}`, (raw) => ({
      leaderboard: LeaderboardEntrySchema.array().parse(
        (raw as { leaderboard: unknown[] }).leaderboard,
      ),
    })),
  portfolio: () => req("/api/portfolio", (raw) => PortfolioSchema.parse(raw)),
  userProfile: (name: string) =>
    req(`/api/users/${encodeURIComponent(name)}`, (raw) => UserProfilePageSchema.parse(raw)),
  createMarket: (body: object): Promise<CreateMarketResponse> =>
    req("/api/markets", (raw) => CreateMarketResponseSchema.parse(raw), {
      method: "POST",
      body: JSON.stringify(body),
    }),
  order: (slug: string, body: object, idempotencyKey?: string): Promise<OrderResponse> =>
    req(`/api/markets/${slug}/orders`, (raw) => OrderResponseSchema.parse(raw), {
      method: "POST",
      body: JSON.stringify(body),
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    }),
  resolve: (slug: string, outcome: string): Promise<ResolveResponse> =>
    req(`/api/markets/${slug}/resolve`, (raw) => ResolveResponseSchema.parse(raw), {
      method: "POST",
      body: JSON.stringify({ outcome }),
    }),
};
