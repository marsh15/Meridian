/* LMSR (logarithmic market scoring rule) — the pricing engine.
 *
 * Each market holds net outstanding quantities qYes / qNo. The cost
 * function C(q) = B * ln(e^(qYes/B) + e^(qNo/B)) prices any bundle, so a
 * market order fills instantly at the marginal price and moves it
 * continuously. B controls depth: bigger B, softer price impact.
 */
export const B = 250

function logsumexp(a, b) {
  const m = Math.max(a, b)
  return m + Math.log(Math.exp(a - m) + Math.exp(b - m))
}

export function cost(qYes, qNo) {
  return B * logsumexp(qYes / B, qNo / B)
}

/* YES price in [0,1] */
export function priceYes(qYes, qNo) {
  const x = (qNo - qYes) / B
  return 1 / (1 + Math.exp(x))
}

/* quantities that make the market open at a given YES price */
export function openingQ(initialYesCents) {
  const p = initialYesCents / 100
  const d = B * Math.log(p / (1 - p))
  return { qYes: d, qNo: 0 }
}

/* shares bought for exactly `dollars` on one side (binary search on the
 * monotonic cost curve) */
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

/* dollars received for selling `shares` back */
export function proceedsForShares(qYes, qNo, side, shares) {
  const c0 = cost(qYes, qNo)
  const c1 =
    side === 'yes' ? cost(qYes - shares, qNo) : cost(qYes, qNo - shares)
  return c0 - c1
}
