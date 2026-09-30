import { z } from "zod";

/* API contract — the single source of truth for what the FastAPI service
   returns. Types are inferred; parsing happens at the client boundary. */

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
