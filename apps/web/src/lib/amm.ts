/* client mirror of the server's LMSR math — for live fill estimates only;
   the server is the authority when the order actually executes */

const B = 250;

function logsumexp(a: number, b: number): number {
  const m = Math.max(a, b);
  return m + Math.log(Math.exp(a - m) + Math.exp(b - m));
}

function cost(qYes: number, qNo: number): number {
  return B * logsumexp(qYes / B, qNo / B);
}

export function priceYes(qYes: number, qNo: number): number {
  return 1 / (1 + Math.exp((qNo - qYes) / B));
}

export function sharesForDollars(
  qYes: number, qNo: number, side: "yes" | "no", dollars: number,
): number {
  const c0 = cost(qYes, qNo);
  const spent = (shares: number) =>
    side === "yes" ? cost(qYes + shares, qNo) - c0 : cost(qYes, qNo + shares) - c0;
  let lo = 0;
  let hi = Math.max(dollars * 120, 1);
  // a marginal price under ~0.83¢ makes the true fill exceed the naive
  // dollars*120 bracket — grow it until it contains the root (mirrors amm.py)
  while (spent(hi) < dollars) hi *= 2;
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2;
    if (spent(mid) < dollars) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

export function proceedsForShares(
  qYes: number, qNo: number, side: "yes" | "no", shares: number,
): number {
  const c0 = cost(qYes, qNo);
  const c1 = side === "yes" ? cost(qYes - shares, qNo) : cost(qYes, qNo - shares);
  return c0 - c1;
}
