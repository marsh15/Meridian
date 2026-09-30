"""Market lifecycle workflow under Temporal's time-skipping test server:
timers fire in virtual time, activities run for real against the test
database. Proves the durable path: auto-close on the timer, settlement on
the signal, payouts into the ledger — without a deployed Temporal."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.db import engine
from worker import activities
from worker.workflows import MarketLifecycleInput, MarketLifecycleWorkflow, workflow_id

FUTURE = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
async def env():
    env = await WorkflowEnvironment.start_time_skipping()
    yield env
    await env.shutdown()


async def _setup_market(client, alice) -> tuple[int, str, float]:
    r = await client.post("/api/markets", json={
        "question": "Will the workflow tests pass by October 2026?",
        "category": "Tech", "closesAt": FUTURE,
        "description": "d", "resolution": "r", "initialYes": 50,
    })
    assert r.status_code == 200, r.text
    slug = r.json()["market"]["slug"]
    r = await client.post(f"/api/markets/{slug}/orders", json={
        "side": "yes", "action": "buy", "dollarsCents": 2_000,
    })
    assert r.status_code == 200, r.text
    async with engine.connect() as conn:
        mid, closes_at = (await conn.execute(
            text("SELECT id, closes_at FROM markets WHERE slug = :s"), {"s": slug}
        )).one()
    return mid, slug, closes_at.timestamp()


async def _status(market_id: int) -> str | None:
    async with engine.connect() as conn:
        return (await conn.execute(
            text("SELECT status FROM markets WHERE id = :i"), {"i": market_id}
        )).scalar_one_or_none()


async def _wait_status(market_id: int, want: str, timeout_s: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await _status(market_id) == want:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"market {market_id} never reached status {want!r}")


async def test_timer_closes_then_signal_settles(client, alice, env):
    mid, slug, closes_ts = await _setup_market(client, alice)
    tq = f"test-{uuid.uuid4().hex[:8]}"

    async with Worker(
        env.client, task_queue=tq,
        workflows=[MarketLifecycleWorkflow],
        activities=[activities.close_market, activities.settle_market],
    ):
        handle = await env.client.start_workflow(
            MarketLifecycleWorkflow.run,
            MarketLifecycleInput(mid, slug, closes_ts),
            id=workflow_id(mid), task_queue=tq,
        )

        # virtual time jumps straight past closes_at; the close activity
        # still runs for real against the database
        await env.sleep(closes_ts - datetime.now(timezone.utc).timestamp() + 5)
        await _wait_status(mid, "closed")

        await handle.signal(MarketLifecycleWorkflow.resolve, "yes")
        assert await handle.result() == "yes"

    await _wait_status(mid, "resolved")
    rec = (await client.get("/api/ledger/reconcile")).json()
    assert rec["balanced"] is True
    assert rec["userProjectionMatches"] is True

    # the close + resolution both landed in the outbox for the backbone
    async with engine.connect() as conn:
        kinds = (await conn.execute(
            text("SELECT event_type FROM outbox_events WHERE aggregate = :a ORDER BY id"),
            {"a": f"market:{slug}"},
        )).scalars().all()
    assert kinds == ["MarketCreated", "TradeExecuted", "MarketClosed", "MarketResolved"]


async def test_early_resolution_skips_the_close_timer(client, alice, env):
    mid, slug, closes_ts = await _setup_market(client, alice)
    tq = f"test-{uuid.uuid4().hex[:8]}"

    async with Worker(
        env.client, task_queue=tq,
        workflows=[MarketLifecycleWorkflow],
        activities=[activities.close_market, activities.settle_market],
    ):
        handle = await env.client.start_workflow(
            MarketLifecycleWorkflow.run,
            MarketLifecycleInput(mid, slug, closes_ts),
            id=workflow_id(mid), task_queue=tq,
        )
        await handle.signal(MarketLifecycleWorkflow.resolve, "no")
        assert await handle.result() == "no"

    await _wait_status(mid, "resolved")
    assert await _status(mid) == "resolved"  # never passed through 'closed'
    async with engine.connect() as conn:
        kinds = (await conn.execute(
            text("SELECT event_type FROM outbox_events WHERE aggregate = :a ORDER BY id"),
            {"a": f"market:{slug}"},
        )).scalars().all()
    assert "MarketClosed" not in kinds
    assert kinds[-1] == "MarketResolved"
