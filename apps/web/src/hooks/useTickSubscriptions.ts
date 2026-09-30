"use client";

/* Portfolio terminal live P&L (global SSE tap).
   One EventSource on /api/stream for the whole page; ticks for slugs the
   viewer doesn't hold are dropped before they ever reach state. Prices are
   patched locally — the portfolio query is never refetched per tick. */

import { useEffect, useRef, useState } from "react";
import { TickSchema } from "@/lib/schemas";

export interface LiveTick {
  price: number; // yes price, in cents
  status: string;
  outcome: string | null;
  at: number; // Date.now() of receipt — keys the flash animation
  dir: "up" | "down" | null; // vs the previous tick for this slug
}

export function useTickSubscriptions(slugs: readonly string[] | null) {
  const [ticks, setTicks] = useState<Record<string, LiveTick>>({});
  const held = useRef<ReadonlySet<string>>(new Set());

  /* the held set moves with the data; the connection does not */
  useEffect(() => {
    held.current = new Set(slugs ?? []);
  }, [slugs]);

  const enabled = slugs != null;

  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource("/api/stream");
    const listener = (e: Event) => {
      let raw: unknown;
      try {
        raw = JSON.parse((e as MessageEvent).data);
      } catch {
        return;
      }
      const parsed = TickSchema.safeParse(raw);
      if (!parsed.success) return;
      const t = parsed.data;
      if (!held.current.has(t.slug)) return;
      setTicks((prev) => {
        const before = prev[t.slug];
        const dir =
          before == null || t.price === before.price
            ? null
            : t.price > before.price
              ? "up"
              : "down";
        return {
          ...prev,
          [t.slug]: { price: t.price, status: t.status, outcome: t.outcome, at: Date.now(), dir },
        };
      });
    };
    es.addEventListener("tick", listener);
    return () => {
      es.removeEventListener("tick", listener);
      es.close();
    };
  }, [enabled]);

  return ticks;
}
