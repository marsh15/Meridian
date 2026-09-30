import { timeAgo, fmtMoney } from '../lib'

export default function RecentTrades({ market }) {
  const trades = market.trades ?? []
  const holders = market.holders ?? []

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
                {t.action === 'buy' ? 'Bought' : 'Sold'} {t.shares}{' '}
                {t.side === 'yes' ? 'YES' : 'NO'}
              </span>
              <span className="tt-meta">
                @ {t.priceCents}¢ · {fmtMoney(t.amountCents)} · {timeAgo(t.at)}
              </span>
              <span className="tt-trader">{t.trader}</span>
            </div>
          ))}
        </div>

        <div className="holders-list">
          <h3>Top holders</h3>
          {holders.length === 0 && <p className="trades-empty">No open positions yet.</p>}
          {holders.map((h, i) => (
            <div className="holder-row" key={i}>
              <span className="ht-name">{h.trader}</span>
              <b className={`ht-side ${h.side}`}>
                {Number(h.shares)} {h.side === 'yes' ? 'YES' : 'NO'}
              </b>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
