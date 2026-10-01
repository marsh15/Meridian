"""LMSR (logarithmic market scoring rule) — the pricing engine.

Ported 1:1 from server/amm.js. Each market holds net outstanding quantities
q_yes/q_no; the cost function C(q) = B·ln(e^(qYes/B) + e^(qNo/B)) prices any
bundle, so a market order fills instantly at the marginal price. B controls
depth: bigger B, softer price impact.

The math runs in floats (LMSR is irrational — see ADR 0005); every value that
crosses the database boundary is quantized to 10 decimal places.
"""

import math
from decimal import ROUND_DOWN, Decimal

B = 250.0

TEN_PLACES = Decimal("0.0000000001")


def q(value: Decimal | float) -> Decimal:
    return Decimal(value).quantize(TEN_PLACES, rounding=ROUND_DOWN)  # type: ignore[arg-type]


def _f(value: Decimal | float) -> float:
    return float(value)


def cost(q_yes: Decimal | float, q_no: Decimal | float) -> float:
    a, b = _f(q_yes) / B, _f(q_no) / B
    m = max(a, b)
    return B * (m + math.log(math.exp(a - m) + math.exp(b - m)))


def price_yes(q_yes: Decimal | float, q_no: Decimal | float) -> float:
    """YES price in (0, 1). Softmax form: subtracting the max keeps both
    exp() arguments ≤ 0, so extreme quantity gaps saturate toward 0/1
    instead of overflowing."""
    a, b = _f(q_yes) / B, _f(q_no) / B
    m = max(a, b)
    e = math.exp(a - m)
    return e / (e + math.exp(b - m))


def opening_q(initial_yes_cents: int) -> tuple[Decimal, Decimal]:
    """Quantities that make the market open at a given YES price."""
    p = initial_yes_cents / 100
    d = B * math.log(p / (1 - p))
    return q(d), q(0)


def shares_for_dollars(
    q_yes: Decimal | float, q_no: Decimal | float, side: str, dollars: float
) -> Decimal:
    """Shares bought for exactly `dollars` on one side (binary search on the
    monotonic cost curve)."""

    def spent(shares: float) -> float:
        c = cost(_f(q_yes) + shares, q_no) if side == "yes" else cost(q_yes, _f(q_no) + shares)
        return c - c0

    c0 = cost(q_yes, q_no)
    lo, hi = 0.0, max(dollars * 120, 1.0)
    # a marginal price under ~0.83¢ makes the true fill exceed the naive
    # dollars*120 bracket — grow it until the bracket actually contains the
    # root, or the search silently returns the cap and overcharges
    while spent(hi) < dollars:
        hi *= 2.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if spent(mid) < dollars:
            lo = mid
        else:
            hi = mid
    return q((lo + hi) / 2)


def proceeds_for_shares(
    q_yes: Decimal | float, q_no: Decimal | float, side: str, shares: Decimal | float
) -> Decimal:
    """Dollars received for selling `shares` back."""
    c0 = cost(q_yes, q_no)
    c1 = (
        cost(_f(q_yes) - _f(shares), q_no)
        if side == "yes"
        else cost(q_yes, _f(q_no) - _f(shares))
    )
    return q(c0 - c1)
