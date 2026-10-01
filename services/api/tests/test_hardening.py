"""Regression tests for the hardening pass: AMM extremes, hostile order
inputs, idempotent replay after close, account-reset market consistency,
session expiry, proxy-header rate limiting, and cross-topic candle
ordering. Each one pins a failure mode found in review."""

import json
import math
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text

from app.amm import cost, price_yes, shares_for_dollars
from app.db import SessionFactory, engine
from app.market_lifecycle import close_market

FUTURE = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%d")


async def _create_market(client, yes=50, question="Will the hardening tests pass by October 2026?"):
    r = await client.post("/api/markets", json={
        "question": question, "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": yes,
    })
    assert r.status_code == 200, r.text
    return r.json()["market"]


async def _buy(client, slug, dollars, side="yes"):
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": side, "action": "buy", "dollarsCents": int(dollars * 100),
    })
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------- AMM extremes -------------------------------


def test_price_survives_extreme_quantity_gap():
    # gap ≈ 178k shares used to raise OverflowError in math.exp and 500
    # every read that computes a price
    assert price_yes(200_000, 0) == 1.0
    assert price_yes(0, 200_000) == 0.0
    # softmax rearrangement matches the naive formula in the safe band
    for qy, qn in [(0, 0), (120, -40), (500, 500), (-250, 900)]:
        assert abs(price_yes(qy, qn) - 1.0 / (1.0 + math.exp((qn - qy) / 250.0))) < 1e-12


async def test_extreme_gap_reaches_market_reads(client, alice):
    m = await _create_market(client, question="Will extreme-gap reads stay alive for the tests?")
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE markets SET q_yes = 200000, q_no = 0 WHERE slug = :s"),
            {"s": m["slug"]},
        )
    r = await client.get("/api/markets")
    assert r.status_code == 200
    row = next(x for x in r.json()["markets"] if x["slug"] == m["slug"])
    assert row["price"] == 100


def test_fill_bracket_grows_past_naive_bound_at_price_extremes():
    # a 0.5¢ YES price (below the API's 5¢ floor, reachable by trading):
    # the true $1 fill is ~199 shares, past the old dollars*120 cap — the
    # buyer used to pay $1 for a $0.60 fill and never know
    from decimal import Decimal

    qy, qn = Decimal("-1323.3"), Decimal(0)
    assert abs(price_yes(qy, qn) - 0.005) < 0.001
    shares = shares_for_dollars(qy, qn, "yes", 1.0)
    assert float(shares) > 120.0
    spent = cost(float(qy) + float(shares), float(qn)) - cost(float(qy), float(qn))
    assert abs(spent - 1.0) < 1e-6  # pays for exactly what it gets


# ----------------------------- hostile inputs -------------------------------


async def test_sell_rejects_hostile_share_values(client, alice):
    m = await _create_market(client)
    await _buy(client, m["slug"], 50)
    # NaN/Infinity travel as bare literals (json.loads accepts them;
    # httpx's json= serializer refuses them, so send raw bodies)
    for raw in [b'{"side":"yes","action":"sell","shares":NaN}',
                b'{"side":"yes","action":"sell","shares":Infinity}']:
        r = await client.post(
            f"/api/markets/{m['slug']}/orders", content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400, (raw, r.status_code, r.text)
    for bad in [1e18, -5.0, 0.0]:
        r = await client.post(f"/api/markets/{m['slug']}/orders", json={
            "side": "yes", "action": "sell", "shares": bad,
        })
        assert r.status_code == 400, (bad, r.status_code, r.text)


async def test_dust_sell_is_rejected_not_rounded_up(client, alice):
    m = await _create_market(client, question="Will dust stay unsellable for the tests?")
    buy = await _buy(client, m["slug"], 1)
    shares = buy["position"]["yes"]["shares"]
    # slice the position so proceeds round below 1¢: sell all but a sliver,
    # then sell the sliver — the sliver's proceeds must be refused
    r = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "sell", "shares": shares,
    })
    assert r.status_code == 200
    # a position whose entire proceeds round to under 1¢ cannot exist here
    # (buys need ≥ $1), so pin the guard with a synthetic micro-sell:
    # selling 1e-10 shares of a real position is under a tenth of a cent
    r = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 100_00,
    })
    assert r.status_code == 200
    r = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "sell", "shares": 1e-10,
    })
    assert r.status_code == 400
    assert "less than 1" in r.json()["error"]


async def test_replay_after_close_returns_original_fill(client, alice):
    m = await _create_market(client)
    key = "replay-after-close"
    r1 = await client.post(
        f"/api/markets/{m['slug']}/orders",
        json={"side": "yes", "action": "buy", "dollarsCents": 2_000},
        headers={"Idempotency-Key": key},
    )
    assert r1.status_code == 200

    async with engine.connect() as conn:
        mid = (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": m["slug"]}
        )).scalar_one()
    assert await close_market(mid) is True

    # retries cluster at close time — the replay must still answer with
    # the stored fill, not "market closed"
    r2 = await client.post(
        f"/api/markets/{m['slug']}/orders",
        json={"side": "yes", "action": "buy", "dollarsCents": 2_000},
        headers={"Idempotency-Key": key},
    )
    assert r2.status_code == 200, r2.text
    assert r1.json() == r2.json()
    # while a genuinely new order is refused
    r3 = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 2_000,
    })
    assert r3.status_code == 400


# --------------------------- account reset sanity ---------------------------


async def _market_q(slug):
    async with engine.connect() as conn:
        row = (await conn.execute(
            text("SELECT q_yes, q_no FROM markets WHERE slug = :s"), {"s": slug}
        )).one()
    return row.q_yes, row.q_no


async def test_reset_sells_back_and_leaves_market_consistent(client, alice):
    m = await _create_market(client, yes=50)
    q0 = await _market_q(m["slug"])
    price0 = (await client.get(f"/api/markets/{m['slug']}")).json()["market"]["price"]

    await _buy(client, m["slug"], 40)
    q1 = await _market_q(m["slug"])
    assert q1[0] > q0[0]  # the buy really moved the book

    r = await client.post("/api/account/reset")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["balanceCents"] == 100_000

    # the AMM book and price are rebased exactly — no phantom inventory
    assert await _market_q(m["slug"]) == q0
    price_now = (await client.get(f"/api/markets/{m['slug']}")).json()["market"]["price"]
    assert price_now == price0

    detail = (await client.get(f"/api/markets/{m['slug']}")).json()["market"]
    assert detail["yourPosition"]["yes"]["shares"] == 0

    rec = (await client.get("/api/ledger/reconcile")).json()
    assert rec["balanced"] and rec["userProjectionMatches"]


async def test_reset_is_rate_limited(client, alice, fake_redis, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "account_resets_per_hour", 2)
    for _ in range(2):
        r = await client.post("/api/account/reset")
        assert r.status_code == 200
    r = await client.post("/api/account/reset")
    assert r.status_code == 429
    assert r.headers.get("retry-after")


# ------------------------------ sessions/auth -------------------------------


async def test_expired_session_token_is_refused(client, alice):
    token = "expired-token-for-tests"
    async with SessionFactory() as session:
        await session.execute(
            text("INSERT INTO sessions (token, user_id, expires_at) "
                 "VALUES (:t, :u, now() - interval '1 minute')"),
            {"t": token, "u": alice["id"]},
        )
        await session.commit()
    me = await client.get("/api/auth/me", headers={"Cookie": f"meridian_session={token}"})
    assert me.json()["user"] is None
    portfolio = await client.get("/api/portfolio", headers={"Cookie": f"meridian_session={token}"})
    assert portfolio.status_code == 401


async def test_reconcile_requires_auth(client, alice):

    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as fresh:
        r = await fresh.get("/api/ledger/reconcile")
    assert r.status_code == 401


async def test_login_unknown_email_is_plain_401(client, alice):
    r = await client.post("/api/auth/login", json={
        "email": "nobody@test.io", "password": "wrong-password",
    })
    assert r.status_code == 401
    assert "Wrong email or password" in r.json()["error"]


# --------------------------- rate-limit spoofing ----------------------------


async def test_forwarded_header_spoofing_does_not_bypass_limits(
    client, fake_redis, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "auth_requests_per_minute", 2)
    # rotating X-Forwarded-For per request must not mint fresh limit keys
    # when proxy headers aren't trusted (the default)
    for i in range(3):
        r = await client.post(
            "/api/auth/login",
            json={"email": f"x{i}@test.io", "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
        if i < 2:
            assert r.status_code == 401
        else:
            assert r.status_code == 429


async def test_proxy_headers_honored_when_trusted(client, fake_redis, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "auth_requests_per_minute", 2)
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    for i in range(3):  # distinct trusted XFF values → distinct keys
        r = await client.post(
            "/api/auth/login",
            json={"email": f"y{i}@test.io", "password": "wrong-password"},
            headers={"X-Forwarded-For": f"10.1.0.{i}"},
        )
        assert r.status_code == 401  # never limited


# --------------------------- candle ordering guard --------------------------


async def test_late_trade_cannot_overwrite_settlement_candle(client, alice):
    from consumers import candles

    m = await _create_market(client, question="Will the candle guard pass by October 2026?")
    await _buy(client, m["slug"], 20)
    res = await client.post(f"/api/markets/{m['slug']}/resolve", json={"outcome": "yes"})
    assert res.status_code == 200

    async with engine.connect() as conn:
        mid = (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": m["slug"]}
        )).scalar_one()
        events = (await conn.execute(
            text("SELECT o.id, o.aggregate, o.event_type, o.payload, o.created_at, "
                 "m.id AS market_id FROM outbox_events o "
                 "LEFT JOIN markets m ON 'market:' || m.slug = o.aggregate "
                 "WHERE o.event_type IN ('TradeExecuted', 'MarketResolved') ORDER BY o.id")
        )).mappings().all()
    from relay.main import build_message

    evs = [json.loads(json.dumps(build_message(r))) for r in events]
    resolve_ev = next(e for e in evs if e["type"] == "MarketResolved")
    trade_evs = [e for e in evs if e["type"] == "TradeExecuted"]

    # deliver resolve FIRST (cross-topic reordering), then the pre-resolution
    # trades — the settlement candle must survive
    for ev in [resolve_ev, *trade_evs]:
        async with SessionFactory() as session, session.begin():
            await candles.handle(session, ev)
    async with engine.connect() as conn:
        rows = (await conn.execute(
            text("SELECT close_cents, trades FROM candles_1m WHERE market_id = :m "
                 "ORDER BY bucket_start"), {"m": mid}
        )).all()
    assert rows, "resolve should have written the settlement candle"
    assert rows[-1].close_cents == 100
    assert rows[-1].trades == 0  # the late trade was skipped, not merged
