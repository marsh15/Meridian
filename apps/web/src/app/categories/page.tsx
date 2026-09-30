"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtVol } from "@/lib/format";
import MarketCard from "@/components/MarketCard";
import { GridSkeleton, PageHead } from "@/components/LedgerBits";
import type { MarketCardData } from "@/lib/schemas";

function catId(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

interface CategoryGroup {
  name: string;
  count: number;
  volume: number;
  top: MarketCardData[];
}

export default function CategoriesPage() {
  const { data, isLoading } = useQuery({ queryKey: ["markets"], queryFn: api.markets });
  const markets = data?.markets;

  /* heaviest desks first; each shows its three biggest markets */
  const groups = useMemo<CategoryGroup[] | null>(() => {
    if (!markets) return null;
    const by = new Map<string, MarketCardData[]>();
    for (const m of markets) {
      const arr = by.get(m.category);
      if (arr) arr.push(m);
      else by.set(m.category, [m]);
    }
    return [...by.entries()]
      .map(([name, ms]) => ({
        name,
        count: ms.length,
        volume: ms.reduce((s, m) => s + m.volumeCents, 0),
        top: [...ms].sort((a, b) => b.volumeCents - a.volumeCents).slice(0, 3),
      }))
      .sort((a, b) => b.volume - a.volume);
  }, [markets]);

  const totals = useMemo(() => {
    if (!groups) return null;
    return {
      cats: groups.length,
      markets: groups.reduce((s, g) => s + g.count, 0),
      volume: groups.reduce((s, g) => s + g.volume, 0),
    };
  }, [groups]);

  return (
    <main className="wrap page">
      <PageHead
        eyebrow="Categories"
        title="The index."
        sub={
          totals
            ? `${totals.cats} desks · ${totals.markets} live contracts · ${fmtVol(totals.volume)} traded across the exchange`
            : "Every market on the exchange, filed by desk."
        }
      />

      {isLoading || !groups ? (
        <GridSkeleton label="Loading categories" />
      ) : groups.length === 0 ? (
        <div className="empty-state">
          <b>No markets yet.</b> The board is blank — open the first contract
          yourself.
          <div className="empty-actions">
            <Link className="btn btn-primary" href="/">
              Create a market
            </Link>
          </div>
        </div>
      ) : (
        <>
          <nav className="cat-index" aria-label="Jump to a category">
            {groups.map((g) => (
              <a className="cat-index-link" href={`#${catId(g.name)}`} key={g.name}>
                {g.name}
                <span className="cat-index-count">{g.count}</span>
              </a>
            ))}
          </nav>

          {groups.map((g) => (
            <section
              className="cat-section"
              id={catId(g.name)}
              aria-labelledby={`${catId(g.name)}-h`}
              key={g.name}
            >
              <div className="section-head">
                <div>
                  <h2 className="section-title" id={`${catId(g.name)}-h`}>
                    {g.name}
                  </h2>
                  <p className="section-sub">
                    {g.count} {g.count === 1 ? "market" : "markets"} ·{" "}
                    {fmtVol(g.volume)} traded
                  </p>
                </div>
                <Link className="cat-all" href="/">
                  All {g.count} {g.count === 1 ? "market" : "markets"}
                  <span aria-hidden="true">→</span>
                </Link>
              </div>
              <div className="related-grid cat-grid">
                {g.top.map((m, i) => (
                  <MarketCard key={m.id} market={m} index={i} />
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </main>
  );
}
