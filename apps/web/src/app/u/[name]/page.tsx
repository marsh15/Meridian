"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDate, fmtMoney, fmtVol, timeAgo } from "@/lib/format";
import { Pnl, SideBadge, StatusPill, TableSkeleton } from "@/components/LedgerBits";

export default function TraderPage() {
  const params = useParams<{ name: string }>();
  const raw = params?.name ?? null;

  const name = useMemo(() => {
    if (!raw) return null;
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }, [raw]);

  const { data, error, isLoading } = useQuery({
    queryKey: ["user", name],
    queryFn: () => api.userProfile(name as string),
    enabled: !!name,
    retry: false,
  });

  if (error) {
    return (
      <main className="wrap notfound">
        <h2>Trader not found</h2>
        <p>
          No account goes by &ldquo;{name}&rdquo; — it may have been renamed or
          never existed.
        </p>
        <div className="notfound-actions">
          <Link className="btn btn-primary" href="/leaderboard">
            Back to the leaderboard
          </Link>
          <Link className="btn-ghost" href="/">
            Browse markets
          </Link>
        </div>
      </main>
    );
  }

  if (isLoading || !data) {
    return (
      <main className="wrap page" aria-busy="true" aria-label="Loading trader profile">
        <div className="profile-skel" aria-hidden="true">
          <span className="skel av" />
          <span className="skel l1" />
          <span className="skel l2" />
        </div>
        <TableSkeleton rows={5} cols={6} label="Loading positions" />
      </main>
    );
  }

  const { user: profile, positions, recentTrades } = data;

  return (
    <main className="wrap page">
      <Link href="/leaderboard" className="back-link">
        ← Leaderboard
      </Link>

      <header className="profile-head">
        <span className="profile-avatar" aria-hidden="true">
          {profile.displayName.slice(0, 1).toUpperCase()}
        </span>
        <div>
          <h1 className="profile-name">{profile.displayName}</h1>
          <p className="profile-meta">
            Joined {fmtDate(profile.joinedAt)} ·{" "}
            {profile.tradesCount.toLocaleString()}{" "}
            {profile.tradesCount === 1 ? "trade" : "trades"} traded
          </p>
        </div>
      </header>

      <div className="stat-row">
        <div className="stat">
          <div className="label">Cash</div>
          <b>{fmtMoney(profile.cashCents)}</b>
        </div>
        <div className="stat">
          <div className="label">Realized P&amp;L</div>
          <Pnl cents={profile.realizedPnlCents} />
        </div>
        <div className="stat">
          <div className="label">Volume</div>
          <b>{fmtVol(profile.volumeCents)}</b>
        </div>
      </div>

      <div className="section-head">
        <div>
          <h2 className="section-title">Open positions</h2>
          <p className="section-sub">What this trader is holding right now</p>
        </div>
      </div>

      {positions.length === 0 ? (
        <div className="empty-state flat">
          <b>No open positions.</b> All squared away.
        </div>
      ) : (
        <div className="table-scroll">
          <table className="ledger">
            <caption className="vh">
              Open positions held by {profile.displayName}
            </caption>
            <thead>
              <tr>
                <th scope="col">Market</th>
                <th scope="col">Side</th>
                <th scope="col" className="num">Shares</th>
                <th scope="col" className="num">Price</th>
                <th scope="col" className="num">Value</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
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
                  <td className="num">{p.priceCents}¢</td>
                  <td className="num">{fmtMoney(p.valueCents)}</td>
                  <td>
                    <StatusPill status={p.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="section-head">
        <div>
          <h2 className="section-title">Recent trades</h2>
          <p className="section-sub">The latest fills, as they hit the tape</p>
        </div>
      </div>

      <div className="card about-card trades-card">
        {recentTrades.length === 0 ? (
          <p className="trades-empty">No trades yet — the book is untouched.</p>
        ) : (
          recentTrades.map((t, i) => (
            <div className="trade-row ptrade-row" key={`${t.slug}-${t.at}-${i}`}>
              <span className={`tt-side ${t.side} ${t.action}`}>
                {t.action === "buy" ? "Bought" : "Sold"} {t.shares}{" "}
                {t.side === "yes" ? "YES" : "NO"}
              </span>
              <Link className="ptrade-market" href={`/market/${t.slug}`}>
                {t.question}
              </Link>
              <span className="tt-meta">
                @ {t.priceCents}¢ · {fmtMoney(t.amountCents)} · {timeAgo(t.at)}
              </span>
            </div>
          ))
        )}
      </div>
    </main>
  );
}
