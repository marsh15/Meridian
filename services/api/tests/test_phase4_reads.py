"""Chart candles (range bucketing, volume, markers) and public trader
profiles — the phase 4 product-surface reads."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db import engine

FUTURE = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%d")


async def _create_market(client, yes=50):
    r = await client.post("/api/markets", json={
        "question": "Will the phase 4 reads pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": yes,
    })
    assert r.status_code == 200, r.text
    return r.json()["market"]


async def _buy(client, slug, dollars):
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": dollars * 100,
    })
    assert r.status_code == 200, r.text


async def test_candles_bucket_prices_and_volume(client, alice):
    m = await _create_market(client)
    await _buy(client, m["slug"], 10)
    await _buy(client, m["slug"], 5)

    r = await client.get(f"/api/markets/{m['slug']}/candles?range=1h")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["range"] == "1h" and body["bucket"] == "1 minute"

    # opening row + 2 trades → at least 2 buckets; volume sums to $15
    candles = body["candles"]
    assert len(candles) >= 1
    assert sum(c["v"] for c in candles) == 1_500
    first = candles[0]
    assert {"t", "o", "h", "l", "c", "v"} == set(first.keys())
    assert first["o"] == 50  # opening price starts the series
    assert all(c["l"] <= c["h"] for c in candles)
    assert candles == sorted(candles, key=lambda c: c["t"])

    # the resolution marker lands when the market resolves
    res = await client.post(f"/api/markets/{m['slug']}/resolve", json={"outcome": "yes"})
    assert res.status_code == 200
    r = await client.get(f"/api/markets/{m['slug']}/candles?range=1h")
    kinds = [mk["kind"] for mk in r.json()["markers"]]
    assert "open" in kinds and "resolved" in kinds
    # resolution prices the series at 100
    assert r.json()["candles"][-1]["c"] == 100


async def test_candles_ranges_validated(client, alice):
    m = await _create_market(client)
    for bad in ("1x", "", "2d", "ALL", "1h1"):
        r = await client.get(f"/api/markets/{m['slug']}/candles?range={bad}")
        assert r.status_code == 400, f"range={bad!r} should 400"
    r = await client.get("/api/markets/nope/candles?range=1d")
    assert r.status_code == 404


async def test_user_profile_shape_and_lookup(client, alice, bob, user_client):
    ca = await user_client("alice@test.io")
    cb = await user_client("bob@test.io")
    m = await _create_market(ca)
    await _buy(ca, m["slug"], 20)
    await _buy(cb, m["slug"], 10)

    r = await client.get("/api/users/alice")
    assert r.status_code == 200, r.text
    body = r.json()
    u = body["user"]
    assert u["displayName"] == "Alice"
    assert u["tradesCount"] == 1
    assert u["cashCents"] == 100_000 - 2_000
    assert u["realizedPnlCents"] == -2_000
    assert u["volumeCents"] == 2_000
    assert u["joinedAt"]

    assert len(body["recentTrades"]) == 1
    t = body["recentTrades"][0]
    assert t["slug"] == m["slug"] and t["action"] == "buy" and t["side"] == "yes"

    assert len(body["positions"]) == 1
    p = body["positions"][0]
    assert p["side"] == "yes"
    assert p["status"] == "open"
    assert p["valueCents"] == round(p["shares"] * p["priceCents"])

    # slug-style lookup also resolves ("Phase3 Demo" style names)
    async with engine.connect() as conn:
        await conn.execute(text("UPDATE users SET display_name = 'Maya Chen' "
                                "WHERE email = 'alice@test.io'"))
        await conn.commit()
    r = await client.get("/api/users/maya-chen")
    assert r.status_code == 200
    assert r.json()["user"]["displayName"] == "Maya Chen"

    # house/demo accounts are not public profiles
    r = await client.get("/api/users/nobody-here")
    assert r.status_code == 404
