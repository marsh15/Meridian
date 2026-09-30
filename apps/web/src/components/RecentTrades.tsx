"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { timeAgo, fmtMoney } from "@/lib/format";
import type { MarketDetail, Trade } from "@/lib/schemas";

export default function RecentTrades({ market }: { market: MarketDetail }) {
  // older pages walked via keyset pagination; the embedded page is the
  // newest window and refreshes with the market query
  const [older, setOlder] = useState<Trade[]>([]);
  const [nextBefore, setNextBefore] = useState<number | null>(market.tradesNextBeforeId);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setOlder([]);
    setNextBefore(market.tradesNextBeforeId);
  }, [market.slug]);

  const trades = useMemo(() => {
    const byId = new Map(older.map((t) => [t.id, t]));
    for (const t of market.trades ?? []) byId.set(t.id, t);
    return [...byId.values()].sort((a, b) => b.id - a.id);
  }, [older, market.trades]);

  const holders = market.holders ?? [];

  async function showMore() {
    if (loading || nextBefore == null) return;
    setLoading(true);
    try {
      const page = await api.marketTrades(market.slug, nextBefore);
      setOlder((prev) => [...prev, ...page.trades]);
      setNextBefore(page.nextBeforeId);
    } catch {
      setNextBefore(null); // stop offering the walk on failure
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card about-card trades-card">
      <div className="trades-cols">
        <div className="trades-list">
          <h3>Recent trades</h3>
          {trades.length === 0 && (
            <p className="trades-empty">No trades yet — be the first.</p>
          )}
          {trades.map((t) => (
            <div className="trade-row" key={t.id}>
              <span className={`tt-side ${t.side} ${t.action}`}>
                {t.action === "buy" ? "Bought" : "Sold"} {t.shares}{" "}
                {t.side === "yes" ? "YES" : "NO"}
              </span>
              <span className="tt-meta">
                @ {t.priceCents}¢ · {fmtMoney(t.amountCents)} · {timeAgo(t.at)}
              </span>
              <span className="tt-trader">{t.trader}</span>
            </div>
          ))}
          {nextBefore != null && (
            <div className="load-more">
              <button className="btn-mini" onClick={showMore} disabled={loading}>
                {loading ? "Loading…" : "Show more"}
              </button>
            </div>
          )}
        </div>

        <div className="holders-list">
          <h3>Top holders</h3>
          {holders.length === 0 && <p className="trades-empty">No open positions yet.</p>}
          {holders.map((h, i) => (
            <div className="holder-row" key={i}>
              <span className="ht-name">{h.trader}</span>
              <b className={`ht-side ${h.side}`}>
                {Number(h.shares)} {h.side === "yes" ? "YES" : "NO"}
              </b>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
