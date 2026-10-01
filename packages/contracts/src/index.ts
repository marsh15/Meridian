import { z } from "zod";

/* API contract — the single source of truth for what the FastAPI service
   returns. Types are inferred; parsing happens at the client boundary.
   Consumed as a workspace package (@meridian/contracts) so any future JS
   surface (admin console, bots) shares the exact same shapes. */

export const UserSchema = z.object({
  id: z.number(),
  email: z.string(),
  displayName: z.string(),
  balanceCents: z.number(),
});

export const MarketSummarySchema = z.object({
  id: z.string(),
  slug: z.string(),
  ticker: z.string(),
  question: z.string(),
  category: z.string(),
  description: z.string(),
  resolution: z.string(),
  closesAt: z.string(),
  createdAt: z.string(),
  price: z.number(),
  change24h: z.number(),
  status: z.string(),
  outcome: z.string().nullable(),
  volumeCents: z.number(),
  traders: z.number(),
  creatorName: z.string().nullable(),
});

export const MarketCardSchema = MarketSummarySchema.extend({
  history: z.array(z.number()), // flat price list — sparkline fuel
});

export const TradeSchema = z.object({
  id: z.number(),
  trader: z.string(),
  side: z.string(),
  action: z.string(),
  shares: z.number(),
  priceCents: z.number(),
  amountCents: z.number(),
  at: z.string(),
});

export const HolderSchema = z.object({
  trader: z.string(),
  side: z.string(),
  shares: z.number(),
});

export const PositionSideSchema = z.object({
  shares: z.number(),
  costCents: z.number(),
});

export const MarketDetailSchema = MarketSummarySchema.extend({
  history: z.array(z.object({ price: z.number(), at: z.string() })),
  trades: z.array(TradeSchema),
  tradesNextBeforeId: z.number().nullable(),
  historyNextBeforeId: z.number().nullable(),
  holders: z.array(HolderSchema),
  yourPosition: z
    .object({ yes: PositionSideSchema, no: PositionSideSchema })
    .nullable(),
  isCreator: z.boolean(),
  q: z.object({ yes: z.number(), no: z.number() }),
  depth: z.number(),
});

export const HistoryPointSchema = z.object({ price: z.number(), at: z.string() });

export const TradesPageSchema = z.object({
  trades: z.array(TradeSchema),
  nextBeforeId: z.number().nullable(),
});

export const HistoryPageSchema = z.object({
  history: z.array(HistoryPointSchema),
  nextBeforeId: z.number().nullable(),
});

export const CandleSchema = z.object({
  t: z.number(), // epoch seconds — chart time
  o: z.number(),
  h: z.number(),
  l: z.number(),
  c: z.number(),
  v: z.number(),
});

export const CandlesSchema = z.object({
  range: z.string(),
  bucket: z.string(),
  candles: z.array(CandleSchema),
  markers: z.array(z.object({ t: z.number(), kind: z.string() })),
});

export const LeaderboardEntrySchema = z.object({
  id: z.number(),
  trader: z.string(),
  cashCents: z.number(),
  mintedCents: z.number(),
  realizedPnlCents: z.number(),
  volumeCents: z.number(),
});

export const PortfolioPositionSchema = z.object({
  slug: z.string(),
  question: z.string(),
  ticker: z.string(),
  side: z.string(),
  shares: z.number(),
  costCents: z.number(),
  priceCents: z.number(),
  valueCents: z.number(),
  pnlCents: z.number(),
  status: z.string(),
});

export const PortfolioSchema = z.object({
  cashCents: z.number(),
  mintedCents: z.number(),
  realizedPnlCents: z.number(),
  volumeCents: z.number(),
  positionsValueCents: z.number(),
  netWorthCents: z.number(),
  positions: z.array(PortfolioPositionSchema),
});

export const UserProfileSchema = z.object({
  displayName: z.string(),
  joinedAt: z.string(),
  cashCents: z.number(),
  realizedPnlCents: z.number(),
  volumeCents: z.number(),
  tradesCount: z.number(),
});

export const UserProfilePageSchema = z.object({
  user: UserProfileSchema,
  recentTrades: z.array(
    z.object({
      slug: z.string(),
      question: z.string(),
      ticker: z.string(),
      side: z.string(),
      action: z.string(),
      shares: z.number(),
      priceCents: z.number(),
      amountCents: z.number(),
      at: z.string(),
    }),
  ),
  positions: z.array(
    z.object({
      slug: z.string(),
      question: z.string(),
      ticker: z.string(),
      side: z.string(),
      shares: z.number(),
      costCents: z.number(),
      priceCents: z.number(),
      valueCents: z.number(),
      status: z.string(),
    }),
  ),
});

export const TickSchema = z.object({
  type: z.string(),
  slug: z.string(),
  seq: z.number(),
  price: z.number(),
  status: z.string(),
  outcome: z.string().nullable(),
});

export type User = z.infer<typeof UserSchema>;
export type MarketSummary = z.infer<typeof MarketSummarySchema>;
export type MarketCardData = z.infer<typeof MarketCardSchema>;
export type MarketDetail = z.infer<typeof MarketDetailSchema>;
export type Tick = z.infer<typeof TickSchema>;
export type Trade = z.infer<typeof TradeSchema>;
export type HistoryPoint = z.infer<typeof HistoryPointSchema>;
export type Candle = z.infer<typeof CandleSchema>;
export type Candles = z.infer<typeof CandlesSchema>;
export type LeaderboardEntry = z.infer<typeof LeaderboardEntrySchema>;
export type PortfolioPosition = z.infer<typeof PortfolioPositionSchema>;
export type Portfolio = z.infer<typeof PortfolioSchema>;
export type UserProfilePage = z.infer<typeof UserProfilePageSchema>;
