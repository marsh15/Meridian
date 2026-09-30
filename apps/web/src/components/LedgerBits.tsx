import type { ReactNode } from "react";
import { fmtMoney } from "@/lib/format";

/* Shared ledger atoms for the portfolio / leaderboard / trader-profile
   pages: masthead, signed P&L figures, YES/NO badges, market status pills
   and the two skeleton shapes every data surface starts as. */

export function PageHead({
  eyebrow,
  title,
  sub,
  aside,
}: {
  eyebrow: string;
  title: ReactNode;
  sub?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-main">
        <span className="label page-eyebrow">{eyebrow}</span>
        <h1 className="page-title">{title}</h1>
        {sub ? <p className="page-sub">{sub}</p> : null}
      </div>
      {aside ? <div className="page-head-aside">{aside}</div> : null}
    </header>
  );
}

export function Pnl({ cents }: { cents: number }) {
  const up = cents >= 0;
  return (
    <b className={`pnl ${up ? "up" : "down"}`}>
      {up ? "+" : "−"}
      {fmtMoney(Math.abs(cents))}
    </b>
  );
}

export function SideBadge({ side }: { side: string }) {
  const yes = side === "yes";
  return <span className={`side-badge ${yes ? "yes" : "no"}`}>{yes ? "YES" : "NO"}</span>;
}

export function StatusPill({ status, outcome }: { status: string; outcome?: string | null }) {
  if (status === "resolved") {
    const yes = outcome === "yes";
    return (
      <span className={`status-pill resolved ${yes ? "yes" : "no"}`}>
        Resolved {yes ? "YES" : "NO"}
      </span>
    );
  }
  if (status === "closed") return <span className="status-pill closed">Closed</span>;
  return <span className="status-pill open">Open</span>;
}

export function TableSkeleton({
  rows = 6,
  cols = 5,
  label = "Loading",
}: {
  rows?: number;
  cols?: number;
  label?: string;
}) {
  return (
    <div className="table-skel" role="status" aria-label={label}>
      {Array.from({ length: rows }).map((_, r) => (
        <div
          className="table-skel-row"
          key={r}
          aria-hidden="true"
          style={{ gridTemplateColumns: `minmax(0, 2.4fr) repeat(${Math.max(cols - 1, 1)}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: cols }).map((_, c) => (
            <span
              className="skel"
              key={c}
              style={{ width: c === 0 ? undefined : `${58 + ((r + c) % 3) * 12}%` }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function GridSkeleton({ count = 6, label = "Loading" }: { count?: number; label?: string }) {
  return (
    <div className="markets-grid" aria-busy="true" aria-label={label}>
      {Array.from({ length: count }).map((_, i) => (
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
