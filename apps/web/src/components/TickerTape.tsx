"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useMarketsStream } from "@/hooks/useMarketStream";

export default function TickerTape() {
  const { data } = useQuery({
    queryKey: ["markets"],
    queryFn: api.markets,
    staleTime: 30_000,
  });
  useMarketsStream(true); // prices update live over SSE

  const markets = data?.markets ?? [];
  if (!markets.length) return null;
  const items = [...markets, ...markets];

  return (
    <div className="tape" aria-hidden="true">
      <div className="tape-inner">
        {items.map((m, i) => (
          <span className="tape-item" key={`${m.id}-${i}`}>
            <span className="sym">{m.ticker}</span>
            <span className="px">{m.price}¢</span>
            <span className={`chg ${m.change24h >= 0 ? "up" : "down"}`}>
              {m.change24h >= 0 ? "▲" : "▼"} {Math.abs(m.change24h)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
