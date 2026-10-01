"""Double-entry ledger correctness: every money movement posts balanced
entries, the database refuses unbalanced journals, users.balance_cents
tracks the user_cash account exactly, and the reconciliation endpoint
proves all of it. Leaderboard and portfolio read from the journal."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.db import engine
from app.ledger import (
    KIND_MARKET_ESCROW,
    KIND_SYSTEM,
    KIND_USER_CASH,
    Entry,
    account_id,
    post_burn,
    post_entries,
    post_mint,
)

FUTURE = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%d")


async def _create_market(client, yes=50, question="Will the ledger tests pass by October 2026?"):
    r = await client.post("/api/markets", json={
        "question": question, "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": yes,
    })
    assert r.status_code == 200, r.text
    return r.json()["market"]


async def _buy(client, slug, dollars, side="yes"):
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": side, "action": "buy", "dollarsCents": dollars * 100,
    })
    assert r.status_code == 200, r.text
    return r.json()


async def _reconcile(client) -> dict:
    r = await client.get("/api/ledger/reconcile")
    assert r.status_code == 200
    return r.json()


async def _ledger_balance(kind: str, **ids) -> int:
    async with engine.connect() as conn:
        cents = (await conn.execute(
            text("SELECT COALESCE(SUM(CASE WHEN e.direction = 'debit' THEN e.amount_cents "
                 "ELSE -e.amount_cents END), 0) FROM ledger_entries e "
                 "JOIN ledger_accounts a ON a.id = e.account_id "
                 "WHERE a.kind = :k AND a.user_id IS NOT DISTINCT FROM :u "
                 "AND a.market_id IS NOT DISTINCT FROM :m"),
            {"k": kind, "u": ids.get("user_id"), "m": ids.get("market_id")},
        )).scalar_one()
    return int(cents)


async def test_signup_mints_and_reconcile_is_green(client, alice):
    rec = await _reconcile(client)
    assert rec["balanced"] is True
    assert rec["userProjectionMatches"] is True
    assert rec["totalDebitCents"] == rec["totalCreditCents"] == 100_000
    assert await _ledger_balance(KIND_USER_CASH, user_id=alice["id"]) == 100_000


async def test_buy_sell_post_balanced_escrow_entries(client, alice):
    m = await _create_market(client)
    buy = await _buy(client, m["slug"], 40)
    rec = await _reconcile(client)
    assert rec["balanced"] is True
    assert buy["balanceCents"] == 100_000 - 4_000

    async with engine.connect() as conn:
        mid = (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": m["slug"]}
        )).scalar_one()
    assert await _ledger_balance(KIND_MARKET_ESCROW, market_id=mid) == 4_000
    assert await _ledger_balance(KIND_USER_CASH, user_id=alice["id"]) == 96_000

    shares = buy["position"]["yes"]["shares"]
    r = await client.post(f"/api/markets/{m['slug']}/orders", json={
        "side": "yes", "action": "sell", "shares": shares,
    })
    assert r.status_code == 200
    sold = r.json()
    escrow = await _ledger_balance(KIND_MARKET_ESCROW, market_id=mid)
    user = await _ledger_balance(KIND_USER_CASH, user_id=alice["id"])
    assert escrow == 4_000 - sold["fill"]["amountCents"]  # proceeds left escrow
    assert user == sold["balanceCents"]  # projection still equals the journal
    rec = await _reconcile(client)
    assert rec["balanced"] and rec["userProjectionMatches"]


async def test_resolution_payouts_post_and_reconcile(client, alice, bob, user_client):
    ca = await user_client("alice@test.io")
    cb = await user_client("bob@test.io")
    m = await _create_market(ca)
    await _buy(ca, m["slug"], 100, side="yes")
    await _buy(cb, m["slug"], 100, side="no")

    res = await ca.post(f"/api/markets/{m['slug']}/resolve", json={"outcome": "yes"})
    assert res.status_code == 200, res.text

    rec = await _reconcile(client)
    assert rec["balanced"] is True, rec
    assert rec["userProjectionMatches"] is True, rec

    me_a = (await ca.get("/api/auth/me")).json()["user"]
    assert await _ledger_balance(KIND_USER_CASH, user_id=me_a["id"]) == me_a["balanceCents"]

    async with engine.connect() as conn:
        mid = (await conn.execute(
            text("SELECT id FROM markets WHERE slug = :s"), {"s": m["slug"]}
        )).scalar_one()
        payout_rows = (await conn.execute(
            text("SELECT amount_cents FROM ledger_entries WHERE ref_type = 'payout' "
                 "AND market_id = :m AND direction = 'debit'"),
            {"m": mid},
        )).scalars().all()
    assert len(payout_rows) == 1  # only the YES holder was paid
    # sub-cent truncation and unsold losing-side inventory drain to the
    # system account — a resolved market's escrow ends at exactly zero
    drain = 20_000 - sum(payout_rows)
    assert await _ledger_balance(KIND_MARKET_ESCROW, market_id=mid) == 0
    # system carries -200k from the two signup mints plus the drain
    assert await _ledger_balance(KIND_SYSTEM) == -200_000 + drain


async def test_database_rejects_unbalanced_journal(client, alice):
    from app.db import SessionFactory

    # app-level guard fires synchronously at the call site
    async with SessionFactory() as session, session.begin():
        with pytest.raises(ValueError, match="unbalanced"):
            await post_entries(session, "app-level", [
                Entry(KIND_SYSTEM, "debit", 100, ref_type="test"),
                Entry(KIND_USER_CASH, "credit", 99, user_id=alice["id"], ref_type="test"),
            ])

    # the deferred constraint trigger is the database-level backstop: the
    # journal refuses to commit a transaction whose legs do not sum
    async with SessionFactory() as session:
        acc = await account_id(session, kind=KIND_SYSTEM)
        ua = await account_id(session, kind=KIND_USER_CASH, user_id=alice["id"])
        await session.execute(
            text("INSERT INTO ledger_entries (transaction_id, account_id, direction, "
                 "amount_cents, ref_type) VALUES ('bad-tx', :a, 'debit', 500, 'test')"),
            {"a": acc},
        )
        await session.execute(
            text("INSERT INTO ledger_entries (transaction_id, account_id, direction, "
                 "amount_cents, ref_type) VALUES ('bad-tx', :a, 'credit', 499, 'test')"),
            {"a": ua},
        )
        with pytest.raises(Exception, match="unbalanced"):
            await session.commit()


async def test_reset_accounts_mint_and_burn(client, alice):
    m = await _create_market(client)
    await _buy(client, m["slug"], 30)
    r = await client.post("/api/account/reset")
    assert r.status_code == 200
    assert r.json()["user"]["balanceCents"] == 100_000
    rec = await _reconcile(client)
    assert rec["balanced"] is True
    assert rec["userProjectionMatches"] is True


async def test_leaderboard_and_portfolio_read_the_journal(client, alice, bob, user_client):
    ca = await user_client("alice@test.io")
    cb = await user_client("bob@test.io")
    m = await _create_market(ca)
    await _buy(ca, m["slug"], 50, side="yes")
    await _buy(cb, m["slug"], 25, side="no")

    board = (await client.get("/api/leaderboard")).json()["leaderboard"]
    assert len(board) == 2
    a = next(x for x in board if x["trader"] == "Alice")
    b = next(x for x in board if x["trader"] == "Bob")
    assert a["cashCents"] == 100_000 - 5_000
    assert a["mintedCents"] == 100_000
    assert a["realizedPnlCents"] == -5_000  # unrealized loss doesn't show here
    assert a["volumeCents"] == 5_000
    assert b["volumeCents"] == 2_500
    assert board[0]["realizedPnlCents"] >= board[1]["realizedPnlCents"]

    p = (await ca.get("/api/portfolio")).json()
    assert p["cashCents"] == 95_000
    assert p["mintedCents"] == 100_000
    assert p["realizedPnlCents"] == -5_000
    assert len(p["positions"]) == 1
    pos = p["positions"][0]
    assert pos["side"] == "yes" and pos["shares"] > 0
    assert pos["status"] == "open"
    assert pos["pnlCents"] == pos["valueCents"] - pos["costCents"]
    assert p["positionsValueCents"] == pos["valueCents"]
    assert p["netWorthCents"] == p["cashCents"] + p["positionsValueCents"]

    import httpx

    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as fresh:
        unauth = await fresh.get("/api/portfolio")
    assert unauth.status_code == 401


async def test_post_mint_and_burn_helpers(client, alice):
    from app.db import SessionFactory

    async with SessionFactory() as session, session.begin():
        await post_mint(session, alice["id"], 500, "test mint")
        await post_burn(session, alice["id"], 200, "test burn")
    assert await _ledger_balance(KIND_USER_CASH, user_id=alice["id"]) == 100_300
    assert await _ledger_balance(KIND_SYSTEM) == -100_300  # system absorbs the mint
