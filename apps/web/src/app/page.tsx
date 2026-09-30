"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtVol } from "@/lib/format";
import { useAuth } from "@/auth/AuthContext";
import { useMarketsStream } from "@/hooks/useMarketStream";
import MarketCard from "@/components/MarketCard";
import CreateMarketModal from "@/components/CreateMarketModal";
import type { MarketCardData } from "@/lib/schemas";

function SkeletonGrid() {
  return (
    <div className="markets-grid" aria-busy="true" aria-label="Loading markets">
      {Array.from({ length: 6 }).map((_, i) => (
        <div className="card skel-card" key={i} aria-hidden="true">
          <div className="skel" />
          <div className="skel" />
          <div className="skel" />
          <div className="skel" />
        </div>
      ))}
    </div>
  );
}

export default function Home() {
  const { user, openAuth } = useAuth();
  const [cat, setCat] = useState("All");
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const { data, isLoading } = useQuery({ queryKey: ["markets"], queryFn: api.markets });
  useMarketsStream(true); // live prices on cards + tape

  const markets: MarketCardData[] | undefined = data?.markets;

  /* "/" focuses search from anywhere — keyboard actions skip animation */
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = document.activeElement;
      const typing =
        el instanceof HTMLElement &&
        (el.tagName === "INPUT" ||
          el.tagName === "TEXTAREA" ||
          el.tagName === "SELECT" ||
          el.isContentEditable);
      if (typing) return;
      e.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const cats = useMemo(() => {
    if (!markets) return ["All"];
    return ["All", ...Array.from(new Set(markets.map((m) => m.category)))];
  }, [markets]);

  const filtered = useMemo(() => {
    if (!markets) return [];
    const q = query.trim().toLowerCase();
    return markets.filter((m) => {
      const catOk = cat === "All" || m.category === cat;
      const qOk =
        !q ||
        m.question.toLowerCase().includes(q) ||
        m.category.toLowerCase().includes(q) ||
        m.ticker.toLowerCase().includes(q);
      return catOk && qOk;
    });
  }, [markets, cat, query]);

  const totals = useMemo(() => {
    if (!markets) return null;
    return {
      count: markets.length,
      volume: markets.reduce((s, m) => s + m.volumeCents, 0),
      traders: markets.reduce((s, m) => s + m.traders, 0),
    };
  }, [markets]);

  return (
    <main>
      <section className="hero">
        <div className="wrap">
          <div className="hero-eyebrow">
            <span className="live-dot" aria-hidden="true" />
            <span className="label">
              {totals
                ? `${totals.count} live contracts · ${fmtVol(totals.volume)} traded · ${totals.traders.toLocaleString()} traders`
                : "Loading markets…"}
            </span>
          </div>

          <h1 className="hero-h1">
            Trade on what <span className="grad">happens next.</span>
          </h1>
          <p className="hero-sub">
            Buy Yes or No on elections, economics, crypto, science and
            culture — or open a market of your own. Instant fills, prices
            set by the crowd.
          </p>

          <div className="search-box">
            <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.6" />
              <path d="M10 10l4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='Search markets — try "Fed", "Bitcoin", "Super Bowl"…'
              aria-label="Search markets"
            />
            {query === "" ? (
              <span className="search-kbd" aria-hidden="true">
                /
              </span>
            ) : (
              <button
                className="search-clear"
                onClick={() => {
                  setQuery("");
                  searchRef.current?.focus();
                }}
                aria-label="Clear search"
              >
                <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
                  <path
                    d="M2 2l8 8M10 2l-8 8"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="wrap">
        <div className="section-head">
          <div>
            <h2 className="section-title">Markets</h2>
            <p className="section-sub">Prices in cents · live over SSE · every trade moves the market</p>
          </div>
          <button
            className="btn btn-primary btn-new-market"
            onClick={() => (user ? setShowCreate(true) : openAuth("signup"))}
          >
            + New market
          </button>
        </div>

        <div className="market-toolbar">
          <div className="chips">
            {cats.map((c) => (
              <button
                key={c}
                className={`chip ${cat === c ? "active" : ""}`}
                onClick={() => setCat(c)}
                aria-pressed={cat === c}
              >
                {c}
              </button>
            ))}
          </div>
          {markets && (
            <span className="result-count">
              {filtered.length} market{filtered.length === 1 ? "" : "s"}
            </span>
          )}
        </div>

        {isLoading ? (
          <SkeletonGrid />
        ) : filtered.length > 0 ? (
          <div className="markets-grid">
            {filtered.map((m, i) => (
              <MarketCard key={m.id} market={m} index={i} />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <b>No markets match.</b> Try a different search or category — or
            open the first one yourself.
            {(query !== "" || cat !== "All") && (
              <div className="empty-actions">
                <button
                  className="btn-ghost"
                  onClick={() => {
                    setQuery("");
                    setCat("All");
                  }}
                >
                  Clear search & filters
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      {showCreate && <CreateMarketModal onClose={() => setShowCreate(false)} />}
    </main>
  );
}
