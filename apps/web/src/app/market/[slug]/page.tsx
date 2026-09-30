"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtVol, fmtDate } from "@/lib/format";
import { useAuth } from "@/auth/AuthContext";
import { useMarketStream } from "@/hooks/useMarketStream";
import type { HistoryPoint, MarketDetail } from "@/lib/schemas";
import PriceChart from "@/components/PriceChart";
import TradePanel from "@/components/TradePanel";
import PositionCard from "@/components/PositionCard";
import RecentTrades from "@/components/RecentTrades";
import MarketCard from "@/components/MarketCard";

interface ToastState {
  msg: string;
  isError: boolean;
  closing: boolean;
}

export default function MarketDetail() {
  const params = useParams<{ slug: string }>();
  const slug = params?.slug ?? null;
  const qc = useQueryClient();
  const [status, setStatus] = useState<"loading" | "ready" | "missing">("loading");
  const [toast, setToastState] = useState<ToastState | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data, error } = useQuery({
    queryKey: ["market", slug],
    queryFn: () => api.market(slug as string),
    enabled: !!slug,
    retry: false,
  });
  useMarketStream(slug);

  const { data: list } = useQuery({ queryKey: ["markets"], queryFn: api.markets });
  const market = data?.market;

  useEffect(() => {
    if (error) setStatus("missing");
    else if (market) setStatus("ready");
  }, [error, market]);

  const setToast = useCallback((msg: string, isError = false) => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setToastState({ msg, isError, closing: false });
    closeTimer.current = setTimeout(() => {
      setToastState((t) => (t ? { ...t, closing: true } : null));
    }, 3300);
    hideTimer.current = setTimeout(() => setToastState(null), 3500);
  }, []);

  useEffect(
    () => () => {
      if (hideTimer.current) clearTimeout(hideTimer.current);
      if (closeTimer.current) clearTimeout(closeTimer.current);
    },
    [],
  );

  const onDone = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["market", slug] });
    qc.invalidateQueries({ queryKey: ["markets"] });
  }, [qc, slug]);

  if (status === "missing") {
    return (
      <main className="wrap notfound">
        <h2>Market not found</h2>
        <p>This contract may have expired or never existed.</p>
        <Link className="btn btn-primary" href="/">
          Back to markets
        </Link>
      </main>
    );
  }

  if (!market) {
    return (
      <main className="wrap detail-skel" aria-busy="true" aria-label="Loading market">
        <div className="skel t1" aria-hidden="true" />
        <div className="skel t2" aria-hidden="true" />
        <div className="skel t3" aria-hidden="true" />
        <div className="skel t4" aria-hidden="true" />
      </main>
    );
  }

  const related = (list?.markets ?? [])
    .filter((m) => m.id !== market.id)
    .sort((a, b) =>
      a.category === market.category ? -1 : b.category === market.category ? 1 : 0,
    )
    .slice(0, 3);

  const up = market.change24h >= 0;
  const resolved = market.status === "resolved";
  // status === "closed" is the server's word (sweeper transitioned it);
  // the clock check is a pre-sweep fallback for freshly expired markets
  const closed =
    !resolved &&
    (market.status === "closed" ||
      new Date(market.closesAt).getTime() < Date.now());

  return (
    <main className="detail wrap">
      <Link href="/" className="back-link">
        ← All markets
      </Link>

      {resolved && (
        <div className={`banner ${market.outcome === "yes" ? "up" : "down"}`}>
          <b>Resolved {market.outcome === "yes" ? "YES" : "NO"}.</b>{" "}
          {market.outcome === "yes" ? "YES" : "NO"} shares paid $1 each;
          the other side expired worthless.
        </div>
      )}
      {closed && (
        <div className="banner neutral">
          <b>Closed {fmtDate(market.closesAt)}.</b> Trading is paused —
          awaiting the creator&apos;s resolution.
        </div>
      )}

      <div className="detail-grid">
        <div className="detail-main">
          <div className="detail-head">
            <div className="chips-row">
              <span className="tag">{market.category}</span>
              <span className="tag">{market.ticker}</span>
              <span className="tag">Closes {fmtDate(market.closesAt)}</span>
              {market.creatorName && (
                <span className="tag">by {market.creatorName}</span>
              )}
            </div>
            <h1 className="detail-h1">{market.question}</h1>

            <div className="stat-row">
              <div className="stat">
                <div className="label">Yes price</div>
                <b>{market.price}¢</b>
              </div>
              <div className="stat">
                <div className="label">24h change</div>
                <b className={up ? "up" : "down"}>
                  {up ? "▲" : "▼"} {Math.abs(market.change24h)}¢
                </b>
              </div>
              <div className="stat">
                <div className="label">Volume</div>
                <b>{fmtVol(market.volumeCents)}</b>
              </div>
              <div className="stat">
                <div className="label">Traders</div>
                <b>{market.traders.toLocaleString()}</b>
              </div>
            </div>
          </div>

          <ChartCard market={market} />

          <div className="card about-card">
            <h3>About this market</h3>
            {market.description ? (
              <p>{market.description}</p>
            ) : (
              <p className="muted">No description provided.</p>
            )}
            {market.resolution && (
              <p className="res">
                <b>Resolution:</b> {market.resolution}
              </p>
            )}
          </div>

          <RecentTrades market={market} />

          {related.length > 0 && (
            <>
              <h2 className="section-title">Related markets</h2>
              <div className="related-grid">
                {related.map((m, i) => (
                  <MarketCard key={m.id} market={m} index={i} />
                ))}
              </div>
            </>
          )}
        </div>

        <aside className="side-panel">
          <TradePanel market={market} onDone={onDone} setToast={setToast} />
          <PositionCard market={market} onDone={onDone} setToast={setToast} />
          {market.isCreator && !resolved && (
            <ResolveCard slug={market.slug} onDone={onDone} setToast={setToast} />
          )}
          <div className="card stats-card">
            <div className="stat-line">
              <span>Market ID</span>
              <b>{market.ticker}</b>
            </div>
            <div className="stat-line">
              <span>Created</span>
              <b>{fmtDate(market.createdAt)}</b>
            </div>
            <div className="stat-line">
              <span>Mechanism</span>
              <b>Instant fill · AMM</b>
            </div>
            <div className="stat-line">
              <span>Fee</span>
              <b>None (demo)</b>
            </div>
          </div>
        </aside>
      </div>

      {toast && (
        <div
          className={`toast ${toast.isError ? "error" : ""} ${toast.closing ? "closing" : ""}`}
          role={toast.isError ? "alert" : "status"}
        >
          {toast.msg}
        </div>
      )}
    </main>
  );
}

function ChartCard({ market }: { market: MarketDetail }) {
  // price history is paginated newest-window-first; "Show earlier" walks
  // backwards through keyset pages and prepends to the chart
  const [older, setOlder] = useState<HistoryPoint[]>([]);
  const [nextBefore, setNextBefore] = useState<number | null>(market.historyNextBeforeId);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setOlder([]);
    setNextBefore(market.historyNextBeforeId);
  }, [market.slug]);

  const history = useMemo(() => {
    const byAt = new Map(older.map((h) => [h.at, h]));
    for (const h of market.history ?? []) byAt.set(h.at, h);
    return [...byAt.values()].sort((a, b) => a.at.localeCompare(b.at));
  }, [older, market.history]);

  async function showEarlier() {
    if (loading || nextBefore == null) return;
    setLoading(true);
    try {
      const page = await api.marketHistory(market.slug, nextBefore);
      setOlder((prev) => [...prev, ...page.history]);
      setNextBefore(page.nextBeforeId);
    } catch {
      setNextBefore(null); // stop offering the walk on failure
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card chart-card">
      <div className="chart-head">
        <span className="chart-title">Yes price · history</span>
        <span className="chart-range">
          {fmtDate(history[0]?.at || market.createdAt)} —{" "}
          {fmtDate(history[history.length - 1]?.at || market.closesAt)}
        </span>
      </div>
      <PriceChart history={history} />
      {nextBefore != null && (
        <div className="load-more">
          <button className="btn-mini" onClick={showEarlier} disabled={loading}>
            {loading ? "Loading…" : "Show earlier"}
          </button>
        </div>
      )}
    </div>
  );
}

function ResolveCard({
  slug,
  onDone,
  setToast,
}: {
  slug: string;
  onDone: () => void;
  setToast: (msg: string, isError?: boolean) => void;
}) {
  const [confirming, setConfirming] = useState<"yes" | "no" | null>(null);
  const { refreshUser } = useAuth();

  async function resolve(outcome: "yes" | "no") {
    try {
      await api.resolve(slug, outcome);
      setToast(`Market resolved ${outcome.toUpperCase()}`);
      await refreshUser();
      onDone();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Request failed", true);
    }
  }

  return (
    <div className="card stats-card resolve-card">
      <div className="label card-label">Creator tools</div>
      {confirming ? (
        <>
          <p className="resolve-q">
            Pay $1 per <b>{confirming === "yes" ? "YES" : "NO"}</b> share and
            close this market?
          </p>
          <div className="resolve-btns">
            <button className="btn-mini yes" onClick={() => resolve(confirming)}>
              Confirm {confirming === "yes" ? "YES" : "NO"}
            </button>
            <button className="btn-mini" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <div className="resolve-btns">
          <button className="btn-mini yes" onClick={() => setConfirming("yes")}>
            Resolve YES
          </button>
          <button className="btn-mini no" onClick={() => setConfirming("no")}>
            Resolve NO
          </button>
        </div>
      )}
    </div>
  );
}
