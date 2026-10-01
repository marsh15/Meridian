import asyncio
import contextlib
import logging

from sqlalchemy import text
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.worker import Worker

from app.config import settings
from app.db import SessionFactory
from worker.activities import close_market, settle_market
from worker.workflows import MarketLifecycleInput, MarketLifecycleWorkflow, workflow_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("meridian.worker")

STARTER_INTERVAL_S = 5


async def connect() -> Client:
    for attempt in range(30):
        try:
            client = await Client.connect(settings.temporal_address)
            log.info("connected to temporal at %s", settings.temporal_address)
            return client
        except (RPCError, OSError) as err:
            log.warning("temporal unreachable (attempt %d/30): %s", attempt + 1, err)
            await asyncio.sleep(2)
    raise SystemExit(f"could not reach temporal at {settings.temporal_address}")


async def starter(client: Client) -> None:
    """Launch a lifecycle workflow for every live market that lacks one.
    Markets.workflow_started_at is the marker; the deterministic id +
    ALLOW_DUPLICATE_FAILED_ONLY make starts idempotent (running/succeeded
    ids refuse duplication) while a failed run can be replaced. Covers
    markets created before the worker existed."""
    while True:
        try:
            rows = []
            async with SessionFactory() as session:
                rows = (await session.execute(text(
                    "SELECT id, slug, closes_at FROM markets "
                    "WHERE status <> 'resolved' AND workflow_started_at IS NULL "
                    "ORDER BY id LIMIT 200"
                ))).mappings().all()
            for m in rows:
                try:
                    await client.start_workflow(
                        MarketLifecycleWorkflow.run,
                        MarketLifecycleInput(m["id"], m["slug"], m["closes_at"].timestamp()),
                        id=workflow_id(m["id"]),
                        task_queue=settings.temporal_task_queue,
                        # a failed prior run may be replaced (retry-budget
                        # exhaustion, bug) so the market isn't stuck closed;
                        # running/succeeded ids still refuse to duplicate
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    )
                    log.info("started %s (%s)", workflow_id(m["id"]), m["slug"])
                except WorkflowAlreadyStartedError:
                    pass  # already running — fine
                async with SessionFactory() as session, session.begin():
                    await session.execute(
                        text("UPDATE markets SET workflow_started_at = now() WHERE id = :id"),
                        {"id": m["id"]},
                    )
        except Exception:
            log.exception("starter scan failed")
        await asyncio.sleep(STARTER_INTERVAL_S)


async def main() -> None:
    client = await connect()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[MarketLifecycleWorkflow],
        activities=[close_market, settle_market],
    )
    log.info("worker on task queue %s", settings.temporal_task_queue)
    await asyncio.gather(worker.run(), starter(client))


with contextlib.suppress(KeyboardInterrupt):
    asyncio.run(main())
