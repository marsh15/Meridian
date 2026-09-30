"""LMSR engine invariants — the properties the trading system depends on."""

from decimal import Decimal

from app.amm import cost, opening_q, price_yes, proceeds_for_shares, shares_for_dollars


def test_price_always_in_bounds():
    # Raw price is strictly interior everywhere (ADR 0001). The rounded-cents
    # display lives in 1..99 over the band reachable from mid with $1,000
    # balances (gap ≤ ~1,200 shares); markets opened at 5¢/95¢ and pushed
    # hard can display 0¢/100¢ — pre-existing behavior, not a regression.
    for qy, qn in [(0, 0), (250, 0), (0, 250), (-500, 900), (2500, -2500)]:
        assert 0.0 < price_yes(qy, qn) < 1.0, (qy, qn)
    for qy, qn in [(0, 0), (250, 0), (0, 250), (900, -300), (-300, 900)]:
        p = price_yes(qy, qn)
        assert 1 <= round(p * 100) <= 99, (qy, qn, p)


def test_opening_price_matches_seed():
    for cents in (5, 29, 44, 50, 68, 95):
        qy, qn = opening_q(cents)
        assert abs(price_yes(qy, qn) - cents / 100) < 1e-9


def test_buy_yes_raises_yes_price():
    qy, qn = opening_q(50)
    shares = shares_for_dollars(qy, qn, "yes", 10.0)
    assert price_yes(qy + shares, qn) > 0.5


def test_buying_both_sides_equally_leaves_price_unchanged():
    """YES and NO move the same quantity → qYes−qNo difference unchanged."""
    qy, qn = opening_q(30)
    p0 = price_yes(qy, qn)
    shares = shares_for_dollars(qy, qn, "yes", 10.0)
    assert abs(price_yes(qy + shares, qn + shares) - p0) < 1e-9


def test_shares_for_dollars_spends_exactly_the_dollars():
    qy, qn = opening_q(50)
    dollars = 37.50
    shares = shares_for_dollars(qy, qn, "yes", dollars)
    spent = cost(float(qy) + float(shares), float(qn)) - cost(float(qy), float(qn))
    assert abs(spent - dollars) < 1e-6


def test_round_trip_loses_at_most_spread():
    qy, qn = opening_q(50)
    shares = shares_for_dollars(qy, qn, "yes", 50.0)
    proceeds = proceeds_for_shares(qy + shares, qn, "yes", shares)
    assert proceeds < Decimal("50.0")  # never a free lunch
    assert float(proceeds) > 40.0  # but a small round trip keeps most value


def test_monotonic_impact():
    qy, qn = opening_q(30)
    p0 = price_yes(qy, qn)
    small = shares_for_dollars(qy, qn, "yes", 5.0)
    p1 = price_yes(qy + small, qn)
    big = shares_for_dollars(qy, qn, "yes", 200.0)
    p2 = price_yes(qy + big, qn)
    assert p0 < p1 < p2


def test_quantization_to_ten_places():
    shares = shares_for_dollars(*opening_q(50), "yes", 12.34)
    assert isinstance(shares, Decimal)
    assert -shares.as_tuple().exponent <= 10
