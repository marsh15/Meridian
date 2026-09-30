import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { fmtVol, fmtDate } from '../lib'
import { useAuth } from '../auth/AuthContext'
import PriceChart from '../components/PriceChart'
import TradePanel from '../components/TradePanel'
import PositionCard from '../components/PositionCard'
import RecentTrades from '../components/RecentTrades'
import MarketCard from '../components/MarketCard'

export default function MarketDetail() {
  const { id } = useParams()
  const [market, setMarket] = useState(null)
  const [related, setRelated] = useState([])
  const [status, setStatus] = useState('loading') // loading | ready | missing
  const [toast, setToastState] = useState(null) // { msg, isError, closing }
  const hideTimer = useRef(null)
  const closeTimer = useRef(null)

  const load = useCallback(() => {
    return api
      .market(id)
      .then((d) => {
        setMarket(d.market)
        setStatus('ready')
        return api.markets().then(({ markets }) => {
          setRelated(
            markets
              .filter((m) => m.id !== d.market.id)
              .sort((a, b) =>
                a.category === d.market.category
                  ? -1
                  : b.category === d.market.category
                    ? 1
                    : 0
              )
              .slice(0, 3)
          )
        })
      })
      .catch(() => setStatus('missing'))
  }, [id])

  useEffect(() => {
    setMarket(null)
    setStatus('loading')
    load()
  }, [load])

  useEffect(() => () => {
    clearTimeout(hideTimer.current)
    clearTimeout(closeTimer.current)
  }, [])

  const setToast = useCallback((msg, isError = false) => {
    clearTimeout(hideTimer.current)
    clearTimeout(closeTimer.current)
    setToastState({ msg, isError, closing: false })
    closeTimer.current = setTimeout(() => {
      setToastState((t) => (t ? { ...t, closing: true } : null))
    }, 3300)
    hideTimer.current = setTimeout(() => setToastState(null), 3500)
  }, [])

  const onDone = useCallback(() => {
    load()
  }, [load])

  if (status === 'missing') {
    return (
      <main className="wrap notfound">
        <h2>Market not found</h2>
        <p>This contract may have expired or never existed.</p>
        <Link className="btn btn-primary" to="/">
          Back to markets
        </Link>
      </main>
    )
  }

  if (status === 'loading' || !market) {
    return (
      <main className="wrap detail-skel" aria-busy="true" aria-label="Loading market">
        <div className="skel t1" aria-hidden="true" />
        <div className="skel t2" aria-hidden="true" />
        <div className="skel t3" aria-hidden="true" />
        <div className="skel t4" aria-hidden="true" />
      </main>
    )
  }

  const up = market.change24h >= 0
  const resolved = market.status === 'resolved'
  const closed = !resolved && new Date(market.closesAt).getTime() < Date.now()

  return (
    <main className="detail wrap">
      <Link to="/" className="back-link">
        ← All markets
      </Link>

      {resolved && (
        <div className={`banner ${market.outcome === 'yes' ? 'up' : 'down'}`}>
          <b>Resolved {market.outcome === 'yes' ? 'YES' : 'NO'}.</b>{' '}
          {market.outcome === 'yes' ? 'YES' : 'NO'} shares paid $1 each;
          the other side expired worthless.
        </div>
      )}
      {closed && (
        <div className="banner neutral">
          <b>Closed {fmtDate(market.closesAt)}.</b> Trading is paused —
          awaiting the creator's resolution.
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
                <b className={up ? 'up' : 'down'}>
                  {up ? '▲' : '▼'} {Math.abs(market.change24h)}¢
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

          <div className="card chart-card">
            <div className="chart-head">
              <span className="chart-title">Yes price · history</span>
              <span className="chart-range">
                {fmtDate(market.history?.[0]?.at || market.createdAt)} —{' '}
                {fmtDate(market.history?.[market.history.length - 1]?.at || market.closesAt)}
              </span>
            </div>
            <PriceChart history={market.history} />
          </div>

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
          className={`toast ${toast.isError ? 'error' : ''} ${toast.closing ? 'closing' : ''}`}
          role={toast.isError ? 'alert' : 'status'}
        >
          {toast.msg}
        </div>
      )}
    </main>
  )
}

function ResolveCard({ slug, onDone, setToast }) {
  const [confirming, setConfirming] = useState(null)
  const { refreshUser } = useAuth()

  async function resolve(outcome) {
    try {
      await api.resolve(slug, outcome)
      setToast(`Market resolved ${outcome.toUpperCase()}`)
      await refreshUser()
      onDone()
    } catch (err) {
      setToast(err.message, true)
    }
  }

  return (
    <div className="card stats-card resolve-card">
      <div className="label card-label">Creator tools</div>
      {confirming ? (
        <>
          <p className="resolve-q">
            Pay $1 per <b>{confirming === 'yes' ? 'YES' : 'NO'}</b> share and
            close this market?
          </p>
          <div className="resolve-btns">
            <button className="btn-mini yes" onClick={() => resolve(confirming)}>
              Confirm {confirming === 'yes' ? 'YES' : 'NO'}
            </button>
            <button className="btn-mini" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </>
      ) : (
        <div className="resolve-btns">
          <button className="btn-mini yes" onClick={() => setConfirming('yes')}>
            Resolve YES
          </button>
          <button className="btn-mini no" onClick={() => setConfirming('no')}>
            Resolve NO
          </button>
        </div>
      )}
    </div>
  )
}
