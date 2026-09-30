import { useEffect, useState } from 'react'
import { api } from '../api'

export default function TickerTape() {
  const [markets, setMarkets] = useState([])

  useEffect(() => {
    let alive = true
    api.markets().then((d) => alive && setMarkets(d.markets)).catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  if (!markets.length) return null
  const items = [...markets, ...markets]

  return (
    <div className="tape" aria-hidden="true">
      <div className="tape-inner">
        {items.map((m, i) => (
          <span className="tape-item" key={`${m.id}-${i}`}>
            <span className="sym">{m.ticker}</span>
            <span className="px">{m.price}¢</span>
            <span className={`chg ${m.change24h >= 0 ? 'up' : 'down'}`}>
              {m.change24h >= 0 ? '▲' : '▼'} {Math.abs(m.change24h)}
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}
