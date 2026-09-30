import Link from "next/link";
import { fmtVol, fmtDate } from "@/lib/format";
import type { MarketCardData } from "@/lib/schemas";
import Sparkline from "./Sparkline";

export default function MarketCard({
  market,
  index = 0,
}: {
  market: MarketCardData;
  index?: number;
}) {
  const up = market.change24h >= 0;
  const resolved = market.status === "resolved";

  return (
    <Link
      href={`/market/${market.id}`}
      className={`card market-card ${resolved ? "is-resolved" : ""}`}
      style={{ animationDelay: `${Math.min(index, 10) * 40}ms` }}
    >
      <div className="mc-top">
        <span className="mc-cat">{market.category}</span>
        {resolved ? (
          <span className="badge resolved">
            Resolved {market.outcome === "yes" ? "YES" : "NO"}
          </span>
        ) : (
          <span className={`badge ${up ? "up" : "down"}`}>
            {up ? "▲" : "▼"} {Math.abs(market.change24h)}¢
          </span>
        )}
      </div>

      <div className="mc-mid">
        <h3 className="mc-q">{market.question}</h3>
        {market.history?.length > 1 && <Sparkline history={market.history} />}
      </div>

      <div className="mc-bottom">
        <div className="mini-btns">
          <span className="mini yes">Yes {market.price}¢</span>
          <span className="mini no">No {100 - market.price}¢</span>
        </div>
        <div className="mc-meta">
          <b>{fmtVol(market.volumeCents)}</b> vol
          <br />
          Ends {fmtDate(market.closesAt)}
        </div>
      </div>
    </Link>
  );
}
