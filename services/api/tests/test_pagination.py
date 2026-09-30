"""Keyset pagination on trades and price history: windows are stable under
live inserts, walks don't skip or repeat rows, limits are clamped server-side."""

from datetime import datetime, timedelta, timezone

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


async def _create_market(client, yes=50):
    r = await client.post("/api/markets", json={
        "question": "Will the pagination tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": yes,
    })
    assert r.status_code == 200, r.text
    return r.json()["market"]


async def _make_trades(client, slug, n):
    for _ in range(n):
        r = await client.post(f"/api/markets/{slug}/orders", json={
            "side": "yes", "action": "buy", "dollarsCents": 100,
        })
        assert r.status_code == 200, r.text


async def test_trades_walk_pages_without_gaps(client, alice):
    m = await _create_market(client)
    await _make_trades(client, m["slug"], 7)

    detail = (await client.get(f"/api/markets/{m['slug']}")).json()["market"]
    assert len(detail["trades"]) == 7  # under the 25 default, one page
    assert detail["tradesNextBeforeId"] is None

    seen: list[int] = []
    before = None
    for _ in range(5):
        url = f"/api/markets/{m['slug']}/trades?limit=3"
        if before is not None:
            url += f"&before_id={before}"
        r = await client.get(url)
        assert r.status_code == 200, r.text
        page = r.json()
        seen.extend(t["id"] for t in page["trades"])
        assert [t["id"] for t in page["trades"]] == sorted(
            (t["id"] for t in page["trades"]), reverse=True
        )  # newest first within the page
        before = page["nextBeforeId"]
        if before is None:
            break
    assert len(seen) == 7 and len(set(seen)) == 7  # all rows, no repeats


async def test_trades_limit_clamped(client, alice):
    m = await _create_market(client)
    await _make_trades(client, m["slug"], 1)
    for bad in ("0", "101", "-1"):
        r = await client.get(f"/api/markets/{m['slug']}/trades?limit={bad}")
        assert r.status_code == 400, f"limit={bad} should be rejected"
        assert r.json()["error"] == "Invalid request."
    r = await client.get("/api/markets/does-not-exist/trades")
    assert r.status_code == 404


async def test_history_walks_backwards(client, alice):
    m = await _create_market(client)
    await _make_trades(client, m["slug"], 4)  # 1 opening + 4 trade prices

    detail = (await client.get(f"/api/markets/{m['slug']}")).json()["market"]
    assert len(detail["history"]) == 5
    assert detail["historyNextBeforeId"] is None

    # newest window first, in chronological order
    p1 = (await client.get(f"/api/markets/{m['slug']}/history?limit=3")).json()
    assert len(p1["history"]) == 3
    assert p1["history"][0]["at"] <= p1["history"][-1]["at"]
    assert p1["nextBeforeId"] is not None

    # older window continues without overlap
    p2 = (
        await client.get(f"/api/markets/{m['slug']}/history?limit=3&before_id={p1['nextBeforeId']}")
    ).json()
    assert len(p2["history"]) == 2
    assert p2["nextBeforeId"] is None
    assert p2["history"][-1]["at"] < p1["history"][0]["at"]
    assert len({h["at"] for h in p1["history"] + p2["history"]}) == 5

    r = await client.get("/api/markets/does-not-exist/history")
    assert r.status_code == 404
