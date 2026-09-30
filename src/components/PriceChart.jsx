import { useId, useMemo, useState } from 'react'

const W = 640
const H = 250
const PAD = { l: 34, r: 20, t: 14, b: 22 }

/* history: [{ price, at }] — at is an ISO timestamp */
export default function PriceChart({ history }) {
  const gradId = useId()
  const [hover, setHover] = useState(null)
  const n = history.length

  const { pts, area, ticks } = useMemo(() => {
    const iw = W - PAD.l - PAD.r
    const ih = H - PAD.t - PAD.b
    const x = (i) => PAD.l + (i / Math.max(n - 1, 1)) * iw
    const y = (v) => PAD.t + (1 - v / 100) * ih
    const pts = history.map((h, i) => ({ x: x(i), y: y(h.price), v: h.price }))
    const area = `M ${PAD.l},${H - PAD.b} L ${pts
      .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
      .join(' L ')} L ${W - PAD.r},${H - PAD.b} Z`
    const ticks = [25, 50, 75].map((v) => ({ v, y: y(v) }))
    return { pts, area, ticks }
  }, [history, n])

  if (n < 2) {
    return (
      <div className="chart-empty">
        {n === 1
          ? `Opened at ${history[0].price}¢ — no trades yet.`
          : 'No price history yet.'}
      </div>
    )
  }

  const last = pts[n - 1]
  const first = pts[0]
  const up = last.v >= first.v
  const stroke = up ? 'var(--up)' : 'var(--down)'

  function onMove(e) {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    const i = Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (n - 1))
    if (i >= 0 && i < n) setHover(i)
  }

  const hp = hover != null ? pts[hover] : null
  const fmt = (iso) =>
    new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  return (
    <div className="chart-box">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.25" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>

        {ticks.map((t) => (
          <g key={t.v}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={t.y}
              y2={t.y}
              stroke="var(--grid-line)"
              strokeDasharray="3 4"
            />
            <text
              x={PAD.l - 7}
              y={t.y + 3}
              textAnchor="end"
              fontSize="10"
              fill="var(--muted)"
            >
              {t.v}¢
            </text>
          </g>
        ))}

        <path d={area} fill={`url(#${gradId})`} />
        <polyline
          points={pts.map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke={stroke}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        <circle cx={last.x} cy={last.y} r="4" fill={stroke} />
        <circle cx={last.x} cy={last.y} r="8" fill={stroke} opacity="0.25" />

        {hp && (
          <g>
            <line
              x1={hp.x}
              x2={hp.x}
              y1={PAD.t}
              y2={H - PAD.b}
              stroke="var(--muted)"
              strokeDasharray="2 3"
            />
            <circle
              cx={hp.x}
              cy={hp.y}
              r="4.5"
              fill="var(--bg)"
              stroke={stroke}
              strokeWidth="2"
            />
          </g>
        )}

        <text x={PAD.l} y={H - 6} fontSize="10" fill="var(--muted)">
          {fmt(history[0].at)}
        </text>
        <text x={W - PAD.r} y={H - 6} fontSize="10" fill="var(--muted)" textAnchor="end">
          {fmt(history[n - 1].at)}
        </text>
      </svg>

      {hp && (
        <div
          className="chart-tip"
          style={{ left: `${(hp.x / W) * 100}%`, top: `${(hp.y / H) * 100}%` }}
        >
          {hp.v}¢ · {fmt(history[hover].at)}
        </div>
      )}
    </div>
  )
}
