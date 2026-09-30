"""API-side Temporal bridge (ADR 0008).

The resolve endpoint validates, then asks the market's lifecycle workflow
to settle: ensure the workflow exists (idempotent start), signal the
outcome, and confirm settlement landed. The poll keeps the endpoint's
synchronous contract while execution stays durable in the worker.
"""

import asyncio

from sqlalchemy import text
from temporalio.client import (
    Client,
    WorkflowExecutionAlreadyStartedError,
    WorkflowIDReusePolicy,
)
from temporalio.service import RPCError

from app.config import settings
from app.db import SessionFactory
from worker.workflows import MarketLifecycleInput, MarketLifecycleWorkflow, workflow_id

CONFIRM_TIMEOUT_S = 5.0


class SettlementUnavailable(RuntimeError):
    """The worker did not confirm settlement in time."""


async def request_resolution(market: dict, outcome: str) -> None:
    client = await Client.connect(settings.temporal_address)
    wid = workflow_id(market["id"])
    try:
        handle = await client.start_workflow(
            MarketLifecycleWorkflow.run,
            MarketLifecycleInput(market["id"], market["slug"], market["closes_at"].timestamp()),
            id=wid,
            task_queue=settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowExecutionAlreadyStartedError:
        handle = client.get_workflow_handle(wid)

    try:
        await handle.signal(MarketLifecycleWorkflow.resolve, outcome)
    except RPCError as err:
        # the workflow already completed (late signal on a resolved market)
        raise SettlementUnavailable(
            f"Could not signal settlement for this market: {err}"
        ) from err

    deadline = asyncio.get_running_loop().time() + CONFIRM_TIMEOUT_S
    while asyncio.get_running_loop().time() < deadline:
        async with SessionFactory() as session:
            status = (await session.execute(
                text("SELECT status FROM markets WHERE id = :id"), {"id": market["id"]}
            )).scalar_one_or_none()
        if status == "resolved":
            return
        await asyncio.sleep(0.1)
    raise SettlementUnavailable(
        "Settlement did not confirm in time — the lifecycle worker may be down."
    )
