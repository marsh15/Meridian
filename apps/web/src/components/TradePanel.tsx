"use client";

import { useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/auth/AuthContext";
import { api } from "@/lib/api";
import { sharesForDollars, proceedsForShares } from "@/lib/amm";
import { idempotencyKey } from "@/lib/safeUrl";
import { useHotkeys } from "@/hooks/useHotkeys";
import type { MarketDetail } from "@meridian/contracts";

const PRESETS = [10, 50, 100, 250];

export default function TradePanel({
  market,
  onDone,
  setToast,
}: {
  market: MarketDetail;
  onDone: () => void;
  setToast: (msg: string, isError?: boolean) => void;
}) {
  const { user, openAuth, setBalanceCents } = useAuth();
  const qc = useQueryClient();
  const [side, setSide] = useState<"yes" | "no">("yes");
  const [action, setAction] = useState<"buy" | "sell">("buy");
  const [dollars, setDollars] = useState<number | "">(50);
  const [sellShares, setSellShares] = useState<number | "">(0);
  const [busy, setBusy] = useState(false);
  // synchronous guard — a double-click fires two handlers before the busy
  // state re-renders, and each order gets one key so retries dedupe server-side
  const inFlight = useRef(false);

  const tradable = market.status === "open";
  const price = side === "yes" ? market.price : 100 - market.price;
  const owned = market.yourPosition?.[side]?.shares ?? 0;

  /* keyboard trading: B/S flips the action, Y/N the side, Esc resets amounts.
     Checked at event time (not render time) so a dialog opened after render —
     the command palette, auth modal — still swallows the keys. The typing
     guard inside useHotkeys keeps text entry out of this. */
  function unlessDialog(fn: () => void) {
    return () => {
      if (document.querySelector('[role="dialog"]')) return;
      fn();
    };
  }

  useHotkeys(
    {
      b: unlessDialog(() => setAction("buy")),
      s: unlessDialog(() => setAction("sell")),
      y: unlessDialog(() => setSide("yes")),
      n: unlessDialog(() => setSide("no")),
      escape: unlessDialog(() => {
        setDollars(50);
        setSellShares(0);
      }),
    },
    tradable,
  );

  const estimate = useMemo(() => {
    if (!market.q) return null;
    const { yes, no } = market.q;
    if (action === "buy") {
      const d = Number(dollars);
      if (!(d > 0)) return null;
      const shares = sharesForDollars(yes, no, side, d);
      return { shares, avgCents: Math.round((d / shares) * 100), cents: Math.round(d * 100) };
    }
    const s = Number(sellShares);
    if (!(s > 0) || s > owned) return null;
    const proceeds = proceedsForShares(yes, no, side, s);
    return { shares: s, avgCents: Math.round((proceeds / s) * 100), cents: Math.round(proceeds * 100) };
  }, [market.q, action, side, dollars, sellShares, owned]);

  const buyOk =
    action === "buy" &&
    Number(dollars) >= 1 &&
    Number(dollars) <= (user?.balanceCents ?? 0) / 100;
  const sellOk = action === "sell" && Number(sellShares) > 0 && Number(sellShares) <= owned;
  const canSubmit = tradable && !!user && (action === "buy" ? buyOk : sellOk);

  async function submit() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      const body =
        action === "buy"
          ? { side, action, dollarsCents: Math.round(Number(dollars) * 100) }
          : { side, action, shares: Number(sellShares) };
      const res = await api.order(market.slug, body, idempotencyKey());
      setBalanceCents(res.balanceCents);
      setToast(
        `${res.fill.action === "buy" ? "Bought" : "Sold"} ${res.fill.shares} ${side.toUpperCase()} @ ${res.fill.priceCents}¢`,
      );
      setSellShares(0);
      qc.invalidateQueries({ queryKey: ["market", market.slug] });
      qc.invalidateQueries({ queryKey: ["markets"] });
      onDone();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Request failed", true);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="card trade-card">
      <div className="side-toggle">
        <button
          className={`yes ${side === "yes" ? "active" : ""}`}
          onClick={() => setSide("yes")}
          aria-pressed={side === "yes"}
          disabled={!tradable}
        >
          Yes {market.price}¢
        </button>
        <button
          className={`no-side ${side === "no" ? "active" : ""}`}
          onClick={() => setSide("no")}
          aria-pressed={side === "no"}
          disabled={!tradable}
        >
          No {100 - market.price}¢
        </button>
      </div>

      <div
        className={`segmented action-toggle ${action === "sell" ? "alt" : ""}`}
        role="group"
        aria-label="Trade action"
      >
        <span className="seg-thumb" aria-hidden="true" />
        <button
          className={action === "buy" ? "active" : ""}
          onClick={() => setAction("buy")}
          aria-pressed={action === "buy"}
        >
          Buy
        </button>
        <button
          className={action === "sell" ? "active" : ""}
          onClick={() => setAction("sell")}
          aria-pressed={action === "sell"}
        >
          Sell
        </button>
      </div>

      {action === "buy" ? (
        <>
          <div className="amount-label">
            <span className="label">Amount</span>
            {user && <span className="label">Balance ${(user.balanceCents / 100).toFixed(2)}</span>}
          </div>
          <div className="amount-box">
            <span>$</span>
            <input
              type="number"
              min="1"
              step="1"
              value={dollars}
              onChange={(e) => setDollars(e.target.value === "" ? "" : Number(e.target.value))}
              aria-label="Trade amount in dollars"
              disabled={!tradable}
            />
          </div>
          <div className="presets">
            {PRESETS.map((p) => (
              <button
                key={p}
                onClick={() => setDollars(p)}
                type="button"
                className={dollars === p ? "active" : ""}
                aria-pressed={dollars === p}
              >
                ${p}
              </button>
            ))}
            {user && (
              <button
                onClick={() => setDollars(Math.floor(user.balanceCents / 100))}
                type="button"
              >
                Max
              </button>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="amount-label">
            <span className="label">Shares to sell</span>
            <span className="label">You own {Number(owned.toFixed(2))}</span>
          </div>
          <div className="amount-box">
            <input
              type="number"
              min="0"
              step="0.01"
              value={sellShares}
              onChange={(e) => setSellShares(e.target.value === "" ? "" : Number(e.target.value))}
              aria-label="Shares to sell"
              disabled={!tradable}
            />
            <span className="amount-side">{side.toUpperCase()}</span>
          </div>
          <div className="presets">
            {[25, 50, 75].map((pct) => {
              const v = Number(((owned * pct) / 100).toFixed(2));
              return (
                <button
                  key={pct}
                  type="button"
                  className={owned > 0.004 && sellShares === v ? "active" : ""}
                  aria-pressed={owned > 0.004 && sellShares === v}
                  onClick={() => setSellShares(v)}
                >
                  {pct}%
                </button>
              );
            })}
            <button
              type="button"
              className={owned > 0.004 && sellShares === Number(owned.toFixed(2)) ? "active" : ""}
              onClick={() => setSellShares(Number(owned.toFixed(2)))}
            >
              All
            </button>
          </div>
        </>
      )}

      <div className="summary">
        <div className="sum-row">
          <span>{action === "buy" ? "Est. shares" : "Shares"}</span>
          <b>{estimate ? estimate.shares.toFixed(2) : "—"}</b>
        </div>
        <div className="sum-row">
          <span>Est. avg price</span>
          <b>{estimate ? `${estimate.avgCents}¢` : "—"}</b>
        </div>
        <div className="sum-row total">
          <span>{action === "buy" ? "You pay" : "You receive (est.)"}</span>
          <b>
            {estimate ? `$${(estimate.cents / 100).toFixed(2)}` : "—"}
          </b>
        </div>
      </div>

      {!user ? (
        <button className="btn btn-primary btn-block" onClick={() => openAuth("signup")}>
          Sign in to trade
        </button>
      ) : !tradable ? (
        <button className="btn btn-primary btn-block" disabled>
          {market.status === "resolved" ? "Market resolved" : "Market closed"}
        </button>
      ) : (
        <button
          className="btn btn-primary btn-block"
          onClick={submit}
          disabled={!canSubmit || busy}
        >
          {busy
            ? "Filling…"
            : `${action === "buy" ? "Buy" : "Sell"} ${side === "yes" ? "Yes" : "No"}`}
        </button>
      )}

      <p className="fineprint">
        Instant fill at market price · live prices over SSE · play money · $1 per winning share at
        resolution
        <span className="trade-keys">
          Keys: <kbd>B</kbd>/<kbd>S</kbd> buy·sell · <kbd>Y</kbd>/<kbd>N</kbd> side · <kbd>Esc</kbd>{" "}
          reset
        </span>
      </p>
    </div>
  );
}
