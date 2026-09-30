/* client mirror of the server's LMSR math — for live fill estimates only;
   the server is the authority when the order actually executes */

const B = 250

function logsumexp(a, b) {
  const m = Math.max(a, b)
  return m + Math.log(Math.exp(a - m) + Math.exp(b - m))
}

function cost(qYes, qNo) {
  return B * logsumexp(qYes / B, qNo / B)
}

export function priceYes(qYes, qNo) {
  return 1 / (1 + Math.exp((qNo - qYes) / B))
}

export function sharesForDollars(qYes, qNo, side, dollars) {
  const c0 = cost(qYes, qNo)
  let lo = 0
  let hi = Math.max(dollars * 120, 1)
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2
    const c = side === 'yes' ? cost(qYes + mid, qNo) : cost(qYes, qNo + mid)
    if (c - c0 < dollars) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}

export function proceedsForShares(qYes, qNo, side, shares) {
  const c0 = cost(qYes, qNo)
  const c1 = side === 'yes' ? cost(qYes - shares, qNo) : cost(qYes, qNo - shares)
  return c0 - c1
}

/* ---------- formatting ---------- */

export function fmtVol(cents) {
  const v = cents / 100
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${Math.round(v / 1_000)}K`
  return `$${Math.round(v)}`
}

export function fmtMoney(cents) {
  return `$${(cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function fmtDate(iso) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function fmtShortDate(iso) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function timeAgo(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export const CATEGORIES = [
  'Politics', 'Economics', 'Crypto', 'Tech', 'Science', 'Culture', 'Sports', 'Weather',
]
