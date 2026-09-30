import { api } from '../api'
import { fmtMoney } from '../lib'
import { useAuth } from '../auth/AuthContext'

/* one row per side the user holds */
export default function PositionCard({ market, onDone, setToast }) {
  const { setBalanceCents } = useAuth()
  const pos = market.yourPosition
  if (!pos) return null

  const sides = ['yes', 'no']
    .map((side) => ({ side, ...pos[side] }))
    .filter((p) => p.shares > 0.004)
  if (!sides.length) return null

  async function sellAll(side) {
    try {
      const res = await api.order(market.slug, {
        side,
        action: 'sell',
        shares: pos[side].shares,
      })
      setBalanceCents(res.balanceCents)
      setToast(`Sold ${res.fill.shares} ${side.toUpperCase()} for $${(res.fill.amountCents / 100).toFixed(2)}`)
      onDone(res)
    } catch (err) {
      setToast(err.message, true)
    }
  }

  return (
    <div className="card stats-card position-card">
      <div className="label card-label">Your position</div>
      {sides.map(({ side, shares, costCents }) => {
        const price = side === 'yes' ? market.price : 100 - market.price
        const value = Math.round(shares * price)
        const pl = value - costCents
        return (
          <div className="pos-row" key={side}>
            <div className="pos-main">
              <b className={`pos-side ${side}`}>{side === 'yes' ? 'YES' : 'NO'}</b>
              <span className="pos-shares">{Number(shares.toFixed(2))} sh</span>
            </div>
            <div className="pos-nums">
              <span>avg {costCents > 0 ? `${Math.round(costCents / shares)}¢` : '—'}</span>
              <span>worth {fmtMoney(value)}</span>
              <b className={pl >= 0 ? 'up' : 'down'}>
                {pl >= 0 ? '+' : '−'}
                {fmtMoney(Math.abs(pl))}
              </b>
            </div>
            {market.status === 'open' && (
              <button className="btn-mini" onClick={() => sellAll(side)}>
                Sell all
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
