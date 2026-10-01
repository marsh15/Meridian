"use client";

/* Live prices over SSE (ADR 0004). One EventSource per surface:
   - useMarketStream(slug): the open market page — patches the detail cache
     with the tick, then refetches for trades/positions consistency.
   - useMarketsStream(): the home page + ticker tape — patches list prices. */

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { TickSchema, type MarketCardData, type MarketDetail, type Tick } from "@meridian/contracts";

function onTick(e: Event, handler: (t: Tick) => void) {
  const parsed = TickSchema.safeParse(JSON.parse((e as MessageEvent).data));
  if (parsed.success) handler(parsed.data);
}

export function useMarketStream(slug: string | null) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!slug) return;
    const es = new EventSource(`/api/markets/${slug}/stream`);
    const listener = (e: Event) =>
      onTick(e, (t) => {
        qc.setQueryData<MarketDetail>(["market", slug], (old) =>
          old ? { ...old, price: t.price, status: t.status, outcome: t.outcome } : old,
        );
        qc.invalidateQueries({ queryKey: ["market", slug] });
        qc.invalidateQueries({ queryKey: ["markets"] });
      });
    es.addEventListener("tick", listener);
    return () => {
      es.removeEventListener("tick", listener);
      es.close();
    };
  }, [slug, qc]);
}

export function useMarketsStream(enabled = true) {
  const qc = useQueryClient();
  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource("/api/stream");
    const listener = (e: Event) =>
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
      });
    es.addEventListener("tick", listener);
    return () => {
      es.removeEventListener("tick", listener);
      es.close();
    };
  }, [enabled, qc]);
}
