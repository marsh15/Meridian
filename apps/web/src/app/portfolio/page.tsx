"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { useAuth } from "@/auth/AuthContext";
import { useTickSubscriptions } from "@/hooks/useTickSubscriptions";
import { PageHead, Pnl, SideBadge, StatusPill, TableSkeleton } from "@/components/LedgerBits";

/* One live row per held slug+side — everything the tick moves, precomputed */
interface LiveView {
  price: number;
  value: number;
  pnl: number;
  status: string;
  outcome: string | null;
  flash: "up" | "down" | null;
  tickAt: number;
}

export default function PortfolioPage() {
  const { user, ready, openAuth } = useAuth();

  const { data, error, refetch } = useQuery({
    queryKey: ["portfolio"],
    queryFn: api.portfolio,
    enabled: !!user,
  });

  const positions = data?.positions;
  const slugs = useMemo(
    () => (positions ? Array.from(new Set(positions.map((p) => p.slug))) : null),
    [positions],
  );
  const ticks = useTickSubscriptions(slugs);

  /* local patch: mark every held row to the tick's yes price — NO shares
     price off the other side of the book */
  const live = useMemo(() => {
    const map = new Map<string, LiveView>();
    for (const p of positions ?? []) {
      const t = ticks[p.slug];
      if (!t) continue;
      const price = p.side === "yes" ? t.price : 100 - t.price;
      const value = Math.round(p.shares * price);
      const flash = t.dir && p.side === "no" ? (t.dir === "up" ? "down" : "up") : t.dir;
      map.set(`${p.slug}:${p.side}`, {
        price,
        value,
        pnl: value - p.costCents,
        status: t.status,
        outcome: t.outcome,
        flash,
        tickAt: t.at,
      });
    }
    return map;
  }, [positions, ticks]);

  const positionsValue = useMemo(
    () =>
      (positions ?? []).reduce(
        (s, p) => s + (live.get(`${p.slug}:${p.side}`)?.value ?? p.valueCents),
        0,
      ),
    [positions, live],
  );

  const netWorth = data ? data.cashCents + positionsValue : 0;

  /* net worth flashes with each tick — direction vs the previous render */
  const [netFlash, setNetFlash] = useState<"up" | "down" | null>(null);
  const prevNet = useRef<number | null>(null);
  useEffect(() => {
    if (!data) return; // don't prime the tracker with the skeleton's 0
    const prev = prevNet.current;
    prevNet.current = netWorth;
    if (prev == null || prev === netWorth) return;
    setNetFlash(netWorth > prev ? "up" : "down");
    const t = setTimeout(() => setNetFlash(null), 1200);
    return () => clearTimeout(t);
  }, [netWorth, data]);

  /* auth gate — the terminal is meaningless without a book */
  if (ready && !user) {
    return (
      <main className="wrap page">
        <div className="auth-gate">
          <span className="label">Portfolio · the terminal</span>
          <h1 className="auth-gate-title">Your book is one sign-in away.</h1>
          <p className="auth-gate-copy">
            Track live P&amp;L across every market you hold — positions mark
            themselves to the last trade as it happens.
          </p>
          <div className="auth-gate-actions">
            <button className="btn btn-primary" onClick={() => openAuth("login")}>
              Sign in
            </button>
            <Link className="btn-ghost" href="/">
              Browse markets
            </Link>
          </div>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="wrap page">
        <div className="empty-state">
          <b>Couldn&apos;t load your book.</b> The exchange didn&apos;t answer.
          <div className="empty-actions">
            <button className="btn-ghost" onClick={() => refetch()}>
              Try again
            </button>
          </div>
        </div>
      </main>
    );
  }

  if (!ready || !data) {
    return (
      <main className="wrap page" aria-busy="true" aria-label="Loading portfolio">
        <PageHead eyebrow="Portfolio · the terminal" title="Your book." />
        <div className="stat-skel" aria-hidden="true">
          <span className="skel" />
          <span className="skel" />
          <span className="skel" />
          <span className="skel" />
        </div>
        <TableSkeleton rows={6} cols={7} label="Loading positions" />
      </main>
    );
  }

  const rows = [...data.positions].sort((a, b) => b.valueCents - a.valueCents);

  return (
    <main className="wrap page">
      <PageHead
        eyebrow="Portfolio · the terminal"
        title="Your book."
        sub="Every position marked to the last trade — prices stream in live over SSE, nothing here waits on a refresh."
      />

      <div className="stat-row">
        <div className="stat">
          <div className="label">Net worth</div>
          <b className={netFlash ? `nw-flash ${netFlash}` : undefined}>{fmtMoney(netWorth)}</b>
        </div>
        <div className="stat">
          <div className="label">Cash</div>
          <b>{fmtMoney(data.cashCents)}</b>
        </div>
        <div className="stat">
          <div className="label">Positions value</div>
          <b>{fmtMoney(positionsValue)}</b>
        </div>
        <div className="stat">
          <div className="label">Realized P&amp;L</div>
          <Pnl cents={data.realizedPnlCents} />
        </div>
      </div>

      <div className="section-head">
        <div>
          <h2 className="section-title">Positions</h2>
          <p className="section-sub">
            Sizes, cost basis and cash settled by the exchange — price, value
            and P&amp;L move with the tape
          </p>
        </div>
        {rows.length > 0 && (
          <span className="live-pill">
            <span className="live-dot" aria-hidden="true" />
            Live prices
          </span>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="empty-state">
          <b>No open positions.</b> Your cash is waiting for a conviction —
          pick a side on any market and it will show up here instantly.
          <div className="empty-actions">
            <Link className="btn btn-primary" href="/">
              Browse markets
            </Link>
          </div>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="ledger">
            <caption className="vh">Your open positions, marked to market</caption>
            <thead>
              <tr>
                <th scope="col">Market</th>
                <th scope="col">Side</th>
                <th scope="col" className="num">Shares</th>
                <th scope="col" className="num hide-sm">Cost</th>
                <th scope="col" className="num">Price</th>
                <th scope="col" className="num">Value</th>
                <th scope="col" className="num">P&amp;L</th>
                <th scope="col" className="hide-sm">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const l = live.get(`${p.slug}:${p.side}`);
                return (
                  <tr key={`${p.slug}-${p.side}`}>
                    <th scope="row" className="ledger-market">
                      <Link className="ledger-market-link" href={`/market/${p.slug}`}>
                        {p.question}
                      </Link>
                      <span className="ledger-ticker">{p.ticker}</span>
                    </th>
                    <td>
                      <SideBadge side={p.side} />
                    </td>
                    <td className="num">{Number(p.shares.toFixed(2))}</td>
                    <td className="num hide-sm">{fmtMoney(p.costCents)}</td>
                    <td className="num">
                      <span
                        className={l?.flash ? `tick-flash ${l.flash}` : undefined}
                        key={l ? l.tickAt : "base"}
                      >
                        {(l?.price ?? p.priceCents)}¢
                      </span>
                    </td>
                    <td className="num">{fmtMoney(l?.value ?? p.valueCents)}</td>
                    <td className="num">
                      <Pnl cents={l?.pnl ?? p.pnlCents} />
                    </td>
                    <td className="hide-sm">
                      <StatusPill status={l?.status ?? p.status} outcome={l?.outcome} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
