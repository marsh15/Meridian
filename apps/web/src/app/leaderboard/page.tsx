"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtMoney, fmtVol } from "@/lib/format";
import { useAuth } from "@/auth/AuthContext";
import { PageHead, Pnl, TableSkeleton } from "@/components/LedgerBits";

export default function LeaderboardPage() {
  const { user } = useAuth();
  const { data, isLoading } = useQuery({
    queryKey: ["leaderboard"],
    queryFn: () => api.leaderboard(50),
  });

  const rows = data?.leaderboard ?? [];

  return (
    <main className="wrap page">
      <PageHead
        eyebrow="Leaderboard"
        title="The ranking sheet."
        sub="Every account starts with the same $1,000 in play money — here's who has done the most with it."
      />

      {isLoading ? (
        <TableSkeleton rows={8} cols={5} label="Loading leaderboard" />
      ) : rows.length === 0 ? (
        <div className="empty-state">
          <b>No traders on the board yet.</b> Be the first to put points on it.
          <div className="empty-actions">
            <Link className="btn btn-primary" href="/">
              Browse markets
            </Link>
          </div>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="ledger lb-ledger">
            <caption className="vh">Top 50 trader accounts on the exchange</caption>
            <thead>
              <tr>
                <th scope="col" className="rank-col">Rank</th>
                <th scope="col">Trader</th>
                <th scope="col" className="num">Cash</th>
                <th scope="col" className="num">Realized P&amp;L</th>
                <th scope="col" className="num">Volume</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e, i) => {
                const you = !!user && user.displayName === e.trader;
                return (
                  <tr key={e.id} className={you ? "row-you" : undefined}>
                    <td className={`rank${i < 3 ? ` podium-${i + 1}` : ""}`}>{i + 1}</td>
                    <th scope="row" className="ledger-market">
                      <Link
                        className="trader-link"
                        href={`/u/${encodeURIComponent(e.trader)}`}
                      >
                        {e.trader}
                      </Link>
                      {you && (
                        <span className="you-tag">
                          You
                          <span className="vh"> — this is your row</span>
                        </span>
                      )}
                    </th>
                    <td className="num">{fmtMoney(e.cashCents)}</td>
                    <td className="num">
                      <Pnl cents={e.realizedPnlCents} />
                    </td>
                    <td className="num">{fmtVol(e.volumeCents)}</td>
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
