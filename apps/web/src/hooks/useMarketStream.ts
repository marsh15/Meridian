"use client";

/* Live prices over SSE (ADR 0004), all through the shared ref-counted
   connection in lib/sse.ts:
   - useMarketStream(slug): the market page — patches the detail cache with
     each tick; a throttled invalidation refetches trades/positions, and
     candles/brief live on their own query keys so a tick never refetches
     them (per-tick invalidation of the ["market", slug] prefix used to
     refetch 4+ queries on every trade).
   - useMarketsStream(): home page + ticker tape — patches list prices.
   - useStreamLive(): whether the global stream is connected, for the
     "reconnecting" indicator. */

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { TickSchema, type MarketCardData, type MarketDetail, type Tick } from "@meridian/contracts";
import { subscribeStream } from "@/lib/sse";

function onTick(e: Event, handler: (t: Tick) => void) {
  const parsed = TickSchema.safeParse(JSON.parse((e as MessageEvent).data));
  if (parsed.success) handler(parsed.data);
}

const REFETCH_INTERVAL_MS = 2_500;

export function useMarketStream(slug: string | null) {
  const qc = useQueryClient();
  const lastRefetch = useRef(0);
  useEffect(() => {
    if (!slug) return;
    const unsubscribe = subscribeStream(`/api/markets/${slug}/stream`, (e) =>
      onTick(e, (t) => {
        qc.setQueryData<MarketDetail>(["market", slug], (old) =>
          old ? { ...old, price: t.price, status: t.status, outcome: t.outcome } : old,
        );
        // the local patch already painted the price; the refetch that
        // follows (trades, positions, your-position consistency) is
        // throttled so a busy market doesn't refetch per tick
        const now = Date.now();
        if (now - lastRefetch.current < REFETCH_INTERVAL_MS) return;
        lastRefetch.current = now;
        qc.invalidateQueries({ queryKey: ["market", slug] });
        qc.invalidateQueries({ queryKey: ["markets"] });
      }),
    );
    return unsubscribe;
  }, [slug, qc]);
}

export function useMarketsStream(enabled = true) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    return subscribeStream("/api/stream", (e) =>
      onTick(e, (t) => {
        qc.setQueryData<{ markets: MarketCardData[] }>(["markets"], (old) =>
          old
            ? {
                markets: old.markets.map((m) =>
                  m.slug === t.slug ? { ...m, price: t.price, status: t.status } : m,
                ),
              }
            : old,
        );
      }),
    );
  }, [enabled, qc]);
}

export function useStreamLive(): boolean {
  const [live, setLive] = useState(true);
  useEffect(() => subscribeStream("/api/stream", () => {}, setLive), []);
  return live;
}
