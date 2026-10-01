"use client";

import { useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtMoney } from "@/lib/format";
import { idempotencyKey } from "@/lib/safeUrl";
import { useAuth } from "@/auth/AuthContext";
import type { MarketDetail } from "@meridian/contracts";

/* one row per side the user holds */
export default function PositionCard({
  market,
  onDone,
  setToast,
}: {
  market: MarketDetail;
  onDone: () => void;
  setToast: (msg: string, isError?: boolean) => void;
}) {
  const { setBalanceCents } = useAuth();
  const qc = useQueryClient();
  // a double-click fires two handlers before any re-render — the second
  // would race the first and lose loudly. One sell at a time, each with
  // its own idempotency key so retries dedupe server-side.
  const inFlight = useRef(false);
  const pos = market.yourPosition;
  if (!pos) return null;

  const sides = (["yes", "no"] as const)
    .map((side) => ({ side, ...pos[side] }))
    .filter((p) => p.shares > 0.004);
  if (!sides.length) return null;

  const sellAll = async (side: "yes" | "no") => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const res = await api.order(
        market.slug,
        { side, action: "sell", shares: pos[side].shares },
        idempotencyKey(),
      );
      setBalanceCents(res.balanceCents);
      setToast(`Sold ${res.fill.shares} ${side.toUpperCase()} for $${(res.fill.amountCents / 100).toFixed(2)}`);
      qc.invalidateQueries({ queryKey: ["market", market.slug] });
      onDone();
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Request failed", true);
    } finally {
      inFlight.current = false;
    }
  };

  return (
    <div className="card stats-card position-card">
      <div className="label card-label">Your position</div>
      {sides.map(({ side, shares, costCents }) => {
        const price = side === "yes" ? market.price : 100 - market.price;
        const value = Math.round(shares * price);
        const pl = value - costCents;
        return (
          <div className="pos-row" key={side}>
            <div className="pos-main">
              <b className={`pos-side ${side}`}>{side === "yes" ? "YES" : "NO"}</b>
              <span className="pos-shares">{Number(shares.toFixed(2))} sh</span>
            </div>
            <div className="pos-nums">
              <span>avg {costCents > 0 ? `${Math.round(costCents / shares)}¢` : "—"}</span>
              <span>worth {fmtMoney(value)}</span>
              <b className={pl >= 0 ? "up" : "down"}>
                {pl >= 0 ? "+" : "−"}
                {fmtMoney(Math.abs(pl))}
              </b>
            </div>
            {market.status === "open" && (
              <button className="btn-mini" onClick={() => sellAll(side)}>
                Sell all
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
